"""Universal Headless ODB Result Extractor & Evidence Lineage Binding Engine.

Executes authentic finite element result extractions directly from binary .odb
databases using native Abaqus Python (headless `abaqus python <script.py>`),
without requiring a GUI or persistent CAE session.

Contract & Fail-Closed Discipline:
1. Reuses authentic extraction script generation from `execution.results` and `execution.odb`.
2. Validates genuine binary ODB presence; immediately blocks on corrupt, empty, or mock JSON files.
3. Manages independent subprocess execution (`abaqus python`) with strict timeouts and error classification.
4. Enforces strict causal lineage binding: embeds `run_id`, `input_hash`, `odb_path`,
   `odb_sha256`, and verified physical units into every `ResultExtraction` and `Evidence` record.
5. Strictly zero tolerance for synthetic fallback: missing fields, corrupt ODBs, or process
   failures raise explicit typed exceptions and NEVER return synthetic benchmark constants.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import sys
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from .client import AbaqusExecutor
from .results import extract_requirement
from .solver import find_abaqus_executable, is_authentic_binary_odb, has_native_odb_access
from ..contracts.results import (
    ResultExtraction,
    ResultRequirement,
    requirements_from_criteria,
)
from ..evidence.model import Evidence


class OdbExtractionError(RuntimeError):
    """Base exception for all authentic ODB extraction failures."""
    pass


class OdbFileNotFoundError(OdbExtractionError):
    """Raised when the requested ODB file does not exist on disk."""
    pass


class OdbCorruptOrInvalidError(OdbExtractionError):
    """Raised when the target file is not an authentic binary ODB (e.g. empty, JSON mock)."""
    pass


class AbaqusLauncherNotFoundError(OdbExtractionError):
    """Raised when no authentic Abaqus executable can be resolved to run abaqus python."""
    pass


class ExtractionExecutionError(OdbExtractionError):
    """Raised when the abaqus python extraction process times out or exits with an error."""
    pass


class ExtractionFieldNotFoundError(OdbExtractionError):
    """Raised when requested steps, frames, fields, or history outputs are missing from the ODB."""
    pass


@dataclass(frozen=True)
class OdbExtractionReport:
    """Complete container of authentically extracted physical results and causal evidence."""
    run_id: str
    input_hash: str
    odb_path: Path
    odb_sha256: str
    extractions: Tuple[ResultExtraction, ...]
    metrics: Dict[str, float]
    evidence: Tuple[Evidence, ...]
    metadata: Dict[str, Any] = field(default_factory=dict)
    energy_evidence: Optional[Dict[str, Any]] = None
    timestamp: float = field(default_factory=time.time)

    def get_extraction(self, value_key: str) -> Optional[ResultExtraction]:
        for ext in self.extractions:
            req = ext.requirement
            if req.value_key == value_key or req.name == value_key:
                return ext
        return None


def _resolve_safe_odb_region(odb: Any, expr: Any) -> Any:
    """Safely resolve an ODB region expression without invoking arbitrary code execution.

    Enforces a strict AST whitelist:
    - Base variable must strictly be `odb`.
    - Allowed operations: attribute traversal and subscripting with string constants only.
    - Disallowed: function/method calls, arithmetic, comprehension, imports, dunder attributes.
    - Fail-Closed: Raises ExtractionFieldNotFoundError or OdbExtractionError on any
      unrecognized syntax or resolution failure. NEVER falls back to returning the raw string.
    """
    if not isinstance(expr, str):
        return expr

    expr_clean = expr.strip()
    if not expr_clean:
        raise OdbExtractionError("Empty ODB region expression")

    try:
        tree = ast.parse(expr_clean, mode="eval")
    except SyntaxError as exc:
        raise OdbExtractionError(f"Malformed ODB region syntax {expr!r}: {exc}") from exc

    def _eval_node(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)
        if isinstance(node, ast.Name):
            if node.id == "odb":
                return odb
            raise OdbExtractionError(f"Unauthorized identifier in region expression: {node.id!r}")
        if isinstance(node, ast.Attribute):
            val = _eval_node(node.value)
            attr = node.attr
            if attr.startswith("_"):
                raise OdbExtractionError(f"Access to private/dunder attribute {attr!r} forbidden")
            try:
                return getattr(val, attr)
            except AttributeError as exc:
                raise ExtractionFieldNotFoundError(f"Attribute {attr!r} not found on ODB object: {exc}") from exc
        if isinstance(node, ast.Subscript):
            val = _eval_node(node.value)
            slice_node = node.slice
            if isinstance(slice_node, ast.Index):  # Compatibility for Python < 3.9
                slice_node = slice_node.value
            if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
                key = slice_node.value
            elif isinstance(slice_node, getattr(ast, "Str", type(None))):
                key = slice_node.s
            else:
                raise OdbExtractionError("Only string constant subscripts are permitted in region expressions")
            try:
                return val[key]
            except (KeyError, IndexError, TypeError) as exc:
                raise ExtractionFieldNotFoundError(f"Key {key!r} not found in ODB collection: {exc}") from exc
        raise OdbExtractionError(f"Disallowed AST node type {type(node).__name__} in region expression: {expr!r}")

    resolved = _eval_node(tree)
    if resolved is None or isinstance(resolved, str):
        raise OdbExtractionError(f"Region expression {expr!r} did not resolve to an authentic ODB set object")
    return resolved


class HeadlessAbaqusPythonExecutor(AbaqusExecutor):
    """Host-side adapter that executes Python snippets inside native Abaqus Python.

    Invokes `abaqus python <temp_script.py>` in a controlled subprocess,
    capturing stdout JSON envelopes and mapping solver tracebacks to typed exceptions.
    Supports dependency-injected `custom_runner` for hermetic unit testing.
    """

    def __init__(
        self,
        launcher_cmd: Optional[str] = None,
        workdir: Optional[Union[str, Path]] = None,
        timeout: int = 120,
        custom_runner: Optional[Callable[[str], Any]] = None,
    ):
        self.launcher_cmd = launcher_cmd
        if workdir:
            self.workdir = Path(workdir).resolve()
        else:
            # Do not invent a solver directory at construction time. A missing
            # customer project must fail when execution is requested, not silently
            # land beside the product checkout or in the process temp directory.
            self.workdir = None
        self.timeout = timeout
        self.custom_runner = custom_runner

    def execute(self, code: str, timeout: Optional[int] = None) -> Any:
        if self.custom_runner is not None:
            return self.custom_runner(code)

        effective_timeout = timeout or self.timeout
        if self.workdir is None:
            raise ValueError(
                "ODB extraction requires a customer project workdir. "
                "Pass workdir inside the customer project solver/ directory. "
                "Nothing is written beside the product checkout."
            )
        from ..paths import assert_path_outside_core_workspace
        assert_path_outside_core_workspace(self.workdir)
        resolved_launcher = find_abaqus_executable(self.launcher_cmd)
        if not resolved_launcher:
            if has_native_odb_access() and sys.executable:
                resolved_launcher = sys.executable
            else:
                raise AbaqusLauncherNotFoundError(
                    f"Abaqus executable not found (launcher_cmd={self.launcher_cmd!r}). "
                    "Authentic ODB extraction requires an authentic Abaqus installation."
                )

        self.workdir.mkdir(parents=True, exist_ok=True)
        script_id = uuid.uuid4().hex[:12]
        script_file = self.workdir / f"_odb_extract_{script_id}.py"

        try:
            script_file.write_text(code, encoding="utf-8")
            if resolved_launcher == sys.executable:
                cmd = [sys.executable, str(script_file.name)]
            else:
                cmd = [resolved_launcher, "python", str(script_file.name)]
            use_shell = (os.name == "nt")

            proc = subprocess.run(
                cmd,
                cwd=str(self.workdir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=effective_timeout,
                shell=use_shell,
            )

            if proc.returncode != 0:
                err_msg = (
                    f"Abaqus Python extraction failed with returncode {proc.returncode}.\n"
                    f"STDOUT:\n{proc.stdout.strip()}\n"
                    f"STDERR:\n{proc.stderr.strip()}"
                )
                if "KeyError" in proc.stderr or "KeyError" in proc.stdout:
                    raise ExtractionFieldNotFoundError(err_msg)
                raise ExtractionExecutionError(err_msg)

            raw_out = proc.stdout.strip()
            if not raw_out:
                if proc.stderr:
                    raise ExtractionExecutionError(f"Abaqus Python returned empty output. STDERR:\n{proc.stderr}")
                raise ExtractionExecutionError("Abaqus Python extraction produced no output.")

            # Decode JSON payload from stdout lines
            for line in reversed(raw_out.splitlines()):
                line_str = line.strip()
                if line_str.startswith("__BATCH_ODB_PAYLOAD__"):
                    return json.loads(line_str[len("__BATCH_ODB_PAYLOAD__"):])
                if line_str.startswith("__ODB_VERIFIED__"):
                    return json.loads(line_str[len("__ODB_VERIFIED__"):])

            last_line = raw_out.splitlines()[-1].strip()
            try:
                return json.loads(last_line)
            except Exception:
                # If last line is not pure JSON, attempt to evaluate or return payload string
                return raw_out

        except subprocess.TimeoutExpired as exc:
            raise ExtractionExecutionError(
                f"Headless Abaqus Python extraction timed out after {effective_timeout}s: {exc}"
            )
        finally:
            try:
                if script_file.exists():
                    script_file.unlink()
            except Exception:
                pass


def _extract_single_requirement_in_process(
    odb: Any,
    requirement: ResultRequirement,
) -> ResultExtraction:
    """Extract a single ResultRequirement directly from an in-process native ODB object."""
    steps = list(getattr(odb, "steps", {}).keys())
    if not steps:
        raise ExtractionFieldNotFoundError("ODB contains zero steps")

    if requirement.step:
        step_name = requirement.step
    else:
        non_initial_steps = [s for s in steps if str(s).strip().lower() != "initial"]
        if len(non_initial_steps) > 1:
            raise ExtractionFieldNotFoundError(
                f"Requirement '{requirement.name or requirement.value_key}' does not specify a step, "
                f"but ODB contains multiple non-Initial steps: {non_initial_steps}. Explicit step binding required."
            )
        elif len(non_initial_steps) == 1:
            step_name = non_initial_steps[0]
        else:
            raise ExtractionFieldNotFoundError("ODB contains zero non-Initial analysis steps")

    if step_name not in odb.steps:
        raise ExtractionFieldNotFoundError(
            f"Step '{step_name}' not found in ODB steps: {steps}"
        )
    st = odb.steps[step_name]

    if requirement.output_kind == "history":
        regions = getattr(st, "historyRegions", {})
        reg_name = requirement.history_region
        var_name = requirement.history_variable
        if reg_name:
            if reg_name not in regions:
                raise ExtractionFieldNotFoundError(
                    f"History region '{reg_name}' not found in step '{step_name}'"
                )
            hr = regions[reg_name]
        else:
            matches = [
                (n, v) for n, v in regions.items()
                if hasattr(v, "historyOutputs") and var_name in v.historyOutputs
            ]
            if len(matches) != 1:
                raise ExtractionFieldNotFoundError(
                    f"History output '{var_name}' ambiguous or not found in step '{step_name}': {[m[0] for m in matches]}"
                )
            reg_name, hr = matches[0]

        history_outputs = getattr(hr, "historyOutputs", {})
        if hr is None or var_name not in history_outputs:
            raise ExtractionFieldNotFoundError(
                f"History output '{var_name}' not found in region '{reg_name}'"
            )
        ho = history_outputs[var_name]
        raw_data = getattr(ho, "data", ())
        values = [float(x[1]) for x in raw_data if hasattr(x, "__getitem__") and len(x) > 1]
        if not values:
            raise OdbExtractionError(f"History output '{var_name}' has no numeric values")

        agg = requirement.aggregation
        if agg == "max":
            value = max(values)
        elif agg == "min":
            value = min(values)
        elif agg == "average":
            value = sum(values) / float(len(values))
        elif agg == "first":
            value = values[0]
        elif agg == "sum":
            value = sum(values)
        else:
            value = values[-1]

        locator = {
            "step": step_name,
            "history_region": reg_name,
            "history_region_expression": requirement.history_region_expression,
            "history_variable": var_name,
        }
        evidence = Evidence(
            kind="odb_history_result",
            source="odb",
            locator=str(locator),
            value=float(value),
            unit=requirement.unit,
            metadata={
                "value_key": requirement.value_key,
                "aggregation": requirement.aggregation,
            },
        )
        return ResultExtraction(requirement, float(value), locator, (evidence,))

    if requirement.output_kind == "frame_value":
        frames = getattr(st, "frames", [])
        n_frames = len(frames)
        fr_idx = requirement.frame
        if n_frames == 0 or fr_idx >= n_frames or fr_idx < -n_frames:
            raise ExtractionFieldNotFoundError(
                f"Frame {fr_idx} unavailable in step '{step_name}' ({n_frames} frames available)"
            )
        fr = frames[fr_idx]
        value = getattr(fr, "frameValue", None)
        if value is None or not isinstance(value, (int, float)):
            raise OdbExtractionError(f"frameValue unavailable for frame {fr_idx} in step '{step_name}'")
        locator = {"step": step_name, "frame": fr_idx}
        evidence = Evidence(
            kind="odb_frame_value",
            source="odb",
            locator=str(locator),
            value=float(value),
            metadata={"payload": {"step": step_name, "frame": fr_idx, "frame_value": float(value)}},
        )
        return ResultExtraction(requirement, float(value), locator, (evidence,))

    # output_kind == "field"
    frames = getattr(st, "frames", [])
    n_frames = len(frames)
    fr_idx = requirement.frame
    if n_frames == 0 or fr_idx >= n_frames or fr_idx < -n_frames:
        raise ExtractionFieldNotFoundError(
            f"Frame {fr_idx} unavailable in step '{step_name}' ({n_frames} frames available)"
        )
    fr = frames[fr_idx]
    field_outputs = getattr(fr, "fieldOutputs", {})
    fld = requirement.field
    if fld in field_outputs:
        fo = field_outputs[fld]
    elif fld and (fld + "11") in field_outputs:
        fo = field_outputs[fld + "11"]
    else:
        raise ExtractionFieldNotFoundError(
            f"Field '{fld}' not found in step '{step_name}' frame {fr_idx}. Available: {list(field_outputs.keys())}"
        )

    if requirement.position:
        if not hasattr(fo, "getSubset"):
            raise OdbExtractionError(
                f"FieldOutput for '{fld}' does not support position filtering (getSubset missing) "
                f"but position={requirement.position!r} was explicitly requested"
            )
        pos_const = requirement.position
        try:
            import sys as _sys
            abq_consts = _sys.modules.get("abaqusConstants")
            if abq_consts and isinstance(pos_const, str):
                pos_const = getattr(abq_consts, pos_const, pos_const)
        except Exception:
            pass
        fo = fo.getSubset(position=pos_const)

    if requirement.region:
        if not hasattr(fo, "getSubset"):
            raise OdbExtractionError(
                f"FieldOutput for '{fld}' does not support region filtering (getSubset missing) "
                f"but region={requirement.region!r} was explicitly requested"
            )
        reg_val = _resolve_safe_odb_region(odb, requirement.region)
        fo = fo.getSubset(region=reg_val)

    if requirement.invariant:
        if not hasattr(fo, "getScalarField"):
            raise OdbExtractionError(
                f"FieldOutput for '{fld}' does not support invariant extraction (getScalarField missing) "
                f"but invariant={requirement.invariant!r} was explicitly requested"
            )
        inv_const = requirement.invariant
        try:
            import sys as _sys
            abq_consts = _sys.modules.get("abaqusConstants")
            if abq_consts:
                inv_const = getattr(abq_consts, requirement.invariant, inv_const)
        except Exception:
            pass
        fo = fo.getScalarField(invariant=inv_const)
    elif requirement.component:
        if not hasattr(fo, "getScalarField"):
            raise OdbExtractionError(
                f"FieldOutput for '{fld}' does not support component extraction (getScalarField missing) "
                f"but component={requirement.component!r} was explicitly requested"
            )
        fo = fo.getScalarField(componentLabel=requirement.component)

    vals = getattr(fo, "values", [])
    if not vals:
        raise ExtractionFieldNotFoundError(
            f"No field values available for field '{fld}' in step '{step_name}'"
        )

    scalar_values: List[float] = []
    item_locators: List[Dict[str, Any]] = []

    for v in vals:
        val = None
        for attr in ("mises", "maxPrincipal", "magnitude", "value"):
            attr_val = getattr(v, attr, None)
            if isinstance(attr_val, (int, float)):
                val = float(attr_val)
                break
        if val is None:
            d = getattr(v, "data", None)
            if isinstance(d, (int, float)):
                val = float(d)
            elif hasattr(d, "__iter__"):
                d_list = list(d)
                if len(d_list) > 0 and isinstance(d_list[0], (int, float)):
                    val = float(d_list[0])

        if val is not None:
            scalar_values.append(val)
            inst = getattr(v, "instance", None)
            item_locators.append({
                "step": step_name,
                "frame": fr_idx,
                "instance": getattr(inst, "name", str(inst)) if inst else None,
                "node_label": getattr(v, "nodeLabel", None),
                "element_label": getattr(v, "elementLabel", None),
                "position": str(getattr(v, "position", None)),
            })

    if not scalar_values:
        raise ExtractionFieldNotFoundError(
            f"No numeric scalar values could be extracted for field '{fld}'"
        )

    agg = requirement.aggregation
    if agg == "max":
        index = max(range(len(scalar_values)), key=scalar_values.__getitem__)
        value = scalar_values[index]
        locator = item_locators[index]
    elif agg == "min":
        index = min(range(len(scalar_values)), key=scalar_values.__getitem__)
        value = scalar_values[index]
        locator = item_locators[index]
    elif agg == "average":
        value = sum(scalar_values) / float(len(scalar_values))
        locator = {"step": step_name, "frame": fr_idx}
    else:  # "last"
        index = len(scalar_values) - 1
        value = scalar_values[index]
        locator = item_locators[index]

    evidence = Evidence(
        kind="odb_result",
        source="odb",
        locator=str(locator),
        value=float(value),
        unit=requirement.unit,
        metadata={
            "value_key": requirement.value_key,
            "field": requirement.field,
            "component": requirement.component,
            "invariant": requirement.invariant,
            "aggregation": requirement.aggregation,
        },
    )
    return ResultExtraction(requirement, float(value), locator, (evidence,))


def _extract_odb_in_process(
    odb_path: Union[str, Path],
    requirements: Sequence[ResultRequirement],
    extract_metadata: bool = True,
    energy_spec: Optional[Dict[str, Any]] = None,
) -> Tuple[List[ResultExtraction], Dict[str, Any], Optional[Dict[str, Any]]]:
    """In-process native ODB result extraction using authentic odbAccess API."""
    odb = None
    try:
        from odbAccess import openOdb
        odb = openOdb(str(odb_path), readOnly=True)
        results = []
        for req in requirements:
            ext = _extract_single_requirement_in_process(odb, req)
            results.append(ext)
        meta = {}
        if extract_metadata:
            meta = {
                "status": "available",
                "steps": list(odb.steps.keys()),
                "instances": list(odb.rootAssembly.instances.keys()),
                "step_frames": {k: len(v.frames) for k, v in odb.steps.items()},
            }
        energy = None
        if energy_spec:
            non_initial_steps = [s for s in odb.steps.keys() if str(s).strip().lower() != "initial"]
            e_step = energy_spec.get("step")
            if not e_step:
                if len(non_initial_steps) == 1:
                    e_step = non_initial_steps[0]
                elif len(non_initial_steps) > 1:
                    energy = {
                        "status": "unavailable",
                        "reason": "energy_step_ambiguous",
                        "available_steps": non_initial_steps,
                    }
                    e_step = None
            e_reg = energy_spec.get("region") or "Assembly ASSEMBLY"
            e_vars = energy_spec.get("variables") or [
                "ALLIE", "ALLKE", "ALLWK", "ALLAE", "ALLPD", "ALLCD", "ALLFD", "ALLSD", "ALLSE", "ETOTAL"
            ]
            if e_step is not None:
                if e_step in odb.steps:
                    st = odb.steps[e_step]
                    hr = getattr(st, "historyRegions", {}).get(e_reg)
                    if hr:
                        v_dict = {}
                        for vn in e_vars:
                            out = getattr(hr, "historyOutputs", {}).get(vn)
                            v_dict[vn] = [list(pt) for pt in out.data] if (out and hasattr(out, "data")) else None
                        energy = {"status": "available", "step": e_step, "region": e_reg, "variables": v_dict}
                    else:
                        energy = {"status": "unavailable", "reason": "history_region_missing", "region": e_reg}
                else:
                    energy = {"status": "unavailable", "reason": "step_missing", "step": e_step}
        return results, meta, energy
    except OdbExtractionError:
        raise
    except Exception as exc:
        raise OdbExtractionError(f"In-process native ODB extraction failed for {odb_path}: {exc}") from exc
    finally:
        if odb is not None:
            try:
                odb.close()
            except Exception:
                pass


def build_batched_extraction_script(
    odb_path: Union[str, Path],
    requirements: Sequence[ResultRequirement],
    extract_metadata: bool = True,
    energy_spec: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a unified Python script that opens the ODB once and extracts metadata, field extrema, and energy history."""
    reqs_data = []
    for req in requirements:
        reqs_data.append({
            "value_key": req.value_key,
            "output_kind": req.output_kind,
            "step": req.step,
            "frame": req.frame,
            "field": req.field,
            "component": req.component,
            "invariant": req.invariant,
            "position": req.position,
            "region": req.region,
            "aggregation": req.aggregation,
            "history_region": req.history_region,
            "history_variable": req.history_variable,
            "unit": req.unit,
        })
    reqs_json = json.dumps(reqs_data)
    energy_json = json.dumps(energy_spec or {})
    odb_str = str(odb_path).replace("\\", "/")

    return f'''import sys
import json
import math

try:
    from odbAccess import openOdb
    from abaqusConstants import *
except Exception as e:
    print("__BATCH_ODB_PAYLOAD__" + json.dumps({{"status": "error", "error": "Import failed: " + str(e)}}))
    sys.exit(1)

path = {odb_str!r}
try:
    odb = openOdb(path=path, readOnly=True)
except Exception as e:
    print("__BATCH_ODB_PAYLOAD__" + json.dumps({{"status": "error", "error": "openOdb failed: " + str(e)}}))
    sys.exit(1)

payload = {{
    "status": "success",
    "metadata": None,
    "requirements": {{}},
    "energy": None,
    "errors": {{}},
}}

# 1. Structural Metadata
if {extract_metadata!r}:
    try:
        steps_list = list(odb.steps.keys())
        instances_list = list(odb.rootAssembly.instances.keys())
        step_frames = {{k: len(v.frames) for k, v in odb.steps.items()}}
        payload["metadata"] = {{
            "status": "available",
            "steps": steps_list,
            "instances": instances_list,
            "step_frames": step_frames,
        }}
    except Exception as exc:
        payload["errors"]["metadata"] = str(exc)

# 2. Field & History Requirements
reqs = json.loads({reqs_json!r})
for r in reqs:
    vkey = r["value_key"]
    try:
        steps = list(odb.steps.keys())
        if not steps:
            payload["requirements"][vkey] = {{"success": False, "error": "ODB contains zero steps"}}
            continue
        req_step = r.get("step")
        if req_step:
            step_name = req_step
        else:
            non_init = [s for s in steps if str(s).strip().lower() != "initial"]
            if len(non_init) > 1:
                payload["requirements"][vkey] = {{
                    "success": False,
                    "error": f"Requirement '{{r.get('name') or vkey}}' specifies no step, but ODB contains multiple non-Initial steps: {{non_init}}. Explicit step required."
                }}
                continue
            elif len(non_init) == 1:
                step_name = non_init[0]
            else:
                payload["requirements"][vkey] = {{
                    "success": False,
                    "error": "ODB contains zero non-Initial analysis steps"
                }}
                continue
        if step_name not in odb.steps:
            payload["requirements"][vkey] = {{"success": False, "error": f"Step '{{step_name}}' not found in ODB steps: {{steps}}"}}
            continue
        st = odb.steps[step_name]

        if r["output_kind"] == "history":
            regions = getattr(st, "historyRegions", {{}})
            reg_name = r["history_region"]
            var_name = r["history_variable"]
            if reg_name:
                if reg_name not in regions:
                    payload["requirements"][vkey] = {{"success": False, "error": f"History region '{{reg_name}}' not found in step '{{step_name}}'"}}
                    continue
                hr = regions[reg_name]
            else:
                matches = [(n, v) for n, v in regions.items() if hasattr(v, "historyOutputs") and var_name in v.historyOutputs]
                if len(matches) != 1:
                    payload["requirements"][vkey] = {{"success": False, "error": f"History output '{{var_name}}' ambiguous or missing: {{[m[0] for m in matches]}}"}}
                    continue
                reg_name, hr = matches[0]

            if hr is None or var_name not in getattr(hr, "historyOutputs", {{}}):
                payload["requirements"][vkey] = {{"success": False, "error": f"History output '{{var_name}}' not found in region '{{reg_name}}'"}}
                continue
            raw_data = getattr(hr.historyOutputs[var_name], "data", ())
            vals = [float(x[1]) for x in raw_data if hasattr(x, "__getitem__") and len(x) > 1]
            if not vals:
                payload["requirements"][vkey] = {{"success": False, "error": f"History output '{{var_name}}' has no numeric values"}}
                continue
            agg = r["aggregation"]
            if agg == "max":
                val = max(vals)
            elif agg == "min":
                val = min(vals)
            elif agg == "average":
                val = sum(vals) / float(len(vals))
            elif agg == "first":
                val = vals[0]
            elif agg == "sum":
                val = sum(vals)
            else:
                val = vals[-1]
            locator = {{
                "step": step_name,
                "history_region": reg_name,
                "history_variable": var_name,
            }}
            payload["requirements"][vkey] = {{"success": True, "value": float(val), "locator": locator}}

        elif r["output_kind"] == "frame_value":
            frames = getattr(st, "frames", [])
            fr_idx = r["frame"]
            if not frames or fr_idx >= len(frames) or fr_idx < -len(frames):
                payload["requirements"][vkey] = {{"success": False, "error": f"Frame {{fr_idx}} unavailable in step '{{step_name}}'"}}
                continue
            fval = getattr(frames[fr_idx], "frameValue", None)
            if fval is None:
                payload["requirements"][vkey] = {{"success": False, "error": f"frameValue unavailable for frame {{fr_idx}}"}}
                continue
            locator = {{"step": step_name, "frame": fr_idx}}
            payload["requirements"][vkey] = {{"success": True, "value": float(fval), "locator": locator}}

        else: # Field Output
            frames = getattr(st, "frames", [])
            fr_idx = r["frame"]
            if not frames or fr_idx >= len(frames) or fr_idx < -len(frames):
                payload["requirements"][vkey] = {{"success": False, "error": f"Frame {{fr_idx}} unavailable in step '{{step_name}}'"}}
                continue
            fr = frames[fr_idx]
            field_outputs = getattr(fr, "fieldOutputs", {{}})
            fld = r["field"]
            if fld in field_outputs:
                fo = field_outputs[fld]
            elif fld and (fld + "11") in field_outputs:
                fo = field_outputs[fld + "11"]
            else:
                payload["requirements"][vkey] = {{"success": False, "error": f"Field '{{fld}}' not found in step '{{step_name}}' frame {{fr_idx}}"}}
                continue

            if r["position"]:
                pos_const = getattr(sys.modules.get("abaqusConstants"), r["position"], r["position"])
                fo = fo.getSubset(position=pos_const)

            if r["invariant"]:
                inv_const = getattr(sys.modules.get("abaqusConstants"), r["invariant"], r["invariant"])
                fo = fo.getScalarField(invariant=inv_const)
            elif r["component"]:
                fo = fo.getScalarField(componentLabel=r["component"])

            scalar_values = []
            item_locators = []
            for v in fo.values:
                d = getattr(v, "data", None)
                val_c = None
                for key_sub in ("mises", "magnitude", "maxPrincipal"):
                    sub_v = getattr(v, key_sub, None)
                    if isinstance(sub_v, (int, float)):
                        val_c = float(sub_v)
                        break
                if val_c is None:
                    if isinstance(d, (int, float)):
                        val_c = float(d)
                    elif hasattr(d, "__iter__"):
                        dl = list(d)
                        if dl and isinstance(dl[0], (int, float)):
                            val_c = float(dl[0])
                if val_c is not None:
                    scalar_values.append(val_c)
                    inst = getattr(v, "instance", None)
                    item_locators.append({{
                        "step": step_name,
                        "frame": fr_idx,
                        "instance": getattr(inst, "name", str(inst)) if inst else None,
                        "node_label": getattr(v, "nodeLabel", None),
                        "element_label": getattr(v, "elementLabel", None),
                        "position": str(getattr(v, "position", None)),
                    }})

            if not scalar_values:
                payload["requirements"][vkey] = {{"success": False, "error": f"No numeric scalar values could be extracted for field '{{fld}}'"}}
                continue

            agg = r["aggregation"]
            if agg == "max":
                idx = max(range(len(scalar_values)), key=scalar_values.__getitem__)
                val = scalar_values[idx]
                loc = item_locators[idx]
            elif agg == "min":
                idx = min(range(len(scalar_values)), key=scalar_values.__getitem__)
                val = scalar_values[idx]
                loc = item_locators[idx]
            elif agg == "average":
                val = sum(scalar_values) / float(len(scalar_values))
                loc = {{"step": step_name, "frame": fr_idx}}
            else:
                idx = len(scalar_values) - 1
                val = scalar_values[idx]
                loc = item_locators[idx]

            payload["requirements"][vkey] = {{"success": True, "value": float(val), "locator": loc}}
    except Exception as exc:
        payload["requirements"][vkey] = {{"success": False, "error": str(exc)}}

# 3. Energy History Output
energy_spec_in = json.loads({energy_json!r})
if energy_spec_in:
    try:
        non_init_steps = [s for s in odb.steps.keys() if str(s).strip().lower() != "initial"]
        e_step = energy_spec_in.get("step")
        if not e_step:
            if len(non_init_steps) == 1:
                e_step = non_init_steps[0]
            elif len(non_init_steps) > 1:
                payload["energy"] = {{
                    "status": "unavailable",
                    "reason": "energy_step_ambiguous",
                    "available_steps": non_init_steps,
                }}
                e_step = None
            else:
                payload["energy"] = {{
                    "status": "unavailable",
                    "reason": "no_non_initial_steps",
                }}
                e_step = None
        e_region = energy_spec_in.get("region") or "Assembly ASSEMBLY"
        e_vars = energy_spec_in.get("variables") or [
            "ALLIE", "ALLKE", "ALLWK", "ALLAE", "ALLPD", "ALLCD", "ALLFD", "ALLSD", "ALLSE", "ETOTAL"
        ]
        if e_step is not None:
            if e_step in odb.steps:
                st = odb.steps[e_step]
                hr = getattr(st, "historyRegions", {{}}).get(e_region)
                if hr is not None:
                    vars_dict = {{}}
                    for vn in e_vars:
                        out = getattr(hr, "historyOutputs", {{}}).get(vn)
                        if out is not None and hasattr(out, "data"):
                            vars_dict[vn] = [list(pt) for pt in out.data]
                        else:
                            vars_dict[vn] = None
                    payload["energy"] = {{
                        "status": "available",
                        "step": e_step,
                        "region": e_region,
                        "variables": vars_dict,
                    }}
                else:
                    payload["energy"] = {{"status": "unavailable", "reason": "history_region_missing", "region": e_region}}
            else:
                payload["energy"] = {{"status": "unavailable", "reason": "step_missing", "step": e_step}}
    except Exception as exc:
        payload["errors"]["energy"] = str(exc)

try:
    odb.close()
except Exception:
    pass

print("__BATCH_ODB_PAYLOAD__" + json.dumps(payload))
'''


def _extract_via_executor(
    executor: HeadlessAbaqusPythonExecutor,
    odb_path: Path,
    normalized_reqs: Sequence[ResultRequirement],
    requirements_or_criteria: Sequence[Union[ResultRequirement, Dict[str, Any]]],
    extract_metadata: bool = True,
    energy_spec: Optional[Dict[str, Any]] = None,
) -> Tuple[List[ResultExtraction], Dict[str, Any], Optional[Dict[str, Any]]]:
    """Execute batched single-invocation ODB extraction, with fallback to discrete extraction."""
    # 1. Try unified batched extraction first
    try:
        script = build_batched_extraction_script(
            odb_path,
            normalized_reqs,
            extract_metadata=extract_metadata,
            energy_spec=energy_spec,
        )
        raw_res = executor.execute(script)
        if isinstance(raw_res, dict) and raw_res.get("status") == "success" and "requirements" in raw_res:
            req_results = raw_res.get("requirements", {})
            source_items: List[ResultExtraction] = []
            for req in normalized_reqs:
                entry = req_results.get(req.value_key)
                if not entry:
                    raise ExtractionFieldNotFoundError(f"Requirement '{req.value_key}' missing from batch result payload")
                if not entry.get("success", False):
                    err_msg = entry.get("error", "Unknown batch extraction error")
                    if any(k in err_msg.lower() for k in ("not found", "missing", "unavailable", "zero steps", "explicit step required", "specifies no step")):
                        raise ExtractionFieldNotFoundError(err_msg)
                    raise OdbExtractionError(err_msg)
                val = float(entry["value"])
                loc = dict(entry.get("locator") or {})
                ev = Evidence(
                    kind="odb_result" if req.output_kind != "history" else "odb_history_result",
                    source="odb",
                    locator=str(loc),
                    value=val,
                    unit=req.unit,
                    metadata={"value_key": req.value_key},
                )
                source_items.append(ResultExtraction(req, val, loc, (ev,)))
            return source_items, raw_res.get("metadata") or {}, raw_res.get("energy")
    except (OdbExtractionError, ExtractionFieldNotFoundError):
        raise
    except Exception:
        pass

    # 2. Fallback to discrete extraction for hermetic mocks or custom runners
    from .results import extract_requirements, extract_requirement
    source_items = []
    try:
        candidate_extractions, _ = extract_requirements(executor, str(odb_path), requirements_or_criteria)
        if candidate_extractions:
            source_items = list(candidate_extractions)
    except Exception:
        source_items = []

    if not source_items:
        for req in normalized_reqs:
            try:
                extraction = extract_requirement(executor, str(odb_path), req)
                source_items.append(extraction)
            except Exception as exc:
                raise OdbExtractionError(
                    f"Fail-closed: Failed to extract authentic result for {req.value_key} from {odb_path}: {exc}"
                ) from exc
    return source_items, {}, None


def compute_file_sha256(path: Union[str, Path]) -> str:
    """Compute deterministic SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def extract_odb_results(
    odb_path: Union[str, Path],
    requirements_or_criteria: Sequence[Union[ResultRequirement, Dict[str, Any]]],
    *,
    run_id: str,
    input_hash: str,
    workdir: Optional[Union[str, Path]] = None,
    launcher_cmd: Optional[str] = None,
    custom_runner: Optional[Callable[[str], Any]] = None,
    timeout_seconds: int = 120,
    include_metadata: bool = True,
    energy_spec: Optional[Dict[str, Any]] = None,
) -> OdbExtractionReport:
    """Authentically extract finite element results from an ODB with full causal binding.

    Parameters:
    - odb_path: Path to target .odb database.
    - requirements_or_criteria: List of ResultRequirement objects or criteria dictionaries.
    - run_id: Authoritative execution run identifier for causal binding.
    - input_hash: Authoritative SHA-256 digest of the INP model input file.
    - workdir: Scratch directory for temporary extraction scripts.
    - launcher_cmd: Optional path to custom Abaqus launcher command.
    - custom_runner: Optional hook for in-memory / testing executor.
    - timeout_seconds: Maximum time allowed per extraction operation.
    - include_metadata: Whether to simultaneously extract structural ODB metadata (steps, instances).
    - energy_spec: Optional dictionary specifying step, region, and variables for simultaneous energy history extraction.

    Returns:
    - OdbExtractionReport with validated metrics, extractions, evidence, metadata, and energy.

    Raises:
    - OdbFileNotFoundError: If the ODB file does not exist.
    - OdbCorruptOrInvalidError: If the ODB is empty or not authentic binary format.
    - OdbExtractionError: If any requirement extraction fails (Fail-Closed).
    """
    odb = Path(odb_path).resolve()
    if not odb.is_file():
        raise OdbFileNotFoundError(f"Target ODB file does not exist: {odb}")

    if not is_authentic_binary_odb(odb):
        raise OdbCorruptOrInvalidError(
            f"Target file {odb} is not an authentic binary ODB. "
            "Empty files, plaintext JSON, and synthetic mocks are strictly prohibited."
        )

    odb_sha256 = compute_file_sha256(odb)

    # Normalize inputs to typed ResultRequirement objects
    normalized_reqs: List[ResultRequirement] = []
    criteria_to_convert: List[Dict[str, Any]] = []

    for item in requirements_or_criteria:
        if isinstance(item, ResultRequirement):
            normalized_reqs.append(item)
        elif isinstance(item, dict):
            criteria_to_convert.append(item)
        else:
            raise TypeError(f"Unsupported requirement specification type: {type(item)}")

    if criteria_to_convert:
        converted = requirements_from_criteria(criteria_to_convert)
        normalized_reqs.extend(converted)

    if not normalized_reqs:
        return OdbExtractionReport(
            run_id=run_id,
            input_hash=input_hash,
            odb_path=odb,
            odb_sha256=odb_sha256,
            extractions=(),
            metrics={},
            evidence=(),
        )

    if workdir:
        eff_workdir = Path(workdir).resolve()
    else:
        from ..paths import require_customer_project_context
        eff_workdir = require_customer_project_context(source_path=odb).create_run_solver_dir(
            f"extract_{uuid.uuid4().hex[:8]}"
        )
    from ..paths import assert_path_outside_core_workspace
    assert_path_outside_core_workspace(eff_workdir)

    extracted_metadata: Dict[str, Any] = {}
    extracted_energy: Optional[Dict[str, Any]] = None

    if custom_runner is not None:
        executor = HeadlessAbaqusPythonExecutor(
            launcher_cmd=launcher_cmd,
            workdir=eff_workdir,
            timeout=timeout_seconds,
            custom_runner=custom_runner,
        )
        source_items, extracted_metadata, extracted_energy = _extract_via_executor(
            executor, odb, normalized_reqs, requirements_or_criteria,
            extract_metadata=include_metadata, energy_spec=energy_spec,
        )
    elif launcher_cmd:
        resolved_launcher = find_abaqus_executable(launcher_cmd)
        if not resolved_launcher:
            raise AbaqusLauncherNotFoundError(
                f"Abaqus executable not found (launcher_cmd={launcher_cmd!r}). "
                "Authentic ODB extraction requires an authentic Abaqus installation."
            )
        executor = HeadlessAbaqusPythonExecutor(
            launcher_cmd=resolved_launcher,
            workdir=eff_workdir,
            timeout=timeout_seconds,
        )
        source_items, extracted_metadata, extracted_energy = _extract_via_executor(
            executor, odb, normalized_reqs, requirements_or_criteria,
            extract_metadata=include_metadata, energy_spec=energy_spec,
        )
    elif has_native_odb_access():
        source_items, extracted_metadata, extracted_energy = _extract_odb_in_process(
            odb, normalized_reqs,
            extract_metadata=include_metadata, energy_spec=energy_spec,
        )
    else:
        resolved_launcher = find_abaqus_executable()
        if resolved_launcher:
            executor = HeadlessAbaqusPythonExecutor(
                launcher_cmd=resolved_launcher,
                workdir=eff_workdir,
                timeout=timeout_seconds,
            )
            source_items, extracted_metadata, extracted_energy = _extract_via_executor(
                executor, odb, normalized_reqs, requirements_or_criteria,
                extract_metadata=include_metadata, energy_spec=energy_spec,
            )
        else:
            raise AbaqusLauncherNotFoundError(
                f"Abaqus executable not found (launcher_cmd={launcher_cmd!r}) and native odbAccess is unavailable. "
                "Authentic ODB extraction requires an authentic Abaqus installation or native Abaqus Python environment."
            )

    extractions: List[ResultExtraction] = []
    metrics: Dict[str, float] = {}
    evidence_list: List[Evidence] = []

    for extraction in source_items:
        req = extraction.requirement
        val = extraction.value
        if not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
            raise OdbExtractionError(
                f"Extracted non-numeric or infinite value ({val}) for {req.value_key}."
            )

        # Causal lineage binding: enrich extraction locator with execution and ODB provenance
        bound_locator = dict(extraction.locator or {})
        bound_locator["run_id"] = run_id
        bound_locator["input_hash"] = input_hash
        bound_locator["odb_path"] = str(odb)
        bound_locator["odb_sha256"] = odb_sha256
        bound_locator["extraction_timestamp"] = time.time()

        # Enrich evidence records with provenance
        bound_evidences: List[Evidence] = []
        for ev in extraction.evidence:
            ev_meta = dict(getattr(ev, "metadata", {}) or {})
            ev_meta["run_id"] = run_id
            ev_meta["input_hash"] = input_hash
            ev_meta["odb_sha256"] = odb_sha256
            ev_meta["unit"] = req.unit
            ev_meta["value_key"] = req.value_key

            bound_ev = Evidence(
                kind=getattr(ev, "kind", "odb_result"),
                source="odb",
                locator=str(bound_locator),
                value=float(val),
                unit=req.unit,
                metadata=ev_meta,
            )
            bound_evidences.append(bound_ev)
            evidence_list.append(bound_ev)

        bound_extraction = ResultExtraction(
            requirement=req,
            value=float(val),
            locator=bound_locator,
            evidence=tuple(bound_evidences),
        )
        extractions.append(bound_extraction)
        metrics[req.value_key] = float(val)

    return OdbExtractionReport(
        run_id=run_id,
        input_hash=input_hash,
        odb_path=odb,
        odb_sha256=odb_sha256,
        extractions=tuple(extractions),
        metrics=metrics,
        evidence=tuple(evidence_list),
        metadata=extracted_metadata,
        energy_evidence=extracted_energy,
    )
