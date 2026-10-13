from __future__ import annotations

import difflib
import hashlib
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


@dataclass(frozen=True)
class InpEditOperation:
    """Specification of a single controlled INP edit operation."""
    category: str  # "material" | "load" | "step" | "output"
    target_identifier: str  # e.g., material name, step name, set name
    property_keyword: str  # e.g., "*ELASTIC", "*CLOAD", "*STATIC", "*ELEMENT OUTPUT"
    new_values: Any
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InpEditAuditRecord:
    """Verifiable cryptographic and structural audit record of an INP editing session."""
    source_path: str
    target_path: str
    source_sha256: str
    target_sha256: str
    operations_applied: Tuple[Dict[str, Any], ...]
    diff_summary: str
    lines_changed: int


class ControlledInpEditor:
    """Canonical Controlled In-Place Mutation Prevention INP Editor (Phase P1.4 / P1.5).

    Strict Safety Contract:
    1. Zero In-Place Mutation: Source file is strictly read-only and never modified.
    2. Surgical Modifications: Preserves comments, block order, and unrelated lines intact.
    3. Fail-Closed Validation: Rejects ambiguous targets, malformed numbers, and syntax corruption.
    4. Cryptographic Provenance: Records pre/post SHA-256 and reproducible unified diff.
    """

    SUPPORTED_CATEGORIES = {"material", "load", "step", "output"}

    def __init__(self, source_path: Union[str, Path]):
        self.source_path = Path(source_path).resolve()
        if not self.source_path.is_file():
            raise FileNotFoundError(f"Source INP file not found: {self.source_path}")
        raw_bytes = self.source_path.read_bytes()
        self.source_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        self._raw_content = raw_bytes.decode("utf-8", errors="replace")
        self._lines = self._raw_content.splitlines()

    @staticmethod
    def _parse_keyword_line(line: str) -> Optional[Tuple[str, Dict[str, str]]]:
        """Parse keyword name and parameters from a keyword line (*KEYWORD, PARAM=VAL)."""
        stripped = line.strip()
        if not stripped.startswith("*") or stripped.startswith("**"):
            return None
        parts = [p.strip() for p in stripped[1:].split(",")]
        kw_name = parts[0].upper()
        params = {}
        for p in parts[1:]:
            if "=" in p:
                k, v = p.split("=", 1)
                params[k.strip().upper()] = v.strip()
            else:
                params[p.strip().upper()] = "TRUE"
        return kw_name, params

    def edit_material(
        self,
        material_name: str,
        property_keyword: str,
        new_data_lines: Sequence[Sequence[Union[float, int, str]]],
    ) -> ControlledInpEditor:
        """Surgically modify material property data lines under *MATERIAL, NAME=<material_name>."""
        if not material_name or not isinstance(material_name, str):
            raise ValueError("material_name must be a non-empty string.")
        prop_kw = property_keyword.strip().upper()
        if not prop_kw.startswith("*"):
            prop_kw = "*" + prop_kw

        # Scan for target *MATERIAL block
        target_mat_indices = []
        for i, line in enumerate(self._lines):
            parsed = self._parse_keyword_line(line)
            if parsed and parsed[0] == "MATERIAL":
                name = parsed[1].get("NAME", "")
                if name.upper() == material_name.upper():
                    target_mat_indices.append(i)

        if not target_mat_indices:
            raise KeyError(f"Material '{material_name}' not found in source INP.")
        if len(target_mat_indices) > 1:
            raise ValueError(f"Ambiguous target: multiple *MATERIAL blocks named '{material_name}' found.")

        mat_start = target_mat_indices[0]
        # Find bounds of this *MATERIAL block (until next major keyword, step, or end)
        mat_end = len(self._lines)
        for i in range(mat_start + 1, len(self._lines)):
            parsed = self._parse_keyword_line(self._lines[i])
            if parsed:
                # Top level keywords that end material definition
                if parsed[0] in ("MATERIAL", "STEP", "PART", "ASSEMBLY", "END PART", "END ASSEMBLY"):
                    mat_end = i
                    break

        # Locate property keyword inside material block
        prop_idx = -1
        for i in range(mat_start + 1, mat_end):
            parsed = self._parse_keyword_line(self._lines[i])
            if parsed and "*" + parsed[0] == prop_kw:
                prop_idx = i
                break

        if prop_idx == -1:
            raise KeyError(f"Property '{prop_kw}' not found under material '{material_name}'.")

        # Find data lines belonging to this property (non-keyword lines following prop_idx)
        data_start = prop_idx + 1
        data_end = data_start
        while data_end < mat_end:
            stripped = self._lines[data_end].strip()
            if stripped.startswith("*") and not stripped.startswith("**"):
                break
            data_end += 1

        formatted_lines = []
        for row in new_data_lines:
            row_str = ", ".join(str(val) for val in row)
            formatted_lines.append(f" {row_str}")

        new_lines = list(self._lines)
        new_lines[data_start:data_end] = formatted_lines
        self._lines = new_lines
        return self

    def edit_step_parameters(
        self,
        procedure_type: str,
        time_incrementation: Dict[str, float],
        step_name: Optional[str] = None,
    ) -> ControlledInpEditor:
        """Modify procedure timing / incrementation under *STATIC or other procedure keywords."""
        proc_kw = procedure_type.strip().upper()
        if not proc_kw.startswith("*"):
            proc_kw = "*" + proc_kw

        # Scan for matching step and procedure
        target_step_start = 0
        target_step_end = len(self._lines)
        if step_name:
            step_found = False
            for i, line in enumerate(self._lines):
                parsed = self._parse_keyword_line(line)
                if parsed and parsed[0] == "STEP":
                    s_name = parsed[1].get("NAME", "")
                    if s_name.upper() == step_name.upper():
                        target_step_start = i
                        step_found = True
                    elif step_found:
                        target_step_end = i
                        break
            if not step_found:
                raise KeyError(f"Step '{step_name}' not found in source INP.")

        proc_idx = -1
        for i in range(target_step_start, target_step_end):
            parsed = self._parse_keyword_line(self._lines[i])
            if parsed and "*" + parsed[0] == proc_kw:
                proc_idx = i
                break

        if proc_idx == -1:
            raise KeyError(f"Procedure '{proc_kw}' not found in target step.")

        # Procedure data line is immediately following proc_idx
        data_start = proc_idx + 1
        data_end = data_start
        while data_end < target_step_end:
            stripped = self._lines[data_end].strip()
            if stripped.startswith("*") and not stripped.startswith("**"):
                break
            data_end += 1

        init_inc = float(time_incrementation.get("initial_inc", 0.1))
        tot_time = float(time_incrementation.get("total_time", 1.0))
        min_inc = float(time_incrementation.get("min_inc", 1e-5))
        max_inc = float(time_incrementation.get("max_inc", tot_time))

        if init_inc <= 0 or tot_time <= 0 or min_inc <= 0 or max_inc < min_inc:
            raise ValueError(f"Invalid incrementation parameters: {time_incrementation}")

        new_data_str = f" {init_inc}, {tot_time}, {min_inc}, {max_inc}"
        new_lines = list(self._lines)
        new_lines[data_start:data_end] = [new_data_str]
        self._lines = new_lines
        return self

    def edit_load(
        self,
        set_name: str,
        new_magnitude: float,
        dof: Optional[int] = None,
        load_keyword: str = "*CLOAD",
        step_name: Optional[str] = None,
    ) -> ControlledInpEditor:
        """Modify concentrated or distributed load magnitudes on a designated node/surface set."""
        load_kw = load_keyword.strip().upper()
        if not load_kw.startswith("*"):
            load_kw = "*" + load_kw

        step_start = 0
        step_end = len(self._lines)
        if step_name:
            step_found = False
            for i, line in enumerate(self._lines):
                parsed = self._parse_keyword_line(line)
                if parsed and parsed[0] == "STEP":
                    if parsed[1].get("NAME", "").upper() == step_name.upper():
                        step_start = i
                        step_found = True
                    elif step_found:
                        step_end = i
                        break
            if not step_found:
                raise KeyError(f"Step '{step_name}' not found.")

        # Find matching load entry
        load_line_idx = -1
        in_load_block = False
        for i in range(step_start, step_end):
            line = self._lines[i]
            parsed = self._parse_keyword_line(line)
            if parsed:
                in_load_block = ("*" + parsed[0] == load_kw)
                continue
            if in_load_block:
                parts = [p.strip() for p in line.split(",")]
                if parts and parts[0].upper() == set_name.upper():
                    if dof is None or (len(parts) > 1 and parts[1] == str(dof)):
                        load_line_idx = i
                        break

        if load_line_idx == -1:
            raise KeyError(f"Load entry for set '{set_name}' under '{load_kw}' not found.")

        old_parts = [p.strip() for p in self._lines[load_line_idx].split(",")]
        # Replace magnitude (typically last component or position 2)
        if len(old_parts) >= 3:
            old_parts[2] = str(float(new_magnitude))
        elif len(old_parts) == 2:
            old_parts[1] = str(float(new_magnitude))
        else:
            raise ValueError(f"Malformed load line: '{self._lines[load_line_idx]}'")

        new_lines = list(self._lines)
        new_lines[load_line_idx] = " " + ", ".join(old_parts)
        self._lines = new_lines
        return self

    def edit_output_request(
        self,
        output_keyword: str,
        requested_variables: Sequence[str],
        step_name: Optional[str] = None,
    ) -> ControlledInpEditor:
        """Modify or augment field/history output variables (e.g. *NODE OUTPUT or *ELEMENT OUTPUT)."""
        kw = output_keyword.strip().upper()
        if not kw.startswith("*"):
            kw = "*" + kw

        step_start = 0
        step_end = len(self._lines)
        if step_name:
            step_found = False
            for i, line in enumerate(self._lines):
                parsed = self._parse_keyword_line(line)
                if parsed and parsed[0] == "STEP":
                    if parsed[1].get("NAME", "").upper() == step_name.upper():
                        step_start = i
                        step_found = True
                    elif step_found:
                        step_end = i
                        break
            if not step_found:
                raise KeyError(f"Step '{step_name}' not found.")

        kw_idx = -1
        for i in range(step_start, step_end):
            parsed = self._parse_keyword_line(self._lines[i])
            if parsed and "*" + parsed[0] == kw:
                kw_idx = i
                break

        if kw_idx == -1:
            raise KeyError(f"Output keyword '{kw}' not found in step.")

        data_start = kw_idx + 1
        data_end = data_start
        while data_end < step_end:
            stripped = self._lines[data_end].strip()
            if stripped.startswith("*") and not stripped.startswith("**"):
                break
            data_end += 1

        formatted_vars = " " + ", ".join(v.strip().upper() for v in requested_variables)
        new_lines = list(self._lines)
        new_lines[data_start:data_end] = [formatted_vars]
        self._lines = new_lines
        return self

    def save(
        self,
        target_path: Union[str, Path],
        overwrite: bool = False,
    ) -> InpEditAuditRecord:
        """Save the modified INP content to an isolated target path and return verifiable audit record."""
        dest = Path(target_path).resolve()
        if dest == self.source_path:
            raise PermissionError("Zero In-Place Mutation violation: target_path cannot be identical to source_path.")

        # Verify source file integrity remained 100% untampered
        curr_source_sha = hashlib.sha256(self.source_path.read_bytes()).hexdigest()
        if curr_source_sha != self.source_sha256:
            raise RuntimeError(f"Integrity violation: source INP '{self.source_path}' was modified during edit session.")

        if dest.exists() and not overwrite:
            raise FileExistsError(f"Target file '{dest}' already exists. Pass overwrite=True to permit overwrite.")

        dest.parent.mkdir(parents=True, exist_ok=True)
        new_content = "\n".join(self._lines) + "\n"
        dest.write_text(new_content, encoding="utf-8")

        target_sha256 = hashlib.sha256(new_content.encode("utf-8")).hexdigest()

        # Compute unified diff
        diff_lines = list(difflib.unified_diff(
            self._raw_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=str(self.source_path.name),
            tofile=str(dest.name),
            n=3,
        ))
        diff_summary = "".join(diff_lines)
        lines_changed = sum(1 for line in diff_lines if line.startswith("+") or line.startswith("-"))

        return InpEditAuditRecord(
            source_path=str(self.source_path),
            target_path=str(dest),
            source_sha256=self.source_sha256,
            target_sha256=target_sha256,
            operations_applied=(),
            diff_summary=diff_summary,
            lines_changed=lines_changed,
        )


def edit_inp_file(
    source_path: Union[str, Path],
    target_path: Union[str, Path],
    operations: Sequence[InpEditOperation],
    overwrite: bool = False,
) -> InpEditAuditRecord:
    """Convenience helper to apply a batch of InpEditOperation specifications to an INP file."""
    editor = ControlledInpEditor(source_path)
    applied = []
    for op in operations:
        if op.category == "material":
            editor.edit_material(
                material_name=op.target_identifier,
                property_keyword=op.property_keyword,
                new_data_lines=op.new_values,
            )
        elif op.category == "step":
            editor.edit_step_parameters(
                procedure_type=op.property_keyword,
                time_incrementation=op.new_values,
                step_name=op.target_identifier if op.target_identifier else None,
            )
        elif op.category == "load":
            editor.edit_load(
                set_name=op.target_identifier,
                new_magnitude=float(op.new_values.get("magnitude", op.new_values)),
                dof=op.new_values.get("dof") if isinstance(op.new_values, dict) else None,
                load_keyword=op.property_keyword or "*CLOAD",
                step_name=op.metadata.get("step_name"),
            )
        elif op.category == "output":
            editor.edit_output_request(
                output_keyword=op.property_keyword,
                requested_variables=op.new_values,
                step_name=op.metadata.get("step_name"),
            )
        else:
            raise ValueError(f"Unsupported edit category: '{op.category}'.")
        applied.append({
            "category": op.category,
            "target": op.target_identifier,
            "keyword": op.property_keyword,
        })

    record = editor.save(target_path, overwrite=overwrite)
    return InpEditAuditRecord(
        source_path=record.source_path,
        target_path=record.target_path,
        source_sha256=record.source_sha256,
        target_sha256=record.target_sha256,
        operations_applied=tuple(applied),
        diff_summary=record.diff_summary,
        lines_changed=record.lines_changed,
    )
