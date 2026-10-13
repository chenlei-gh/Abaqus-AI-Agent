from __future__ import annotations

import difflib
import hashlib
import math
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union


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
    include_dependencies: Tuple[Dict[str, Any], ...] = ()


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
        self._raw_bytes = self.source_path.read_bytes()
        self.source_sha256 = hashlib.sha256(self._raw_bytes).hexdigest()
        self._newline = "\r\n" if b"\r\n" in self._raw_bytes else "\n"
        self._has_trailing_newline = (
            self._raw_bytes.endswith(b"\n") or self._raw_bytes.endswith(b"\r\n")
        )
        try:
            self._raw_content = self._raw_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"Unsupported character encoding in '{self.source_path}': "
                f"source INP must be valid UTF-8. Error at byte {exc.start}: {exc.reason}"
            ) from exc
        self._lines = self._raw_content.splitlines()

    @staticmethod
    def _validate_token_string(token: str, field_name: str = "identifier") -> str:
        """Validate token to forbid newline injections or leading keyword prefixes."""
        if not isinstance(token, str) or not token.strip():
            raise ValueError(f"{field_name} must be a non-empty string.")
        stripped = token.strip()
        if "\n" in stripped or "\r" in stripped:
            raise ValueError(f"{field_name} cannot contain newline characters: {token!r}")
        if stripped.startswith("*"):
            raise ValueError(f"{field_name} cannot start with '*' (keyword injection attempt): {token!r}")
        return stripped

    @staticmethod
    def _validate_numeric_value(val: Any, field_name: str = "value") -> float:
        """Ensure numeric value is a valid finite float (no NaN, Inf, -Inf)."""
        try:
            num = float(val)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{field_name} must be a valid number, got {val!r}") from exc
        if not math.isfinite(num):
            raise ValueError(f"{field_name} must be finite (got {val!r})")
        return num

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

    @staticmethod
    def _splice_data_lines_preserving_comments(
        block_lines: Sequence[str],
        new_data_lines: Sequence[str],
    ) -> List[str]:
        """Replace data lines in a block while strictly preserving comment and blank line positions.

        Rules:
        1. If original block has identical number of data lines as new_data_lines, each data line
           is replaced in-place in its original slot, leaving all comments and blank lines exactly
           at their relative line positions.
        2. If original block data line count differs from new_data_lines:
           - Comments and blank lines are treated equally as preserved non-data lines.
           - If there are non-data lines interleaved between data lines (i.e. between first and last
             data lines), raise ValueError to fail closed rather than guessing associations.
           - If non-data lines are only leading or trailing, leading lines remain before new data lines,
             followed by new data lines, followed by trailing lines.
        """
        comment_indices: List[int] = []
        blank_indices: List[int] = []
        data_indices: List[int] = []
        for i, line in enumerate(block_lines):
            stripped = line.strip()
            if stripped.startswith("**"):
                comment_indices.append(i)
            elif not stripped:
                blank_indices.append(i)
            else:
                data_indices.append(i)

        non_data_indices = sorted(comment_indices + blank_indices)

        # Case 1: Identical data line counts -> slot-by-slot in-place replacement
        if len(data_indices) == len(new_data_lines):
            result = list(block_lines)
            for orig_idx, new_line in zip(data_indices, new_data_lines):
                result[orig_idx] = new_line
            return result

        # Case 2: Data line count changed. Check for interleaved comments or blank lines.
        if data_indices and non_data_indices:
            first_data = data_indices[0]
            last_data = data_indices[-1]
            has_interleaved = any(first_data < nd_idx < last_data for nd_idx in non_data_indices)
            if has_interleaved:
                raise ValueError(
                    f"Ambiguous comment placement: comments or blank lines are interleaved between data lines "
                    f"and data row count changed from {len(data_indices)} to {len(new_data_lines)}. "
                    "Cannot unambiguously preserve line associations when row count varies."
                )

        # Separate leading non-data lines and trailing non-data lines
        leading_non_data: List[str] = []
        trailing_non_data: List[str] = []
        if data_indices:
            first_data = data_indices[0]
            last_data = data_indices[-1]
            for i, line in enumerate(block_lines):
                if i < first_data:
                    leading_non_data.append(line)
                elif i > last_data:
                    trailing_non_data.append(line)
        else:
            # All lines were non-data
            leading_non_data = list(block_lines)

        return leading_non_data + list(new_data_lines) + trailing_non_data

    def inspect_includes(
        self,
        base_dir: Optional[Union[str, Path]] = None,
        search_dirs: Optional[Sequence[Union[str, Path]]] = None,
        recursive: bool = True,
        visited: Optional[Set[str]] = None,
        active_chain: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Scan all *INCLUDE keywords, verify dependencies recursively, and detect cycles.

        Search Order Guarantee:
        The containing directory of the current file being inspected is ALWAYS the first-priority
        search root. External directories are only probed if the dependency does not reside adjacent
        to the referring file.
        """
        curr_source_resolved = str(self.source_path.resolve())
        chain = list(active_chain or [curr_source_resolved])
        visited_set = set(visited or set())

        # The current file's parent directory is ALWAYS root 0
        current_dir = self.source_path.parent.resolve()
        search_roots: List[Path] = [current_dir]
        if base_dir:
            bp = Path(base_dir).resolve()
            if bp not in search_roots:
                search_roots.append(bp)
        if search_dirs:
            for sd in search_dirs:
                p = Path(sd).resolve()
                if p not in search_roots:
                    search_roots.append(p)

        results: List[Dict[str, Any]] = []
        for i, line in enumerate(self._lines):
            parsed = self._parse_keyword_line(line)
            if parsed and parsed[0] == "INCLUDE":
                input_spec = parsed[1].get("INPUT", "")
                if not input_spec:
                    results.append({
                        "line_number": i + 1,
                        "input": "",
                        "resolved_path": None,
                        "exists": False,
                        "sha256": None,
                        "error": "Missing INPUT parameter in *INCLUDE keyword",
                        "source_deck": curr_source_resolved,
                    })
                    continue

                raw_p = Path(input_spec)
                cand_path: Optional[Path] = None
                if raw_p.is_absolute():
                    cand_path = raw_p.resolve()
                else:
                    for root in search_roots:
                        probe = (root / input_spec).resolve()
                        if probe.is_file():
                            cand_path = probe
                            break
                    if cand_path is None:
                        cand_path = (search_roots[0] / input_spec).resolve()

                cand_path_str = str(cand_path)

                # Cycle detection
                if cand_path_str in chain:
                    cycle_str = " -> ".join(chain + [cand_path_str])
                    raise ValueError(f"Circular *INCLUDE dependency detected: {cycle_str}")

                is_file = cand_path.is_file()
                file_sha256 = None
                if is_file:
                    file_sha256 = hashlib.sha256(cand_path.read_bytes()).hexdigest()

                entry = {
                    "line_number": i + 1,
                    "input": input_spec,
                    "resolved_path": cand_path_str,
                    "exists": is_file,
                    "sha256": file_sha256,
                    "error": None if is_file else f"Referenced file not found in search paths: {cand_path_str}",
                    "source_deck": curr_source_resolved,
                }
                results.append(entry)

                # Recursive descent: child's containing directory becomes the child's primary search root
                if recursive and is_file and cand_path_str not in visited_set:
                    visited_set.add(cand_path_str)
                    child_editor = ControlledInpEditor(cand_path)
                    child_results = child_editor.inspect_includes(
                        base_dir=cand_path.parent.resolve(),
                        search_dirs=search_roots,
                        recursive=True,
                        visited=visited_set,
                        active_chain=chain + [cand_path_str],
                    )
                    results.extend(child_results)

        return results

    def edit_material(
        self,
        material_name: str,
        property_keyword: str,
        new_data_lines: Sequence[Sequence[Union[float, int, str]]],
    ) -> ControlledInpEditor:
        """Surgically modify material property data lines under *MATERIAL, NAME=<material_name>."""
        valid_mat_name = self._validate_token_string(material_name, "material_name")
        prop_kw = property_keyword.strip().upper()
        if not prop_kw.startswith("*"):
            prop_kw = "*" + prop_kw

        # Validate new_data_lines elements
        validated_rows = []
        for r_idx, row in enumerate(new_data_lines):
            row_vals = []
            for c_idx, val in enumerate(row):
                if isinstance(val, (int, float)):
                    row_vals.append(self._validate_numeric_value(val, f"row[{r_idx}][{c_idx}]"))
                else:
                    token_str = self._validate_token_string(str(val), f"row[{r_idx}][{c_idx}]")
                    row_vals.append(token_str)
            validated_rows.append(row_vals)

        # Scan for target *MATERIAL block
        target_mat_indices = []
        for i, line in enumerate(self._lines):
            parsed = self._parse_keyword_line(line)
            if parsed and parsed[0] == "MATERIAL":
                name = parsed[1].get("NAME", "")
                if name.upper() == valid_mat_name.upper():
                    target_mat_indices.append(i)

        if not target_mat_indices:
            raise KeyError(f"Material '{valid_mat_name}' not found in source INP.")
        if len(target_mat_indices) > 1:
            raise ValueError(f"Ambiguous target: multiple *MATERIAL blocks named '{valid_mat_name}' found.")

        mat_start = target_mat_indices[0]
        mat_end = len(self._lines)
        for i in range(mat_start + 1, len(self._lines)):
            parsed = self._parse_keyword_line(self._lines[i])
            if parsed:
                if parsed[0] in ("MATERIAL", "STEP", "PART", "ASSEMBLY", "END PART", "END ASSEMBLY"):
                    mat_end = i
                    break

        # Locate property keyword inside material block and check for ambiguity
        matched_props = []
        for i in range(mat_start + 1, mat_end):
            parsed = self._parse_keyword_line(self._lines[i])
            if parsed and "*" + parsed[0] == prop_kw:
                matched_props.append(i)

        if not matched_props:
            raise KeyError(f"Property '{prop_kw}' not found under material '{valid_mat_name}'.")
        if len(matched_props) > 1:
            raise ValueError(
                f"Ambiguous target: multiple '{prop_kw}' property blocks found under material '{valid_mat_name}'."
            )

        prop_idx = matched_props[0]

        # Find data lines belonging to this property
        data_start = prop_idx + 1
        data_end = data_start
        while data_end < mat_end:
            stripped = self._lines[data_end].strip()
            if stripped.startswith("*") and not stripped.startswith("**"):
                break
            data_end += 1

        formatted_lines = []
        for row in validated_rows:
            row_str = ", ".join(str(val) for val in row)
            formatted_lines.append(f" {row_str}")

        # Preserve exact relative positioning of comments
        block_lines = self._lines[data_start:data_end]
        replacement = self._splice_data_lines_preserving_comments(block_lines, formatted_lines)
        new_lines = list(self._lines)
        new_lines[data_start:data_end] = replacement
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

        # Count total steps to guard against ambiguous multi-step modifications without step_name
        step_indices = []
        for i, line in enumerate(self._lines):
            parsed = self._parse_keyword_line(line)
            if parsed and parsed[0] == "STEP":
                step_indices.append((i, parsed[1].get("NAME", "")))

        target_step_start = 0
        target_step_end = len(self._lines)
        if step_name:
            valid_step = self._validate_token_string(step_name, "step_name")
            matched_steps = [idx for idx, name in step_indices if name.upper() == valid_step.upper()]
            if not matched_steps:
                raise KeyError(f"Step '{valid_step}' not found in source INP.")
            if len(matched_steps) > 1:
                raise ValueError(f"Ambiguous target: multiple steps named '{valid_step}' found.")
            target_step_start = matched_steps[0]
            # Find end of step
            for idx, _ in step_indices:
                if idx > target_step_start:
                    target_step_end = idx
                    break
        else:
            if len(step_indices) > 1:
                raise ValueError(
                    f"Ambiguous target: INP contains {len(step_indices)} steps. "
                    "Explicit 'step_name' is required to prevent cross-step corruption."
                )

        matched_procs = []
        for i in range(target_step_start, target_step_end):
            parsed = self._parse_keyword_line(self._lines[i])
            if parsed and "*" + parsed[0] == proc_kw:
                matched_procs.append(i)

        if not matched_procs:
            raise KeyError(f"Procedure '{proc_kw}' not found in target step.")
        if len(matched_procs) > 1:
            raise ValueError(f"Ambiguous target: multiple '{proc_kw}' procedures found in target scope.")

        proc_idx = matched_procs[0]

        data_start = proc_idx + 1
        data_end = data_start
        while data_end < target_step_end:
            stripped = self._lines[data_end].strip()
            if stripped.startswith("*") and not stripped.startswith("**"):
                break
            data_end += 1

        init_inc = self._validate_numeric_value(time_incrementation.get("initial_inc", 0.1), "initial_inc")
        tot_time = self._validate_numeric_value(time_incrementation.get("total_time", 1.0), "total_time")
        min_inc = self._validate_numeric_value(time_incrementation.get("min_inc", 1e-5), "min_inc")
        max_inc = self._validate_numeric_value(time_incrementation.get("max_inc", tot_time), "max_inc")

        if init_inc <= 0 or tot_time <= 0 or min_inc <= 0 or max_inc < min_inc:
            raise ValueError(f"Invalid incrementation parameters: {time_incrementation}")

        new_data_str = f" {init_inc}, {tot_time}, {min_inc}, {max_inc}"
        block_lines = self._lines[data_start:data_end]
        replacement = self._splice_data_lines_preserving_comments(block_lines, [new_data_str])
        new_lines = list(self._lines)
        new_lines[data_start:data_end] = replacement
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
        valid_set = self._validate_token_string(set_name, "set_name")
        valid_mag = self._validate_numeric_value(new_magnitude, "new_magnitude")
        load_kw = load_keyword.strip().upper()
        if not load_kw.startswith("*"):
            load_kw = "*" + load_kw

        step_start = 0
        step_end = len(self._lines)
        if step_name:
            valid_step = self._validate_token_string(step_name, "step_name")
            step_found = False
            for i, line in enumerate(self._lines):
                parsed = self._parse_keyword_line(line)
                if parsed and parsed[0] == "STEP":
                    if parsed[1].get("NAME", "").upper() == valid_step.upper():
                        step_start = i
                        step_found = True
                    elif step_found:
                        step_end = i
                        break
            if not step_found:
                raise KeyError(f"Step '{valid_step}' not found.")

        # Find matching load entry and check for duplicate ambiguity
        matched_lines = []
        in_load_block = False
        for i in range(step_start, step_end):
            line = self._lines[i]
            parsed = self._parse_keyword_line(line)
            if parsed:
                in_load_block = ("*" + parsed[0] == load_kw)
                continue
            if in_load_block:
                parts = [p.strip() for p in line.split(",")]
                if parts and parts[0].upper() == valid_set.upper():
                    if dof is None or (len(parts) > 1 and parts[1] == str(dof)):
                        matched_lines.append(i)

        if not matched_lines:
            raise KeyError(f"Load entry for set '{valid_set}' under '{load_kw}' not found.")
        if len(matched_lines) > 1:
            raise ValueError(
                f"Ambiguous target: multiple load entries matched set '{valid_set}' under '{load_kw}'."
            )

        load_line_idx = matched_lines[0]
        old_parts = [p.strip() for p in self._lines[load_line_idx].split(",")]
        if len(old_parts) >= 3:
            old_parts[2] = str(valid_mag)
        elif len(old_parts) == 2:
            old_parts[1] = str(valid_mag)
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

        if not requested_variables:
            raise ValueError("requested_variables cannot be empty.")
        validated_vars = [self._validate_token_string(v, "output_variable").upper() for v in requested_variables]

        step_start = 0
        step_end = len(self._lines)
        if step_name:
            valid_step = self._validate_token_string(step_name, "step_name")
            step_found = False
            for i, line in enumerate(self._lines):
                parsed = self._parse_keyword_line(line)
                if parsed and parsed[0] == "STEP":
                    if parsed[1].get("NAME", "").upper() == valid_step.upper():
                        step_start = i
                        step_found = True
                    elif step_found:
                        step_end = i
                        break
            if not step_found:
                raise KeyError(f"Step '{valid_step}' not found.")

        matched_kws = []
        for i in range(step_start, step_end):
            parsed = self._parse_keyword_line(self._lines[i])
            if parsed and "*" + parsed[0] == kw:
                matched_kws.append(i)

        if not matched_kws:
            raise KeyError(f"Output keyword '{kw}' not found in step.")
        if len(matched_kws) > 1:
            raise ValueError(f"Ambiguous target: multiple '{kw}' keywords found in target scope.")

        kw_idx = matched_kws[0]
        data_start = kw_idx + 1
        data_end = data_start
        while data_end < step_end:
            stripped = self._lines[data_end].strip()
            if stripped.startswith("*") and not stripped.startswith("**"):
                break
            data_end += 1

        formatted_vars = " " + ", ".join(validated_vars)
        block_lines = self._lines[data_start:data_end]
        replacement = self._splice_data_lines_preserving_comments(block_lines, [formatted_vars])
        new_lines = list(self._lines)
        new_lines[data_start:data_end] = replacement
        self._lines = new_lines
        return self

    def save(
        self,
        target_path: Union[str, Path],
        overwrite: bool = False,
        allowed_directory: Optional[Union[str, Path]] = None,
        include_dependencies: Sequence[Dict[str, Any]] = (),
    ) -> InpEditAuditRecord:
        """Save the modified INP content to an isolated target path and return verifiable audit record."""
        dest = Path(target_path).resolve()
        if dest == self.source_path:
            raise PermissionError("Zero In-Place Mutation violation: target_path cannot be identical to source_path.")

        if allowed_directory is not None:
            allowed_root = Path(allowed_directory).resolve()
            if not dest.is_relative_to(allowed_root):
                raise ValueError(
                    f"Path escape violation: target_path '{dest}' is outside allowed directory '{allowed_root}'."
                )

        # Verify source file integrity remained 100% untampered
        curr_source_sha = hashlib.sha256(self.source_path.read_bytes()).hexdigest()
        if curr_source_sha != self.source_sha256:
            raise RuntimeError(f"Integrity violation: source INP '{self.source_path}' was modified during edit session.")

        if dest.exists() and not overwrite:
            raise FileExistsError(f"Target file '{dest}' already exists. Pass overwrite=True to permit overwrite.")

        dest.parent.mkdir(parents=True, exist_ok=True)
        # Write bytes deterministically with original newline convention and trailing newline fidelity
        joined_content = self._newline.join(self._lines)
        if self._has_trailing_newline:
            joined_content += self._newline
        new_content_bytes = joined_content.encode("utf-8")
        dest.write_bytes(new_content_bytes)

        # Read actual bytes directly from disk to ensure cryptographic byte-level accuracy
        actual_disk_bytes = dest.read_bytes()
        target_sha256 = hashlib.sha256(actual_disk_bytes).hexdigest()

        # Compute unified diff
        diff_lines = list(difflib.unified_diff(
            self._raw_content.splitlines(keepends=True),
            joined_content.splitlines(keepends=True),
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
            include_dependencies=tuple(include_dependencies),
        )


def edit_inp_file(
    source_path: Union[str, Path],
    target_path: Union[str, Path],
    operations: Sequence[InpEditOperation],
    overwrite: bool = False,
    allowed_directory: Optional[Union[str, Path]] = None,
    include_dependencies: Sequence[Dict[str, Any]] = (),
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

    record = editor.save(
        target_path,
        overwrite=overwrite,
        allowed_directory=allowed_directory,
        include_dependencies=include_dependencies,
    )
    return InpEditAuditRecord(
        source_path=record.source_path,
        target_path=record.target_path,
        source_sha256=record.source_sha256,
        target_sha256=record.target_sha256,
        operations_applied=tuple(applied),
        diff_summary=record.diff_summary,
        lines_changed=record.lines_changed,
        include_dependencies=record.include_dependencies,
    )
