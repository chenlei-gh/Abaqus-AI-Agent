"""Universal Abaqus batch job solver execution engine and lifecycle controller.

Zero Tolerance for Fake Logs:
- When live Abaqus executable is present, launches native batch execution (`abaqus job=... interactive`).
- When offline or dry-running, NEVER synthesizes fake .sta, .msg, .dat, .log, or .odb files.
- Fail-closed if require_live is True and Abaqus cannot be executed.
- Parses authentic solver output diagnostics and validates genuine binary ODB existence.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union


@dataclass(frozen=True)
class AbaqusBatchJob:
    """Specification of a batch Abaqus solver execution job."""
    job_name: str
    inp_path: Path
    workdir: Path
    global_odb: Optional[Path] = None
    cpus: int = 1
    gpus: int = 0
    double_precision: bool = False
    interactive: bool = True
    timeout_seconds: int = 1800
    stall_timeout_seconds: int = 120
    submodel: bool = False


@dataclass(frozen=True)
class AbaqusJobResult:
    """Outcome of an authentic Abaqus batch job execution."""
    job_name: str
    state: str  # "COMPLETED", "ABORTED", "ERROR", "TIMEOUT", "DRY_RUN"
    returncode: int
    workdir: Path
    is_live: bool
    odb_path: Optional[Path] = None
    sta_path: Optional[Path] = None
    msg_path: Optional[Path] = None
    dat_path: Optional[Path] = None
    log_path: Optional[Path] = None
    diagnostics: List[str] = field(default_factory=list)
    artifacts: Dict[str, Path] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.state == "COMPLETED" and self.is_live and self.odb_path is not None and self.odb_path.is_file()


def _read_solver_log(log_file: Path, label: str, diags: List[str]) -> Optional[str]:
    """Decode a solver log strictly, recording any substitution before falling back.

    The ABORTED decision keys on plain-ASCII markers, so a replacement decode still
    finds them. Recording the degradation keeps a corrupted log from being reported
    as if it had been decoded cleanly.
    """
    try:
        return log_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        diags.append(f"{label}_DECODE_ERR: log is not valid UTF-8; markers parsed with replacement substitution")
        return log_file.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        diags.append(f"{label}_READ_ERR: {e}")
        return None


def parse_solver_diagnostics(workdir: Path, job_name: str) -> List[str]:
    """Parse authentic .msg, .sta, and .dat logs for solver error messages and convergence issues."""
    diags: List[str] = []

    msg_file = workdir / f"{job_name}.msg"
    if msg_file.is_file():
        content = _read_solver_log(msg_file, "MSG", diags)
        if content is not None:
            for line in content.splitlines():
                line_upper = line.upper()
                if "***ERROR" in line_upper or "***FATAL" in line_upper:
                    diags.append(f"MSG_ERROR: {line.strip()}")
                elif "THE ANALYSIS HAS NOT BEEN COMPLETED" in line_upper:
                    diags.append("MSG: Analysis not completed")

    sta_file = workdir / f"{job_name}.sta"
    if sta_file.is_file():
        content = _read_solver_log(sta_file, "STA", diags)
        if content is not None:
            for line in content.splitlines():
                if "THE ANALYSIS HAS NOT BEEN COMPLETED" in line.upper():
                    diags.append("STA: Analysis not completed")
                elif "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in line.upper():
                    diags.append("STA: Analysis completed successfully")

    return diags


def is_authentic_binary_odb(path: Union[str, Path]) -> bool:
    """Validate that an ODB file is not empty and is not a plaintext JSON or text mock."""
    path = Path(path)
    if not path.is_file():
        return False
    size = path.stat().st_size
    if size < 1024:
        return False
    try:
        header = path.read_bytes()[:32].strip()
        # Plaintext JSON / XML / YAML mocks start with {, [, <, or comment
        if header.startswith((b"{", b"[", b"<", b"#", b"--")):
            return False
        return True
    except Exception:
        return False


def has_native_odb_access() -> bool:
    """Return True if running in a native Abaqus Python environment with odbAccess available."""
    try:
        import odbAccess  # noqa: F401
        return True
    except ImportError:
        return False


def _verify_odb_in_process(
    path: Path,
    required_fields: Optional[Sequence[str]] = None,
    required_step: Optional[str] = None,
) -> Dict[str, Any]:
    """In-process native ODB structural verification using odbAccess."""
    odb = None
    try:
        from odbAccess import openOdb
        odb = openOdb(str(path), readOnly=True)
        steps = list(odb.steps.keys())
        if not steps:
            return {"verified": False, "error": "ODB contains zero steps"}

        non_initial_steps = [s for s in steps if str(s).strip().lower() != "initial"]
        if not non_initial_steps:
            return {
                "verified": False,
                "error": "ODB contains zero non-Initial analysis steps; simulation has no active analysis step",
            }

        step_info = {}
        for s in steps:
            step_obj = odb.steps[s]
            n_frames = len(step_obj.frames)
            fields = list(step_obj.frames[-1].fieldOutputs.keys()) if n_frames > 0 else []
            step_info[s] = {"frames": n_frames, "fields": fields}

        for s in non_initial_steps:
            if step_info[s]["frames"] <= 0:
                return {
                    "verified": False,
                    "error": f"ODB step '{s}' contains zero frames; incomplete solution cannot be accepted as verified",
                }

        req_step = str(required_step) if required_step else ""
        if req_step:
            if req_step not in step_info:
                return {
                    "verified": False,
                    "error": f"Required step '{req_step}' not found in ODB steps: {steps}",
                }
            if step_info[req_step]["frames"] <= 0:
                return {
                    "verified": False,
                    "error": f"Required step '{req_step}' has zero frames",
                }

        req_fields = [str(f).upper() for f in (required_fields or ())]
        if req_fields:
            if req_step:
                target_s = req_step
            elif len(non_initial_steps) == 1:
                target_s = non_initial_steps[0]
            elif len(non_initial_steps) > 1:
                return {
                    "verified": False,
                    "error": f"Multiple non-Initial analysis steps present ({non_initial_steps}); required_step must be explicitly specified to verify required fields",
                }
            else:
                return {
                    "verified": False,
                    "error": "ODB contains zero non-Initial analysis steps to verify required fields",
                }
            avail_flds = [f.upper() for f in step_info[target_s]["fields"]]
            missing = [f for f in req_fields if f not in avail_flds]
            if missing:
                return {
                    "verified": False,
                    "error": f"Required fields missing from step '{target_s}': {missing}",
                }

        root_assy = getattr(odb, "rootAssembly", None)
        if root_assy is None or not hasattr(root_assy, "instances"):
            return {
                "verified": False,
                "error": "ODB rootAssembly or instances collection cannot be accessed",
            }
        if len(root_assy.instances) == 0:
            return {
                "verified": False,
                "error": "ODB rootAssembly contains zero instances; cannot extract authentic mesh metrics",
            }

        total_elements = 0
        total_nodes = 0
        elem_types = {}
        instance_details = {}
        for inst_name, inst in root_assy.instances.items():
            if not hasattr(inst, "elements") or not hasattr(inst, "nodes"):
                return {
                    "verified": False,
                    "error": f"ODB instance '{inst_name}' lacks required mesh attributes ('elements' or 'nodes'); cannot verify discretization",
                }
            n_elem = len(inst.elements)
            n_node = len(inst.nodes)
            if (n_elem > 0 and n_node == 0) or (n_node > 0 and n_elem == 0):
                return {
                    "verified": False,
                    "error": f"ODB instance '{inst_name}' has incomplete discretization (elements={n_elem}, nodes={n_node})",
                }
            total_elements += n_elem
            total_nodes += n_node
            inst_types = {}
            for elem in inst.elements:
                if not hasattr(elem, "type"):
                    return {
                        "verified": False,
                        "error": f"ODB instance '{inst_name}' element is missing 'type' attribute",
                    }
                et = str(elem.type)
                elem_types[et] = elem_types.get(et, 0) + 1
                inst_types[et] = inst_types.get(et, 0) + 1
            instance_details[str(inst_name)] = {
                "elements": n_elem,
                "nodes": n_node,
                "element_types": inst_types,
                "status": "MESHED" if n_elem > 0 else "EMPTY",
            }
        if total_elements <= 0 or total_nodes <= 0:
            return {
                "verified": False,
                "error": f"ODB rootAssembly contains no finite element mesh (total_elements={total_elements}, total_nodes={total_nodes})",
            }
        mesh_metrics = {
            "total_elements": total_elements,
            "total_nodes": total_nodes,
            "element_types": elem_types,
            "instances": instance_details,
        }

        steps_to_check = list(dict.fromkeys(non_initial_steps if non_initial_steps else steps))
        if req_step and req_step not in steps_to_check:
            steps_to_check.append(req_step)
        all_nonfinite_fields = []
        for s in steps_to_check:
            degenerate_error, nonfinite_fields = _degenerate_solution_error(odb, s)
            for f in nonfinite_fields:
                if f not in all_nonfinite_fields:
                    all_nonfinite_fields.append(f)
            if degenerate_error:
                return {"verified": False, "error": degenerate_error}

        return {
            "verified": True,
            "steps": step_info,
            "mesh_metrics": mesh_metrics,
            "nonfinite_fields": all_nonfinite_fields,
        }
    except Exception as exc:
        return {"verified": False, "error": str(exc)}
    finally:
        if odb is not None:
            try:
                odb.close()
            except Exception:
                pass


def _finite_counts(values) -> tuple:
    """Return ``(numeric_count, finite_count)`` for one field-output array.

    Abaqus returns numpy scalars, which are not always ``float`` subclasses, so
    each component is converted rather than type-checked.
    """
    total = 0
    finite = 0
    for value in values:
        data = value.data
        if not hasattr(data, "__iter__"):
            data = (data,)
        for component in data:
            if isinstance(component, bool):
                continue
            try:
                number = float(component)
            except (TypeError, ValueError):
                continue
            total += 1
            if math.isfinite(number):
                finite += 1
    return total, finite


# Fields whose loss of finiteness means there is no solution at all.
# Contact-only fields are excluded: they can remain finite (mostly zero) while
# the displacement field is already NaN.
_CORE_RESULT_FIELDS = ("U", "UT", "UR", "S", "RF", "RM")

# A core field is treated as degenerate when fewer than this fraction of its
# values are finite. A healthy solution is fully finite; the observed failure
# produced 1 finite value out of 2250 for U and none for S.
_MIN_FINITE_FRACTION = 0.5


def _degenerate_solution_error(odb, step_name):
    """Return an error string when a completed step holds a degenerate solution.

    Abaqus/Standard can report COMPLETED SUCCESSFULLY for a run whose solution
    has diverged numerically, writing NaN into the field outputs. Such an ODB
    passes every structural check yet carries no usable result, so it must not
    reach acceptance as VALID.

    Every frame of the step is checked. Two conditions are rejected on any frame:
      * a core mechanical field (U/UR/S/RF/RM) is mostly non-finite;
      * every field carrying numeric values is entirely non-finite.
    A field with no values at all is not evidence either way and is ignored.

    Returns ``(error_or_None, nonfinite_field_names)``.
    """
    try:
        step_obj = odb.steps[step_name]
        n_frames = len(step_obj.frames)
        if n_frames == 0:
            return None, []
        all_nonfinite_fields = []
        for fr_idx, frame in enumerate(step_obj.frames):
            core_degenerate = []
            frame_nonfinite_fields = []
            data_bearing = 0
            for fname in frame.fieldOutputs.keys():
                total, finite = _finite_counts(frame.fieldOutputs[fname].values)
                if not total:
                    continue
                data_bearing += 1
                if not finite:
                    frame_nonfinite_fields.append(str(fname))
                    if str(fname) not in all_nonfinite_fields:
                        all_nonfinite_fields.append(str(fname))
                base = str(fname).split()[0].upper()
                if base in _CORE_RESULT_FIELDS and (finite / float(total)) < _MIN_FINITE_FRACTION:
                    core_degenerate.append("%s (%d/%d finite)" % (str(fname), finite, total))

            frame_desc = "last frame" if fr_idx == n_frames - 1 else f"frame {fr_idx}"
            if core_degenerate:
                return (
                    f"ODB step {step_name!r} {frame_desc} has a mostly non-finite core result field: {', '.join(sorted(core_degenerate))}; "
                    "the solver reported completion but the solution is numerically degenerate"
                ), all_nonfinite_fields
            if data_bearing and len(frame_nonfinite_fields) == data_bearing:
                return (
                    f"ODB step {step_name!r} {frame_desc} contains no finite field values; the solver "
                    f"reported completion but the solution is numerically degenerate (fields: {', '.join(sorted(frame_nonfinite_fields))})"
                ), all_nonfinite_fields
        return None, all_nonfinite_fields
    except Exception as exc:
        return "degenerate-result check failed: %s" % exc, []


def _build_odb_probe_script(
    path: Union[str, Path],
    required_fields: Optional[Sequence[str]] = None,
    required_step: Optional[str] = None,
) -> str:
    """Generate the headless Abaqus Python verification script for external launcher execution."""
    req_fields_json = json.dumps([str(f).upper() for f in (required_fields or ())])
    req_step_str = str(required_step) if required_step else ""

    return f"""
import sys, json
try:
    from odbAccess import openOdb
    odb = openOdb({str(path)!r}, readOnly=True)
    steps = list(odb.steps.keys())
    if not steps:
        print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': 'ODB contains zero steps'}}))
        odb.close()
        sys.exit(1)

    non_initial_steps = [s for s in steps if str(s).strip().lower() != "initial"]
    if not non_initial_steps:
        print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': "ODB contains zero non-Initial analysis steps; simulation has no active analysis step"}}))
        odb.close()
        sys.exit(1)

    step_info = {{}}
    for s in steps:
        step_obj = odb.steps[s]
        n_frames = len(step_obj.frames)
        fields = list(step_obj.frames[-1].fieldOutputs.keys()) if n_frames > 0 else []
        step_info[s] = {{'frames': n_frames, 'fields': fields}}

    for s in non_initial_steps:
        if step_info[s]['frames'] <= 0:
            print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': f"ODB step '{{s}}' contains zero frames; incomplete solution cannot be accepted as verified"}}))
            odb.close()
            sys.exit(1)

    req_step = {req_step_str!r}
    if req_step:
        if req_step not in step_info:
            print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': f"Required step '{{req_step}}' not found in ODB steps: {{steps}}"}}))
            odb.close()
            sys.exit(1)
        if step_info[req_step]['frames'] <= 0:
            print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': f"Required step '{{req_step}}' has zero frames"}}))
            odb.close()
            sys.exit(1)

    req_fields = {req_fields_json}
    if req_fields:
        if req_step:
            target_s = req_step
        elif len(non_initial_steps) == 1:
            target_s = non_initial_steps[0]
        elif len(non_initial_steps) > 1:
            print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': f"Multiple non-Initial analysis steps present ({{non_initial_steps}}); required_step must be explicitly specified to verify required fields"}}))
            odb.close()
            sys.exit(1)
        else:
            print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': "ODB contains zero non-Initial analysis steps to verify required fields"}}))
            odb.close()
            sys.exit(1)
        avail_flds = [f.upper() for f in step_info[target_s]['fields']]
        missing = [f for f in req_fields if f not in avail_flds]
        if missing:
            print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': f"Required fields missing from step '{{target_s}}': {{missing}}"}}))
            odb.close()
            sys.exit(1)

    root_assy = getattr(odb, 'rootAssembly', None)
    if root_assy is None or not hasattr(root_assy, 'instances'):
        print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': 'ODB rootAssembly or instances collection cannot be accessed'}}))
        odb.close()
        sys.exit(1)
    if len(root_assy.instances) == 0:
        print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': 'ODB rootAssembly contains zero instances; cannot extract authentic mesh metrics'}}))
        odb.close()
        sys.exit(1)

    total_elements = 0
    total_nodes = 0
    elem_types = {{}}
    instance_details = {{}}
    for inst_name, inst in root_assy.instances.items():
        if not hasattr(inst, 'elements') or not hasattr(inst, 'nodes'):
            print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': f"ODB instance '{{inst_name}}' lacks required mesh attributes ('elements' or 'nodes')"}}))
            odb.close()
            sys.exit(1)
        n_elem = len(inst.elements)
        n_node = len(inst.nodes)
        if (n_elem > 0 and n_node == 0) or (n_node > 0 and n_elem == 0):
            print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': f"ODB instance '{{inst_name}}' has incomplete discretization (elements={{n_elem}}, nodes={{n_node}})"}}))
            odb.close()
            sys.exit(1)
        total_elements += n_elem
        total_nodes += n_node
        inst_types = {{}}
        for elem in inst.elements:
            if not hasattr(elem, 'type'):
                print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': f"ODB instance '{{inst_name}}' element missing 'type'"}}))
                odb.close()
                sys.exit(1)
            et = str(elem.type)
            elem_types[et] = elem_types.get(et, 0) + 1
            inst_types[et] = inst_types.get(et, 0) + 1
        instance_details[str(inst_name)] = {{
            'elements': n_elem,
            'nodes': n_node,
            'element_types': inst_types,
            'status': 'MESHED' if n_elem > 0 else 'EMPTY',
        }}
    if total_elements <= 0 or total_nodes <= 0:
        print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': f"ODB rootAssembly contains no finite element mesh (total_elements={{total_elements}}, total_nodes={{total_nodes}})"}}))
        odb.close()
        sys.exit(1)
    mesh_metrics = {{
        'total_elements': total_elements,
        'total_nodes': total_nodes,
        'element_types': elem_types,
        'instances': instance_details,
    }}

    # Degenerate-result guard. Abaqus reports COMPLETED SUCCESSFULLY for some
    # contact runs whose solution has diverged numerically, writing NaN into the
    # field outputs. A structurally valid ODB full of NaN is not a result, so it
    # must not reach acceptance as VALID. Every frame of each analysis step is scanned.
    import math as _math
    _steps_to_check = list(dict.fromkeys(non_initial_steps if non_initial_steps else steps))
    if req_step and req_step not in _steps_to_check:
        _steps_to_check.append(req_step)
    _core = ('U', 'UT', 'UR', 'S', 'RF', 'RM')
    _all_nonfinite = []
    for _target_step in _steps_to_check:
        _step_obj = odb.steps[_target_step]
        _n_frames = len(_step_obj.frames)
        for _fr_idx, _frame in enumerate(_step_obj.frames):
            _core_degenerate = []
            _nonfinite = []
            _data_bearing = 0
            for _fname in _frame.fieldOutputs.keys():
                _tot = 0
                _fin = 0
                for _v in _frame.fieldOutputs[_fname].values:
                    _data = _v.data
                    if not hasattr(_data, '__iter__'):
                        _data = (_data,)
                    for _x in _data:
                        if isinstance(_x, bool):
                            continue
                        try:
                            _n = float(_x)
                        except (TypeError, ValueError):
                            continue
                        _tot += 1
                        if _math.isfinite(_n):
                            _fin += 1
                if not _tot:
                    continue
                _data_bearing += 1
                if not _fin:
                    _nonfinite.append(str(_fname))
                if str(_fname).split()[0].upper() in _core and (_fin / float(_tot)) < 0.5:
                    _core_degenerate.append(f"{{_fname}} ({{_fin}}/{{_tot}} finite)")
            for _f in _nonfinite:
                if _f not in _all_nonfinite:
                    _all_nonfinite.append(_f)
            _frame_desc = "last frame" if _fr_idx == _n_frames - 1 else f"frame {{_fr_idx}}"
            if _core_degenerate:
                print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': f"ODB step '{{_target_step}}' {{_frame_desc}} has a mostly non-finite core result field: {{sorted(_core_degenerate)}}; the solver reported completion but the solution is numerically degenerate"}}))
                odb.close()
                sys.exit(1)
            if _data_bearing and len(_nonfinite) == _data_bearing:
                print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': f"ODB step '{{_target_step}}' {{_frame_desc}} contains no finite field values; the solver reported completion but the solution is numerically degenerate (fields: {{sorted(_nonfinite)}})"}}))
                odb.close()
                sys.exit(1)

    odb.close()
    print("__ODB_VERIFIED__" + json.dumps({{'valid': True, 'steps': step_info, 'mesh_metrics': mesh_metrics, 'nonfinite_fields': _all_nonfinite}}))
except Exception as exc:
    print("__ODB_VERIFIED__" + json.dumps({{'valid': False, 'error': str(exc)}}))
    sys.exit(1)
"""


def verify_authentic_odb_structure(
    path: Union[str, Path],
    launcher_cmd: Optional[str] = None,
    required_fields: Optional[Sequence[str]] = None,
    required_step: Optional[str] = None,
    timeout: int = 60,
) -> Dict[str, Any]:
    """Perform native odbAccess structural verification using headless Abaqus Python (P0-5 / P0-A).

    Verifies that:
    1. File is valid non-empty binary ODB.
    2. File can be opened via native odbAccess.openOdb (in-process if available, else via subprocess).
    3. File contains at least one valid Step, and each Step contains at least one Frame.
    4. Required step (if specified) is present and contains frames.
    5. Required fields (if specified) are present in the last frame of the target/last step.
    """
    path = Path(path).resolve()
    if not is_authentic_binary_odb(path):
        return {
            "verified": False,
            "error": f"File {path} failed binary pre-filter (corrupt, empty, or plaintext mock)",
        }

    # 1. Native in-process path if running directly inside Abaqus Python / CAE environment
    if has_native_odb_access():
        return _verify_odb_in_process(
            path,
            required_fields=required_fields,
            required_step=required_step,
        )

    # 2. External launcher path if running in host Python environment
    launcher = find_abaqus_executable(launcher_cmd)
    if not launcher:
        # Host is offline or in mock test environment
        return {
            "verified": False,
            "offline": True,
            "error": "Abaqus executable not found on host to perform native openOdb verification",
        }

    probe_script = _build_odb_probe_script(
        path,
        required_fields=required_fields,
        required_step=required_step,
    )
    try:
        with tempfile.TemporaryDirectory(prefix="abaqus_odb_probe_") as probe_scratch:
            probe_file = Path(probe_scratch) / "_odb_probe.py"
            probe_file.write_text(probe_script, encoding="utf-8")
            proc = subprocess.run(
                [launcher, "python", str(probe_file)],
                cwd=probe_scratch,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=(os.name == "nt"),
            )
            for line in proc.stdout.splitlines():
                if line.startswith("__ODB_VERIFIED__"):
                    data = json.loads(line[len("__ODB_VERIFIED__"):])
                    return {
                        "verified": bool(data.get("valid", False)),
                        "steps": data.get("steps", {}),
                        "mesh_metrics": data.get("mesh_metrics", {}),
                        "error": data.get("error"),
                    }
            return {
                "verified": False,
                "error": f"Native probe output missing verification marker. stderr: {proc.stderr.strip()}",
            }
    except Exception as exc:
        return {"verified": False, "error": str(exc)}


def find_abaqus_executable(launcher_cmd: Optional[str] = None) -> Optional[str]:
    """Find authentic Abaqus executable or return None if offline."""
    if launcher_cmd:
        if shutil.which(launcher_cmd) or os.path.isfile(launcher_cmd):
            return launcher_cmd
        return None
    cmd = shutil.which("abaqus")
    if cmd:
        return cmd
    if os.name == "nt":
        default_nt_path = Path("C:/SIMULIA/Commands/abaqus.BAT")
        if default_nt_path.is_file():
            return str(default_nt_path)
    return None


def execute_abaqus_batch_job(
    job: AbaqusBatchJob,
    *,
    require_live: bool = False,
    launcher_cmd: Optional[str] = None,
) -> AbaqusJobResult:
    """Execute an authentic Abaqus job or report strict dry-run without synthesizing fake logs.

    Contract:
    1. If live Abaqus executable is available, builds CLI and invokes subprocess.
    2. Validates returncode == 0, examines solver diagnostics, and ensures genuine binary ODB was produced.
    3. If Abaqus is unavailable:
       - If require_live is True, raises RuntimeError (Fail-Closed).
       - If require_live is False, returns state="DRY_RUN", is_live=False, without writing fake logs.
    """
    job.workdir.mkdir(parents=True, exist_ok=True)

    # Locate Abaqus CLI
    abaqus_cmd = find_abaqus_executable(launcher_cmd)

    if not abaqus_cmd:
        if require_live:
            raise RuntimeError(
                f"Abaqus solver executable not found in PATH or environment for job '{job.job_name}'. "
                f"require_live=True forbids mock/synthetic execution."
            )
        # Authentic Dry-Run: Return without writing any fake solver files
        return AbaqusJobResult(
            job_name=job.job_name,
            state="DRY_RUN",
            returncode=-1,
            workdir=job.workdir,
            is_live=False,
            diagnostics=["Solver executable 'abaqus' not found; dry-run mode (no synthetic logs generated)."],
        )

    # Build execution arguments
    cmd: List[str] = [
        abaqus_cmd,
        f"job={job.job_name}",
        f"input={job.inp_path.name}",
    ]
    if job.interactive:
        cmd.append("interactive")
    if job.cpus > 1:
        cmd.append(f"cpus={job.cpus}")
    if job.gpus > 0:
        cmd.append(f"gpus={job.gpus}")
    if job.double_precision:
        cmd.append("double")
    if job.submodel and job.global_odb:
        cmd.append(f"globalmodel={job.global_odb.name}")

    try:
        from .watchdog import run_with_watchdog, SolverProcessStalledError
        proc = run_with_watchdog(
            cmd,
            cwd=job.workdir,
            timeout=job.timeout_seconds,
            stall_timeout=getattr(job, "stall_timeout_seconds", 120),
        )
    except SolverProcessStalledError as exc:
        diags = parse_solver_diagnostics(job.workdir, job.job_name)
        diags.append(
            f"SOLVER_STALLED: Process stalled for {exc.stall_duration:.1f}s exceeding threshold {exc.stall_timeout:.1f}s"
        )
        if exc.last_stdout_line:
            diags.append(f"STALL_LAST_STDOUT: {exc.last_stdout_line}")
        if exc.last_stderr_line:
            diags.append(f"STALL_LAST_STDERR: {exc.last_stderr_line}")
        return AbaqusJobResult(
            job_name=job.job_name,
            state="ABORTED",
            returncode=-1,
            workdir=job.workdir,
            is_live=True,
            diagnostics=diags,
        )
    except subprocess.TimeoutExpired:
        return AbaqusJobResult(
            job_name=job.job_name,
            state="TIMEOUT",
            returncode=-1,
            workdir=job.workdir,
            is_live=True,
            diagnostics=[f"Solver execution timed out after {job.timeout_seconds}s"],
        )
    except Exception as exc:
        return AbaqusJobResult(
            job_name=job.job_name,
            state="ERROR",
            returncode=-1,
            workdir=job.workdir,
            is_live=True,
            diagnostics=[f"Subprocess invocation failure: {exc}"],
        )

    # Inspect generated artifacts
    odb_path = job.workdir / f"{job.job_name}.odb"
    sta_path = job.workdir / f"{job.job_name}.sta"
    msg_path = job.workdir / f"{job.job_name}.msg"
    dat_path = job.workdir / f"{job.job_name}.dat"
    log_path = job.workdir / f"{job.job_name}.log"

    diags = parse_solver_diagnostics(job.workdir, job.job_name)

    artifacts: Dict[str, Path] = {}
    for p, name in [
        (odb_path, "odb"),
        (sta_path, "sta"),
        (msg_path, "msg"),
        (dat_path, "dat"),
        (log_path, "log"),
    ]:
        if p.is_file():
            artifacts[name] = p

    # Evaluate authentic job outcome
    if proc.returncode != 0:
        state = "ABORTED"
        diags.append(f"Solver process exited with non-zero returncode {proc.returncode}")
    elif not odb_path.is_file() or not is_authentic_binary_odb(odb_path):
        state = "ERROR"
        diags.append("Solver completed returncode 0 but did not produce a valid binary .odb artifact")
    elif any("MSG: Analysis not completed" in d or "STA: Analysis not completed" in d for d in diags):
        state = "ABORTED"
    else:
        state = "COMPLETED"

    return AbaqusJobResult(
        job_name=job.job_name,
        state=state,
        returncode=proc.returncode,
        workdir=job.workdir,
        is_live=True,
        odb_path=odb_path if (odb_path.is_file() and is_authentic_binary_odb(odb_path)) else None,
        sta_path=sta_path if sta_path.is_file() else None,
        msg_path=msg_path if msg_path.is_file() else None,
        dat_path=dat_path if dat_path.is_file() else None,
        log_path=log_path if log_path.is_file() else None,
        diagnostics=diags,
        artifacts=artifacts,
    )


def extract_authentic_odb_mesh_metrics(
    path: Union[str, Path],
    launcher_cmd: Optional[str] = None,
    timeout: int = 60,
) -> Dict[str, Any]:
    """Extract authentic finite element discretization metrics directly from an ODB.

    Returns:
        Dict containing total_elements, total_nodes, element_types, instances breakdown.
    Raises:
        FileNotFoundError if ODB does not exist.
        ValueError if ODB is corrupt or verification fails.
    """
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"ODB file not found: {path}")
    res = verify_authentic_odb_structure(path=path, launcher_cmd=launcher_cmd, timeout=timeout)
    if not res.get("verified", False):
        err = res.get("error", "Failed to verify ODB structure")
        raise ValueError(f"Cannot extract authentic mesh metrics from ODB {path}: {err}")
    mesh_metrics = res.get("mesh_metrics")
    if not isinstance(mesh_metrics, dict):
        raise ValueError(
            f"ODB structure verified for {path}, but authentic 'mesh_metrics' payload is missing or invalid"
        )
    required_keys = ("total_elements", "total_nodes", "element_types", "instances")
    missing_keys = [k for k in required_keys if k not in mesh_metrics]
    if missing_keys:
        raise ValueError(
            f"ODB mesh metrics in {path} is incomplete; missing required keys: {missing_keys}"
        )
    if not isinstance(mesh_metrics.get("instances"), dict) or len(mesh_metrics["instances"]) == 0:
        raise ValueError(
            f"ODB mesh metrics in {path} contains no instances data; cannot certify authentic discretization"
        )
    if mesh_metrics.get("total_elements", 0) <= 0 or mesh_metrics.get("total_nodes", 0) <= 0:
        raise ValueError(
            f"ODB mesh metrics in {path} indicates non-positive discretization "
            f"(elements={mesh_metrics.get('total_elements')}, nodes={mesh_metrics.get('total_nodes')}); "
            f"cannot certify authentic finite element mesh"
        )
    return mesh_metrics
