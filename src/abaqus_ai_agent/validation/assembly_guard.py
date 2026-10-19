"""Fail-closed pre-submission audit for assembly contract fidelity.

Verifies that the final solver deck (INP) faithfully represents the approved
AssemblyScope:
1. Resolves *PART definitions and their element blocks.
2. Resolves *INSTANCE definitions and maps each instance to its parent Part.
3. Verifies that all retained parts/instances from the contract exist and possess
   non-empty, topographically valid element definitions.
4. Verifies multi-part load transfer paths (contacts/ties) when required by contract.
5. Verifies boundary conditions do not erroneously lock primary moving/loaded members.
6. Enforces fail-closed handling for all external *INCLUDE dependencies.
7. Guarantees deterministic input identity and raw byte hash binding.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from ..geometry.assembly_scope import AssemblyScope


# Abaqus element topologies: map canonical uppercase element type name to expected number of connected nodes.
# Unknown element types will fail-closed and will not be silently deemed valid.
SUPPORTED_ELEMENT_TOPOLOGIES: Dict[str, int] = {
    # 3D Continuum Solid Elements
    "C3D8": 8, "C3D8R": 8, "C3D8I": 8, "C3D8H": 8,
    "C3D20": 20, "C3D20R": 20, "C3D20H": 20, "C3D20RH": 20,
    "C3D4": 4, "C3D4H": 4,
    "C3D10": 10, "C3D10M": 10, "C3D10MH": 10, "C3D10I": 10,
    "C3D6": 6, "C3D6H": 6,
    "C3D15": 15, "C3D15H": 15,
    # Shell Elements
    "S4": 4, "S4R": 4, "S4R5": 4,
    "S3": 3, "S3R": 3,
    "S8R": 8, "S8R5": 8,
    "STRI3": 3, "STRI65": 6,
    # Membrane Elements
    "M3D3": 3, "M3D4": 4, "M3D4R": 4,
    # 2D Continuum Plane Stress / Plane Strain / Axisymmetric Elements
    "CPS4": 4, "CPS4R": 4, "CPE4": 4, "CPE4R": 4, "CAX4": 4, "CAX4R": 4,
    "CPS3": 3, "CPE3": 3, "CAX3": 3,
    "CPS8": 8, "CPS8R": 8, "CPE8": 8, "CPE8R": 8, "CAX8": 8, "CAX8R": 8,
    "CPS6": 6, "CPE6": 6, "CAX6": 6,
    # Beam and Truss Elements
    "B31": 2, "B31H": 2, "B31OS": 2,
    "B32": 3, "B32H": 3,
    "T3D2": 2, "T3D2H": 2,
    "T3D3": 3,
    # Rigid, Point Mass and Discrete Elements
    "R3D4": 4, "R3D3": 3,
    "MASS": 1,
    "SPRING1": 1, "SPRING2": 2, "SPRINGA": 2,
    # Gasket Elements
    "GK3D8": 8, "GK3D8N": 8,
    "GK3D6": 6, "GK3D6N": 6,
    "GK3D4L": 4, "GK3D4LN": 4,
    "GK3D18N": 18,
    "GK3D12M": 12, "GK3D12MN": 12,
    # Connector Elements
    "CONN3D2": 2,
}


class AssemblyContractViolation(RuntimeError):
    """Raised when an INP violates the approved assembly contract prior to solver submission."""
    pass


@dataclass(frozen=True)
class AssemblyAuditResult:
    passed: bool
    reason: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IncludeAuditRecord:
    """Audit record for an *INCLUDE dependency."""
    raw_statement: str
    raw_input: str
    parent_file: Optional[str] = None
    resolved_path: Optional[str] = None
    sha256: Optional[str] = None
    status: str = "ok"  # "ok", "outside_sandbox", "not_found", "circular", "max_depth", "read_error", "malformed"
    error_message: Optional[str] = None


@dataclass
class InteractionDefinition:
    """Structured record of a contact or tie interaction between surfaces."""
    interaction_type: str  # "CONTACT PAIR", "TIE", or unsupported type
    slave_surface: str
    master_surface: str
    is_supported: bool = True
    source_file: Optional[str] = None
    line_number: Optional[int] = None
    details: str = ""


@dataclass
class InpParseContext:
    """Detailed parsing context tracking entities, topology validity, and dependency resolution."""
    parts_has_elements: Dict[str, bool] = field(default_factory=dict)
    instance_to_part: Dict[str, str] = field(default_factory=dict)
    instance_direct_elements: Dict[str, bool] = field(default_factory=dict)
    root_has_elements: bool = False

    part_definitions: Set[str] = field(default_factory=set)
    instance_definitions: Set[str] = field(default_factory=set)
    defined_surfaces: Dict[str, Set[str]] = field(default_factory=dict)  # surf_name_norm -> set of owner inst/part
    
    # Interactions and load-transfer tracking
    interactions: List[InteractionDefinition] = field(default_factory=list)
    unsupported_interactions: List[str] = field(default_factory=list)
    surf_to_insts: Dict[str, Set[str]] = field(default_factory=dict)
    surf_to_parts: Dict[str, Set[str]] = field(default_factory=dict)

    # Fidelity & fail-closed issue trackers
    include_records: List[IncludeAuditRecord] = field(default_factory=list)
    unresolved_includes: List[str] = field(default_factory=list)
    resolved_include_files: Set[Path] = field(default_factory=set)
    include_file_hashes: Dict[str, str] = field(default_factory=dict)
    malformed_elements: List[str] = field(default_factory=list)
    unknown_element_types: List[str] = field(default_factory=list)
    duplicate_element_ids: List[str] = field(default_factory=list)
    naming_collisions: List[str] = field(default_factory=list)
    missing_part_references: List[str] = field(default_factory=list)


def _normalize_name(name: str) -> str:
    """Normalize identifier for case-insensitive comparison, trimming whitespace and quotes."""
    return re.sub(r'[\s"\'_]+', '', str(name).strip().lower())


def _is_path_within_roots(path: Path, roots: Sequence[Path]) -> bool:
    """Check if target path resides strictly within one of the approved root directories.

    Resolves symlinks, normalizes Windows drive letters and case, and rejects traversal escapes.
    """
    try:
        resolved_path = path.resolve()
    except (OSError, RuntimeError):
        return False

    norm_path = os.path.normcase(os.path.normpath(str(resolved_path)))
    for r in roots:
        try:
            resolved_root = r.resolve()
        except (OSError, RuntimeError):
            continue
        norm_root = os.path.normcase(os.path.normpath(str(resolved_root)))
        try:
            if os.path.commonpath([norm_path, norm_root]) == norm_root:
                return True
        except ValueError:
            # Different drive letters on Windows
            continue
    return False


def parse_inp_full_model(
    inp_text: str,
    base_dir: Optional[Union[str, Path]] = None,
    include_chain: Optional[List[Path]] = None,
    allowed_roots: Optional[Sequence[Union[str, Path]]] = None,
    parent_file: Optional[str] = None,
) -> InpParseContext:
    """Parse complete INP structure, resolving INCLUDE dependencies, element topology, and entity mappings.

    Enforces fail-closed parsing:
    - Every *INCLUDE reference must resolve within strictly approved directory sandboxes (allowed_roots).
    - Windows drive letter normalization and symlink escape defense are strictly enforced.
    - Full audit record (IncludeAuditRecord) is maintained for every include dependency.
    - No circular references or recursion explosions (max depth 10).
    - Element lines are verified against canonical topology with strict continuation state machine;
      broken records followed by new element definitions will NEVER be incorrectly spliced.
    - *CONTACT PAIR, *TIE, and *SURFACE definitions are recursively aggregated across all includes.
    - Unknown element types or malformed records are explicitly tracked.
    """
    ctx = InpParseContext()
    if include_chain is None:
        include_chain = []

    # Configure sandbox roots strictly
    resolved_allowed_roots: List[Path] = []
    if allowed_roots is not None:
        for r in allowed_roots:
            try:
                resolved_allowed_roots.append(Path(r).resolve())
            except (OSError, RuntimeError):
                pass
    elif base_dir is not None:
        try:
            resolved_allowed_roots.append(Path(base_dir).resolve())
        except (OSError, RuntimeError):
            pass

    lines = inp_text.splitlines()

    current_part: Optional[str] = None
    current_instance: Optional[str] = None
    current_surface: Optional[str] = None

    in_element_block = False
    current_expected_nodes = 0
    current_element_type: Optional[str] = None

    pending_elem_id: Optional[str] = None
    pending_elem_nodes: List[str] = []
    pending_line_had_trailing_comma = False

    # Interaction block state
    in_interaction_block = False
    current_interaction_type: Optional[str] = None
    current_interaction_line: Optional[int] = None
    interaction_had_data = False

    seen_element_ids_per_scope: Dict[str, Set[str]] = {}
    raw_names_by_norm: Dict[str, str] = {}

    def _get_scope_key() -> str:
        if current_part is not None:
            return f"part:{current_part}"
        if current_instance is not None:
            return f"instance:{current_instance}"
        return "root"

    def _record_valid_element() -> None:
        if current_part is not None:
            ctx.parts_has_elements[current_part] = True
        elif current_instance is not None:
            ctx.instance_direct_elements[current_instance] = True
        else:
            ctx.root_has_elements = True

    def _flush_pending_element(cause: str = "keyword") -> None:
        nonlocal pending_elem_id, pending_elem_nodes, current_expected_nodes, pending_line_had_trailing_comma
        if pending_elem_id is not None:
            if current_expected_nodes > 0 and len(pending_elem_nodes) == current_expected_nodes:
                _record_valid_element()
            else:
                ctx.malformed_elements.append(
                    f"Incomplete element {pending_elem_id} (expected {current_expected_nodes} nodes, "
                    f"got {len(pending_elem_nodes)}) before {cause}"
                )
        pending_elem_id = None
        pending_elem_nodes = []
        pending_line_had_trailing_comma = False

    def _flush_pending_interaction(cause: str = "keyword") -> None:
        nonlocal in_interaction_block, current_interaction_type, current_interaction_line, interaction_had_data
        if in_interaction_block and not interaction_had_data:
            ctx.unsupported_interactions.append(
                f"Empty interaction block '{current_interaction_type}' without data lines at line {current_interaction_line} before {cause}"
            )
        in_interaction_block = False
        current_interaction_type = None
        current_interaction_line = None
        interaction_had_data = False

    for line_idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("**"):
            continue

        upper = stripped.upper()

        # Keyword line
        if upper.startswith("*"):
            _flush_pending_element(f"keyword '{stripped}'")
            _flush_pending_interaction(f"keyword '{stripped}'")
            current_surface = None

            # 1. *INCLUDE handling
            if upper.startswith("*INCLUDE"):
                in_element_block = False
                current_expected_nodes = 0
                current_element_type = None

                inc_match = re.search(r'INPUT\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|([^,\s]+))', stripped, re.IGNORECASE)
                if not inc_match:
                    err_msg = f"Malformed *INCLUDE statement without valid INPUT parameter: '{stripped}' at line {line_idx}"
                    ctx.unresolved_includes.append(err_msg)
                    ctx.include_records.append(
                        IncludeAuditRecord(
                            raw_statement=stripped,
                            raw_input="",
                            parent_file=parent_file,
                            status="malformed",
                            error_message=err_msg,
                        )
                    )
                    continue

                raw_target = (inc_match.group(1) or inc_match.group(2) or inc_match.group(3) or "").strip()
                if not raw_target:
                    err_msg = f"Empty INPUT parameter in *INCLUDE: '{stripped}' at line {line_idx}"
                    ctx.unresolved_includes.append(err_msg)
                    ctx.include_records.append(
                        IncludeAuditRecord(
                            raw_statement=stripped,
                            raw_input=raw_target,
                            parent_file=parent_file,
                            status="malformed",
                            error_message=err_msg,
                        )
                    )
                    continue

                if base_dir is None:
                    err_msg = f"Cannot resolve *INCLUDE '{raw_target}': base_dir not provided at line {line_idx}"
                    ctx.unresolved_includes.append(err_msg)
                    ctx.include_records.append(
                        IncludeAuditRecord(
                            raw_statement=stripped,
                            raw_input=raw_target,
                            parent_file=parent_file,
                            status="outside_sandbox",
                            error_message=err_msg,
                        )
                    )
                    continue

                target_p = Path(raw_target)
                if target_p.is_absolute():
                    candidate_path = target_p
                else:
                    candidate_path = Path(base_dir) / target_p

                try:
                    resolved_inc = candidate_path.resolve()
                except (OSError, RuntimeError) as exc:
                    err_msg = f"Failed to resolve path for *INCLUDE '{raw_target}': {exc}"
                    ctx.unresolved_includes.append(err_msg)
                    ctx.include_records.append(
                        IncludeAuditRecord(
                            raw_statement=stripped,
                            raw_input=raw_target,
                            parent_file=parent_file,
                            status="malformed",
                            error_message=err_msg,
                        )
                    )
                    continue

                # Sandbox security check
                if not _is_path_within_roots(resolved_inc, resolved_allowed_roots):
                    err_msg = (
                        f"Security violation: *INCLUDE target '{raw_target}' resolves to '{resolved_inc}', "
                        f"which is outside approved sandbox roots: {[str(r) for r in resolved_allowed_roots]}"
                    )
                    ctx.unresolved_includes.append(err_msg)
                    ctx.include_records.append(
                        IncludeAuditRecord(
                            raw_statement=stripped,
                            raw_input=raw_target,
                            parent_file=parent_file,
                            resolved_path=str(resolved_inc),
                            status="outside_sandbox",
                            error_message=err_msg,
                        )
                    )
                    continue

                # File existence check
                if not resolved_inc.is_file():
                    err_msg = f"Referenced *INCLUDE file does not exist or is not a regular file: '{raw_target}' (resolved to '{resolved_inc}')"
                    ctx.unresolved_includes.append(err_msg)
                    ctx.include_records.append(
                        IncludeAuditRecord(
                            raw_statement=stripped,
                            raw_input=raw_target,
                            parent_file=parent_file,
                            resolved_path=str(resolved_inc),
                            status="not_found",
                            error_message=err_msg,
                        )
                    )
                    continue

                # Circular dependency check
                if resolved_inc in include_chain:
                    chain_str = " -> ".join(str(p) for p in include_chain + [resolved_inc])
                    err_msg = f"Circular *INCLUDE reference detected: {chain_str}"
                    ctx.unresolved_includes.append(err_msg)
                    ctx.include_records.append(
                        IncludeAuditRecord(
                            raw_statement=stripped,
                            raw_input=raw_target,
                            parent_file=parent_file,
                            resolved_path=str(resolved_inc),
                            status="circular",
                            error_message=err_msg,
                        )
                    )
                    continue

                # Recursion depth limit check
                if len(include_chain) >= 10:
                    err_msg = f"Maximum *INCLUDE recursion depth (10) exceeded at: '{resolved_inc}'"
                    ctx.unresolved_includes.append(err_msg)
                    ctx.include_records.append(
                        IncludeAuditRecord(
                            raw_statement=stripped,
                            raw_input=raw_target,
                            parent_file=parent_file,
                            resolved_path=str(resolved_inc),
                            status="max_depth",
                            error_message=err_msg,
                        )
                    )
                    continue

                # Read raw bytes and decode strictly. Replacement decoding would audit
                # text that differs from the dependency bound by its raw-byte hash, so an
                # undecodable dependency fails closed before any audit record says "ok".
                try:
                    inc_bytes = resolved_inc.read_bytes()
                    inc_hash = hashlib.sha256(inc_bytes).hexdigest()
                    inc_text = inc_bytes.decode("utf-8")
                except UnicodeDecodeError as exc:
                    err_msg = (
                        f"*INCLUDE file '{resolved_inc}' is not valid UTF-8 ({exc}); "
                        "refusing to audit replacement-decoded content."
                    )
                    ctx.unresolved_includes.append(err_msg)
                    ctx.include_records.append(
                        IncludeAuditRecord(
                            raw_statement=stripped,
                            raw_input=raw_target,
                            parent_file=parent_file,
                            resolved_path=str(resolved_inc),
                            status="read_error",
                            error_message=err_msg,
                        )
                    )
                    continue
                except Exception as exc:
                    err_msg = f"Failed to read *INCLUDE file '{resolved_inc}': {exc}"
                    ctx.unresolved_includes.append(err_msg)
                    ctx.include_records.append(
                        IncludeAuditRecord(
                            raw_statement=stripped,
                            raw_input=raw_target,
                            parent_file=parent_file,
                            resolved_path=str(resolved_inc),
                            status="read_error",
                            error_message=err_msg,
                        )
                    )
                    continue

                ctx.include_file_hashes[str(resolved_inc)] = inc_hash
                ctx.resolved_include_files.add(resolved_inc)
                ctx.include_records.append(
                    IncludeAuditRecord(
                        raw_statement=stripped,
                        raw_input=raw_target,
                        parent_file=parent_file,
                        resolved_path=str(resolved_inc),
                        sha256=inc_hash,
                        status="ok",
                    )
                )

                try:
                    sub_ctx = parse_inp_full_model(
                        inc_text,
                        base_dir=resolved_inc.parent,
                        include_chain=include_chain + [resolved_inc],
                        allowed_roots=resolved_allowed_roots,
                        parent_file=str(resolved_inc),
                    )
                except Exception as exc:
                    err_msg = f"Failed to parse *INCLUDE file '{resolved_inc}': {exc}"
                    ctx.unresolved_includes.append(err_msg)
                    ctx.include_records.append(
                        IncludeAuditRecord(
                            raw_statement=stripped,
                            raw_input=raw_target,
                            parent_file=parent_file,
                            resolved_path=str(resolved_inc),
                            status="read_error",
                            error_message=err_msg,
                        )
                    )
                    continue

                # Merge include diagnostics and entities fail-closed
                ctx.include_records.extend(sub_ctx.include_records)
                ctx.unresolved_includes.extend(sub_ctx.unresolved_includes)
                ctx.malformed_elements.extend(sub_ctx.malformed_elements)
                ctx.unknown_element_types.extend(sub_ctx.unknown_element_types)
                ctx.duplicate_element_ids.extend(sub_ctx.duplicate_element_ids)
                ctx.naming_collisions.extend(sub_ctx.naming_collisions)
                ctx.missing_part_references.extend(sub_ctx.missing_part_references)
                ctx.resolved_include_files.update(sub_ctx.resolved_include_files)
                ctx.include_file_hashes.update(sub_ctx.include_file_hashes)
                ctx.part_definitions.update(sub_ctx.part_definitions)
                ctx.instance_definitions.update(sub_ctx.instance_definitions)

                # Merge interactions and surfaces
                ctx.interactions.extend(sub_ctx.interactions)
                ctx.unsupported_interactions.extend(sub_ctx.unsupported_interactions)
                for s_name, owners in sub_ctx.defined_surfaces.items():
                    ctx.defined_surfaces.setdefault(s_name, set()).update(owners)
                for s_name, insts in sub_ctx.surf_to_insts.items():
                    ctx.surf_to_insts.setdefault(s_name, set()).update(insts)
                for s_name, parts in sub_ctx.surf_to_parts.items():
                    ctx.surf_to_parts.setdefault(s_name, set()).update(parts)

                # Merge element definitions
                if current_part is not None:
                    if sub_ctx.root_has_elements or sub_ctx.parts_has_elements.get(current_part, False):
                        ctx.parts_has_elements[current_part] = True
                elif current_instance is not None:
                    if sub_ctx.root_has_elements or sub_ctx.instance_direct_elements.get(current_instance, False):
                        ctx.instance_direct_elements[current_instance] = True
                else:
                    if sub_ctx.root_has_elements:
                        ctx.root_has_elements = True

                for p, has_e in sub_ctx.parts_has_elements.items():
                    if has_e:
                        ctx.parts_has_elements[p] = True
                    elif p not in ctx.parts_has_elements:
                        ctx.parts_has_elements[p] = False

                for inst, p in sub_ctx.instance_to_part.items():
                    ctx.instance_to_part[inst] = p

                continue

            # 2. *ELEMENT keyword handling
            elem_match = re.match(r"^\*ELEMENT(?:\s*,\s*|\s*$)(.*)", upper)
            if elem_match:
                param_str = elem_match.group(1)
                type_match = re.search(r"TYPE\s*=\s*([A-Z0-9]+)", param_str)
                if type_match:
                    elem_type = type_match.group(1).upper()
                    if elem_type in SUPPORTED_ELEMENT_TOPOLOGIES:
                        in_element_block = True
                        current_expected_nodes = SUPPORTED_ELEMENT_TOPOLOGIES[elem_type]
                        current_element_type = elem_type
                    else:
                        in_element_block = False
                        current_expected_nodes = 0
                        current_element_type = None
                        ctx.unknown_element_types.append(f"Unsupported or unknown element TYPE={elem_type} at line {line_idx}")
                else:
                    in_element_block = False
                    current_expected_nodes = 0
                    current_element_type = None
                    ctx.malformed_elements.append(f"Malformed *ELEMENT keyword line without TYPE: '{stripped}' at line {line_idx}")
                continue
            else:
                in_element_block = False
                current_expected_nodes = 0
                current_element_type = None

            # 3. *PART / *END PART
            if upper.startswith("*PART"):
                part_match = re.search(r"NAME\s*=\s*([^,\s]+)", stripped, re.IGNORECASE)
                if part_match:
                    raw_part = part_match.group(1).strip("\"'")
                    norm_part = _normalize_name(raw_part)
                    if norm_part in raw_names_by_norm and raw_names_by_norm[norm_part] != raw_part:
                        ctx.naming_collisions.append(
                            f"Part naming collision: '{raw_part}' collides with '{raw_names_by_norm[norm_part]}' under normalization."
                        )
                    raw_names_by_norm[norm_part] = raw_part

                    current_part = norm_part
                    ctx.part_definitions.add(norm_part)
                    if norm_part not in ctx.parts_has_elements:
                        ctx.parts_has_elements[norm_part] = False
                continue
            elif upper.startswith("*END PART"):
                current_part = None
                continue

            # 4. *INSTANCE / *END INSTANCE
            if upper.startswith("*INSTANCE"):
                inst_match = re.search(r"NAME\s*=\s*([^,\s]+)", stripped, re.IGNORECASE)
                part_match = re.search(r"PART\s*=\s*([^,\s]+)", stripped, re.IGNORECASE)
                if inst_match:
                    raw_inst = inst_match.group(1).strip("\"'")
                    norm_inst = _normalize_name(raw_inst)
                    if norm_inst in raw_names_by_norm and raw_names_by_norm[norm_inst] != raw_inst:
                        ctx.naming_collisions.append(
                            f"Instance naming collision: '{raw_inst}' collides with '{raw_names_by_norm[norm_inst]}' under normalization."
                        )
                    raw_names_by_norm[norm_inst] = raw_inst

                    current_instance = norm_inst
                    ctx.instance_definitions.add(norm_inst)
                    ctx.instance_direct_elements[norm_inst] = False
                    if part_match:
                        raw_parent_part = part_match.group(1).strip("\"'")
                        norm_parent_part = _normalize_name(raw_parent_part)
                        ctx.instance_to_part[norm_inst] = norm_parent_part
                    else:
                        ctx.missing_part_references.append(f"Instance '{raw_inst}' is missing required PART= attribute at line {line_idx}.")
                continue
            elif upper.startswith("*END INSTANCE"):
                current_instance = None
                continue

            # 5. *SURFACE
            if upper.startswith("*SURFACE"):
                surf_match = re.search(r"NAME\s*=\s*([^,\s]+)", stripped, re.IGNORECASE)
                if surf_match:
                    raw_surf = surf_match.group(1).strip("\"'")
                    current_surface = _normalize_name(raw_surf)
                    owner = current_instance or current_part or "assembly"
                    ctx.defined_surfaces.setdefault(current_surface, set()).add(owner)
                    if current_instance:
                        ctx.surf_to_insts.setdefault(current_surface, set()).add(current_instance)
                    elif current_part:
                        ctx.surf_to_parts.setdefault(current_surface, set()).add(current_part)
                continue

            # 6. *CONTACT PAIR / *TIE interactions
            if upper.startswith("*CONTACT PAIR"):
                in_interaction_block = True
                current_interaction_type = "CONTACT PAIR"
                current_interaction_line = line_idx
                interaction_had_data = False
                continue
            elif upper.startswith("*TIE"):
                in_interaction_block = True
                current_interaction_type = "TIE"
                current_interaction_line = line_idx
                interaction_had_data = False
                continue

            continue

        # Data line within *SURFACE definition
        if current_surface:
            parts = [p.strip() for p in stripped.split(",") if p.strip()]
            for p in parts:
                if "." in p:
                    inst_token = _normalize_name(p.split(".")[0])
                    ctx.defined_surfaces.setdefault(current_surface, set()).add(inst_token)
                    ctx.surf_to_insts.setdefault(current_surface, set()).add(inst_token)

        # Data line within interaction block (*CONTACT PAIR, *TIE)
        if in_interaction_block:
            parts = [p.strip() for p in stripped.split(",") if p.strip()]
            if len(parts) >= 2:
                interaction_had_data = True
                s1 = parts[0]
                s2 = parts[1]
                ctx.interactions.append(
                    InteractionDefinition(
                        interaction_type=current_interaction_type or "INTERACTION",
                        slave_surface=s1,
                        master_surface=s2,
                        is_supported=True,
                        source_file=parent_file,
                        line_number=line_idx,
                        details=stripped,
                    )
                )
            else:
                ctx.unsupported_interactions.append(
                    f"Malformed interaction data line '{stripped}' in {current_interaction_type} "
                    f"(expected at least 2 surface names) at line {line_idx}"
                )
            continue

        # Data line within *ELEMENT block
        if in_element_block and current_expected_nodes > 0:
            tokens = [t.strip() for t in stripped.split(",") if t.strip()]
            if not tokens or not all(t.isdigit() for t in tokens):
                ctx.malformed_elements.append(f"Invalid non-integer tokens in *ELEMENT data: '{stripped}' at line {line_idx}")
                _flush_pending_element("invalid non-integer data")
                continue

            line_ends_with_comma = stripped.endswith(",")
            scope = _get_scope_key()
            if scope not in seen_element_ids_per_scope:
                seen_element_ids_per_scope[scope] = set()

            if pending_elem_id is None:
                # Start of a new element record
                elem_id = tokens[0]
                if int(elem_id) <= 0:
                    ctx.malformed_elements.append(f"Invalid non-positive element ID '{elem_id}' in {scope} at line {line_idx}")
                    continue

                if elem_id in seen_element_ids_per_scope[scope]:
                    ctx.duplicate_element_ids.append(f"Duplicate element ID {elem_id} in {scope} at line {line_idx}")
                seen_element_ids_per_scope[scope].add(elem_id)

                nodes = tokens[1:]
                if len(nodes) == 0:
                    ctx.malformed_elements.append(f"Element {elem_id} in {scope} has no node connections on definition line {line_idx}")
                    continue

                if len(nodes) == current_expected_nodes:
                    _record_valid_element()
                elif len(nodes) < current_expected_nodes:
                    pending_elem_id = elem_id
                    pending_elem_nodes = list(nodes)
                    pending_line_had_trailing_comma = line_ends_with_comma
                else:
                    ctx.malformed_elements.append(
                        f"Element {elem_id} in {scope} has {len(nodes)} nodes, exceeding expected {current_expected_nodes} for {current_element_type} at line {line_idx}"
                    )
            else:
                # Processing continuation line for pending_elem_id
                remaining_needed = current_expected_nodes - len(pending_elem_nodes)

                # Rule 1: Fail-closed if previous line lacked trailing comma continuation
                if not pending_line_had_trailing_comma:
                    ctx.malformed_elements.append(
                        f"Incomplete element {pending_elem_id} in {scope} (got {len(pending_elem_nodes)} nodes, "
                        f"expected {current_expected_nodes}) missing trailing comma before record '{stripped}' at line {line_idx}"
                    )
                    pending_elem_id = None
                    pending_elem_nodes = []
                    pending_line_had_trailing_comma = False

                    # Process current line afresh as a new element record
                    elem_id = tokens[0]
                    if int(elem_id) <= 0:
                        ctx.malformed_elements.append(f"Invalid non-positive element ID '{elem_id}' in {scope} at line {line_idx}")
                        continue
                    if elem_id in seen_element_ids_per_scope[scope]:
                        ctx.duplicate_element_ids.append(f"Duplicate element ID {elem_id} in {scope} at line {line_idx}")
                    seen_element_ids_per_scope[scope].add(elem_id)

                    nodes = tokens[1:]
                    if len(nodes) == current_expected_nodes:
                        _record_valid_element()
                    elif len(nodes) < current_expected_nodes:
                        pending_elem_id = elem_id
                        pending_elem_nodes = list(nodes)
                        pending_line_had_trailing_comma = line_ends_with_comma
                    else:
                        ctx.malformed_elements.append(
                            f"Element {elem_id} in {scope} has {len(nodes)} nodes, exceeding expected {current_expected_nodes} for {current_element_type} at line {line_idx}"
                        )
                    continue

                # Rule 2: Determine if current line unmistakably represents a NEW element record
                # Criteria (strictly topology-based, without assumptions of monotonic ID order):
                # a) Length matches standard full definition: 1 ID + expected nodes
                # b) First token is an already known/defined element ID in this scope with multiple tokens
                is_unmistakable_new_elem = False
                if len(tokens) == 1 + current_expected_nodes:
                    is_unmistakable_new_elem = True
                elif tokens[0] in seen_element_ids_per_scope[scope] and len(tokens) >= 2:
                    is_unmistakable_new_elem = True

                if is_unmistakable_new_elem:
                    # Broken previous element followed by an unmistakable new element definition:
                    # Splicing would corrupt mesh topology. Fail-closed on the broken previous element.
                    ctx.malformed_elements.append(
                        f"Incomplete element {pending_elem_id} in {scope} (got {len(pending_elem_nodes)} nodes, "
                        f"expected {current_expected_nodes}) followed by new element definition '{stripped}' at line {line_idx}"
                    )
                    pending_elem_id = None
                    pending_elem_nodes = []
                    pending_line_had_trailing_comma = False

                    # Process current line afresh as new element definition
                    elem_id = tokens[0]
                    if int(elem_id) <= 0:
                        ctx.malformed_elements.append(f"Invalid non-positive element ID '{elem_id}' in {scope} at line {line_idx}")
                        continue
                    if elem_id in seen_element_ids_per_scope[scope]:
                        ctx.duplicate_element_ids.append(f"Duplicate element ID {elem_id} in {scope} at line {line_idx}")
                    seen_element_ids_per_scope[scope].add(elem_id)

                    nodes = tokens[1:]
                    if len(nodes) == current_expected_nodes:
                        _record_valid_element()
                    elif len(nodes) < current_expected_nodes:
                        pending_elem_id = elem_id
                        pending_elem_nodes = list(nodes)
                        pending_line_had_trailing_comma = line_ends_with_comma
                    else:
                        ctx.malformed_elements.append(
                            f"Element {elem_id} in {scope} has {len(nodes)} nodes, exceeding expected {current_expected_nodes} for {current_element_type} at line {line_idx}"
                        )
                    continue

                # Rule 3: Topology capacity check (tokens exceeding remaining needed nodes)
                if len(tokens) > remaining_needed:
                    ctx.malformed_elements.append(
                        f"Continuation line at line {line_idx} has {len(tokens)} tokens, exceeding remaining "
                        f"capacity {remaining_needed} for element {pending_elem_id} ({current_element_type})"
                    )
                    pending_elem_id = None
                    pending_elem_nodes = []
                    pending_line_had_trailing_comma = False
                    continue

                # Rule 4: Reject ambiguous boundary records (never guess or silently splice)
                # a) Reached capacity but line still has trailing comma: syntax indicates further continuation but capacity is full
                if len(tokens) == remaining_needed and line_ends_with_comma:
                    ctx.malformed_elements.append(
                        f"Ambiguous continuation for element {pending_elem_id} in {scope} at line {line_idx}: "
                        f"reached expected {current_expected_nodes} nodes but line retains trailing comma"
                    )
                    pending_elem_id = None
                    pending_elem_nodes = []
                    pending_line_had_trailing_comma = False
                    continue

                # b) Insufficient tokens to reach capacity but missing trailing comma: incomplete continuation without continuation marker
                if len(tokens) < remaining_needed and not line_ends_with_comma:
                    ctx.malformed_elements.append(
                        f"Incomplete continuation for element {pending_elem_id} in {scope} at line {line_idx}: "
                        f"got {len(tokens)} nodes (needed {remaining_needed}) but line lacks trailing comma continuation marker"
                    )
                    pending_elem_id = None
                    pending_elem_nodes = []
                    pending_line_had_trailing_comma = False
                    continue

                # Rule 5: Legitimate continuation line
                if len(tokens) == remaining_needed and not line_ends_with_comma:
                    # Perfectly fulfills remaining topology capacity as terminal continuation line
                    _record_valid_element()
                    pending_elem_id = None
                    pending_elem_nodes = []
                    pending_line_had_trailing_comma = False
                elif len(tokens) < remaining_needed and line_ends_with_comma:
                    # Valid intermediate continuation line in multiline element definition (e.g. C3D20)
                    pending_elem_nodes.extend(tokens)
                    pending_line_had_trailing_comma = True

    _flush_pending_element("end of deck")
    _flush_pending_interaction("end of deck")

    # Finalize direct instance elements
    for inst, has_elem in ctx.instance_direct_elements.items():
        if has_elem and inst not in ctx.instance_to_part:
            ctx.instance_to_part[inst] = inst
            ctx.parts_has_elements[inst] = True
            ctx.part_definitions.add(inst)

    # Check for instances referencing non-existent parts
    for inst, part in ctx.instance_to_part.items():
        if part not in ctx.part_definitions:
            ctx.missing_part_references.append(f"Instance '{inst}' references undefined Part '{part}'")

    return ctx


def parse_inp_parts_and_instances(
    inp_text: str,
    base_dir: Optional[Union[str, Path]] = None,
) -> Tuple[Dict[str, bool], Dict[str, str], bool]:
    """Parse *PART and *INSTANCE blocks to resolve Part-Instance mapping and element presence.

    Returns:
        (parts_has_elements, instance_to_part, root_has_elements)
    """
    ctx = parse_inp_full_model(inp_text, base_dir=base_dir)
    return ctx.parts_has_elements, ctx.instance_to_part, ctx.root_has_elements


def _is_exact_or_canonical_instance_match(req_name: str, candidate_name: str) -> bool:
    """Check if candidate instance matches requested instance or canonical Part-1 format.
    
    Strictly forbids loose substring containment (e.g., 'Handle' must NOT match 'Handle_Base').
    """
    req_norm = _normalize_name(req_name)
    cand_norm = _normalize_name(candidate_name)
    if req_norm == cand_norm:
        return True
    if cand_norm == f"{req_norm}1":
        return True
    if req_norm == f"{cand_norm}1":
        return True
    return False


def parse_inp_interactions(inp_text: str) -> List[Tuple[str, str]]:
    """Parse *TIE and *CONTACT PAIR definitions from INP to extract connected surface/instance pairs."""
    lines = inp_text.splitlines()
    pairs: List[Tuple[str, str]] = []
    in_interaction = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("**"):
            continue
        upper = stripped.upper()

        if upper.startswith("*CONTACT PAIR") or upper.startswith("*TIE"):
            in_interaction = True
            continue
        elif upper.startswith("*"):
            in_interaction = False
            continue

        if in_interaction:
            # Data line: slave_surface, master_surface
            parts = [p.strip() for p in stripped.split(",") if p.strip()]
            if len(parts) >= 2:
                s1 = _normalize_name(parts[0])
                s2 = _normalize_name(parts[1])
                if s1 and s2:
                    pairs.append((s1, s2))

    return pairs


def parse_inp_surfaces(inp_text: str) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """Parse surface definitions and map normalized surface name to associated instance names and part names."""
    lines = inp_text.splitlines()
    surf_to_insts: Dict[str, Set[str]] = {}
    surf_to_parts: Dict[str, Set[str]] = {}
    current_instance: Optional[str] = None
    current_part: Optional[str] = None
    current_surface: Optional[str] = None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("**"):
            continue
        upper = stripped.upper()

        if upper.startswith("*PART"):
            part_match = re.search(r"NAME\s*=\s*([^,\s]+)", stripped, re.IGNORECASE)
            if part_match:
                current_part = _normalize_name(part_match.group(1))
            current_instance = None
            continue
        elif upper.startswith("*END PART"):
            current_part = None
            continue

        if upper.startswith("*INSTANCE"):
            inst_match = re.search(r"NAME\s*=\s*([^,\s]+)", stripped, re.IGNORECASE)
            if inst_match:
                current_instance = _normalize_name(inst_match.group(1))
            current_part = None
            continue
        elif upper.startswith("*END INSTANCE"):
            current_instance = None
            continue

        if upper.startswith("*SURFACE"):
            surf_match = re.search(r"NAME\s*=\s*([^,\s]+)", stripped, re.IGNORECASE)
            if surf_match:
                current_surface = _normalize_name(surf_match.group(1))
                if current_surface not in surf_to_insts:
                    surf_to_insts[current_surface] = set()
                if current_surface not in surf_to_parts:
                    surf_to_parts[current_surface] = set()
                if current_instance:
                    surf_to_insts[current_surface].add(current_instance)
                elif current_part:
                    surf_to_parts[current_surface].add(current_part)
            continue
        elif upper.startswith("*"):
            current_surface = None
            continue

        if current_surface:
            if current_instance:
                surf_to_insts[current_surface].add(current_instance)
            elif current_part:
                surf_to_parts[current_surface].add(current_part)
            else:
                # Assembly level surface: check if data line references instance (e.g. InstName.Elset)
                parts = stripped.split(",")
                for p in parts:
                    p_clean = p.strip()
                    if "." in p_clean:
                        inst_part = _normalize_name(p_clean.split(".")[0])
                        if inst_part:
                            surf_to_insts[current_surface].add(inst_part)

    return surf_to_insts, surf_to_parts


def _resolve_interaction_token(
    token: str,
    surf_to_insts: Dict[str, Set[str]],
    surf_to_parts: Dict[str, Set[str]],
    part_to_insts: Dict[str, Set[str]],
) -> Tuple[Set[str], str]:
    """Resolve an interaction token (e.g. 'INST.SURF' or 'SURF') to associated candidate instance names and surface name."""
    token_norm = _normalize_name(token)
    if "." in token_norm:
        inst_or_part, surf_name = token_norm.split(".", 1)
        insts = {inst_or_part}
        if inst_or_part in part_to_insts:
            insts.update(part_to_insts[inst_or_part])
        return insts, surf_name

    surf_name = token_norm
    insts = set(surf_to_insts.get(surf_name, set()))
    for p in surf_to_parts.get(surf_name, set()):
        if p in part_to_insts:
            insts.update(part_to_insts[p])
        else:
            insts.add(p)
    return insts, surf_name


def _matches_contact_side(
    req_inst: str,
    req_surf: str,
    cand_insts: Set[str],
    cand_surf: str,
) -> bool:
    """Strictly verify if candidate interaction side matches required instance and surface.
    
    Eliminates all loose substring matching and adheres strictly to canonical equivalence.
    """
    inst_matched = any(_is_exact_or_canonical_instance_match(req_inst, cand) for cand in cand_insts)
    if not inst_matched:
        return False

    if req_surf:
        norm_req_surf = _normalize_name(req_surf)
        return norm_req_surf == cand_surf or _is_exact_or_canonical_instance_match(norm_req_surf, cand_surf)

    return True


def _has_contact_or_interaction(inp_text: str) -> bool:
    """Check whether multi-part load transfer definitions exist in INP."""
    upper = inp_text.upper()
    keywords = [
        "*CONTACT PAIR",
        "*TIE",
        "*CONNECTOR SECTION",
        "*COUPLING",
        "*COHESIVE SECTION",
    ]
    return any(kw in upper for kw in keywords)


def _verify_contacts_covered(
    inp_text: Optional[str] = None,
    scope_contacts: Sequence[Dict[str, Any]] = (),
    inst_to_part: Optional[Dict[str, str]] = None,
    defined_surfaces: Optional[Dict[str, Set[str]]] = None,
    interactions: Optional[Sequence[InteractionDefinition]] = None,
    surf_to_insts: Optional[Dict[str, Set[str]]] = None,
    surf_to_parts: Optional[Dict[str, Set[str]]] = None,
) -> Tuple[bool, Optional[str]]:
    """Verify that required mating contacts in AssemblyScope have corresponding load transfer in INP.

    Supports cross-INCLUDE model context resolution for interactions and surfaces.
    """
    if inst_to_part is None:
        inst_to_part = {}

    # Extract interaction pairs either from structured context or raw INP
    pairs: List[Tuple[str, str]] = []
    if interactions is not None:
        pairs = [(inter.slave_surface, inter.master_surface) for inter in interactions if inter.is_supported]
    elif inp_text is not None:
        pairs = parse_inp_interactions(inp_text)

    if surf_to_insts is None or surf_to_parts is None:
        fallback_insts, fallback_parts = parse_inp_surfaces(inp_text or "")
        surf_to_insts = surf_to_insts if surf_to_insts is not None else fallback_insts
        surf_to_parts = surf_to_parts if surf_to_parts is not None else fallback_parts

    # Invert inst_to_part: map Part name to all instances instantiating it
    part_to_insts: Dict[str, Set[str]] = {}
    for inst, part in inst_to_part.items():
        part_to_insts.setdefault(part, set()).add(inst)

    # Verify that surfaces referenced in interactions actually exist across context
    all_known_surfaces: Set[str] = set()
    if defined_surfaces:
        all_known_surfaces.update(defined_surfaces.keys())
    if surf_to_insts:
        all_known_surfaces.update(surf_to_insts.keys())
    if surf_to_parts:
        all_known_surfaces.update(surf_to_parts.keys())

    if all_known_surfaces and pairs:
        for p1, p2 in pairs:
            for s_token in (p1, p2):
                s_name = _normalize_name(s_token.split(".", 1)[-1] if "." in s_token else s_token)
                if s_name not in all_known_surfaces:
                    return (
                        False,
                        f"Assembly contract fidelity violation: interaction references undefined surface '{s_token}'.",
                    )

    if not scope_contacts:
        return True, None

    if not pairs:
        # Fallback keyword presence check
        has_keywords = _has_contact_or_interaction(inp_text) if inp_text else False
        if not has_keywords:
            return (
                False,
                "Assembly contract fidelity violation: multi-part contract requires load-transfer contact pairs, "
                "but no *CONTACT PAIR, *TIE, *CONNECTOR SECTION, or *COUPLING was found in the deck.",
            )
        return (
            False,
            "Assembly contract fidelity violation: multi-part contract requires load-transfer contact pairs, "
            "but no parsable *CONTACT PAIR or *TIE interaction data lines were found in the deck.",
        )

    resolved_pairs = []
    for p1, p2 in pairs:
        p1_insts, p1_surf = _resolve_interaction_token(p1, surf_to_insts, surf_to_parts, part_to_insts)
        p2_insts, p2_surf = _resolve_interaction_token(p2, surf_to_insts, surf_to_parts, part_to_insts)
        resolved_pairs.append((p1_insts, p1_surf, p2_insts, p2_surf))

    for sc in scope_contacts:
        m_inst = sc.get("master") or sc.get("master_instance") or sc.get("master_part") or ""
        s_inst = sc.get("slave") or sc.get("slave_instance") or sc.get("slave_part") or ""
        m_surf = sc.get("master_surface") or ""
        s_surf = sc.get("slave_surface") or ""

        pair_matched = False
        for p1_insts, p1_surf, p2_insts, p2_surf in resolved_pairs:
            if (
                _matches_contact_side(m_inst, m_surf, p1_insts, p1_surf)
                and _matches_contact_side(s_inst, s_surf, p2_insts, p2_surf)
            ):
                pair_matched = True
                break

            if (
                _matches_contact_side(m_inst, m_surf, p2_insts, p2_surf)
                and _matches_contact_side(s_inst, s_surf, p1_insts, p1_surf)
            ):
                pair_matched = True
                break

        if not pair_matched:
            return (
                False,
                f"Assembly contract fidelity violation: required load transfer between '{m_inst}' "
                f"and '{s_inst}' is not defined in any valid *CONTACT PAIR or *TIE interaction.",
            )

    return True, None


def _detect_overconstrained_actuator(inp_text: str, loaded_instances: Sequence[str]) -> Optional[str]:
    """Check if primary moving/actuator instance is completely locked with ENCASTRE at assembly level."""
    if not loaded_instances:
        return None

    normalized_loaded = {_normalize_name(inst) for inst in loaded_instances}
    lines = inp_text.splitlines()
    in_boundary = False
    
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("**"):
            continue
        upper = stripped.upper()

        if upper.startswith("*BOUNDARY"):
            in_boundary = True
            continue
        elif upper.startswith("*") and not upper.startswith("**"):
            in_boundary = False

        if in_boundary:
            if "ENCASTRE" in upper:
                for inst in normalized_loaded:
                    norm_line = _normalize_name(stripped)
                    if inst in norm_line or f"{inst}1" in norm_line:
                        return f"Actuator instance '{inst}' is completely locked with ENCASTRE in *BOUNDARY"
    return None


def audit_inp_assembly_contract(
    inp_text: str,
    assembly_scope: Optional[Union[AssemblyScope, Dict[str, Any]]] = None,
    loaded_instances: Optional[Sequence[str]] = None,
    base_dir: Optional[Union[str, Path]] = None,
    allowed_roots: Optional[Sequence[Union[str, Path]]] = None,
) -> AssemblyAuditResult:
    """Audit the solver input deck against an approved AssemblyScope contract.

    Fail-closed:
    - All *INCLUDE external references must resolve successfully within approved sandboxes.
    - All element blocks must define valid topologies matching supported types.
    - Malformed element lines, duplicate IDs, or broken continuations trigger rejection.
    - Missing parts, instance-part mapping inconsistencies, or naming collisions trigger rejection.
    - If assembly_scope requires multiple parts, all retained parts must exist with verified mesh.
    - If contact interactions are specified in the scope, load-transfer pairs must match verified surfaces.
    - If primary loaded members are specified, they must not be completely locked.
    """
    if not inp_text or not inp_text.strip():
        return AssemblyAuditResult(passed=False, reason="INP text is empty or missing")

    ctx = parse_inp_full_model(inp_text, base_dir=base_dir, allowed_roots=allowed_roots)

    # 1. External *INCLUDE fail-closed verification
    if ctx.unresolved_includes:
        reasons = "; ".join(ctx.unresolved_includes)
        return AssemblyAuditResult(
            passed=False,
            reason=f"Assembly contract fidelity violation: unresolved or invalid *INCLUDE reference(s): {reasons}",
            diagnostics={
                "unresolved_includes": ctx.unresolved_includes,
                "include_records": [asdict(r) for r in ctx.include_records],
            },
        )

    # 2. Element definition & topology fail-closed verification
    if ctx.unknown_element_types:
        reasons = "; ".join(ctx.unknown_element_types)
        return AssemblyAuditResult(
            passed=False,
            reason=f"Assembly contract fidelity violation: unsupported or unknown element type(s): {reasons}",
            diagnostics={
                "unknown_element_types": ctx.unknown_element_types,
                "include_records": [asdict(r) for r in ctx.include_records],
            },
        )

    if ctx.malformed_elements:
        reasons = "; ".join(ctx.malformed_elements[:5])
        if len(ctx.malformed_elements) > 5:
            reasons += f" (and {len(ctx.malformed_elements) - 5} more)"
        return AssemblyAuditResult(
            passed=False,
            reason=f"Assembly contract fidelity violation: malformed element definition(s): {reasons}",
            diagnostics={
                "malformed_elements": ctx.malformed_elements,
                "include_records": [asdict(r) for r in ctx.include_records],
            },
        )

    if ctx.duplicate_element_ids:
        reasons = "; ".join(ctx.duplicate_element_ids[:5])
        return AssemblyAuditResult(
            passed=False,
            reason=f"Assembly contract fidelity violation: duplicate element ID(s): {reasons}",
            diagnostics={
                "duplicate_element_ids": ctx.duplicate_element_ids,
                "include_records": [asdict(r) for r in ctx.include_records],
            },
        )

    # 3. Entity consistency & naming conflict verification
    if ctx.naming_collisions:
        reasons = "; ".join(ctx.naming_collisions)
        return AssemblyAuditResult(
            passed=False,
            reason=f"Assembly contract fidelity violation: entity naming collision(s): {reasons}",
            diagnostics={
                "naming_collisions": ctx.naming_collisions,
                "include_records": [asdict(r) for r in ctx.include_records],
            },
        )

    if ctx.missing_part_references:
        reasons = "; ".join(ctx.missing_part_references)
        return AssemblyAuditResult(
            passed=False,
            reason=f"Assembly contract fidelity violation: missing part reference(s): {reasons}",
            diagnostics={
                "missing_part_references": ctx.missing_part_references,
                "include_records": [asdict(r) for r in ctx.include_records],
            },
        )

    # 4. Interaction syntax and structure verification
    if ctx.unsupported_interactions:
        reasons = "; ".join(ctx.unsupported_interactions[:5])
        return AssemblyAuditResult(
            passed=False,
            reason=f"Assembly contract fidelity violation: unsupported or malformed interaction(s): {reasons}",
            diagnostics={
                "unsupported_interactions": ctx.unsupported_interactions,
                "include_records": [asdict(r) for r in ctx.include_records],
            },
        )

    # 5. Baseline element presence: deck must not be completely empty of elements
    has_any_elements = ctx.root_has_elements or any(ctx.parts_has_elements.values())
    if not has_any_elements:
        return AssemblyAuditResult(
            passed=False,
            reason="INP contains no valid *ELEMENT definitions",
            diagnostics={"include_records": [asdict(r) for r in ctx.include_records]},
        )

    # 6. Actuator boundary check MUST execute regardless of single-part or multi-part
    if loaded_instances:
        overconstrained_err = _detect_overconstrained_actuator(inp_text, loaded_instances)
        if overconstrained_err:
            return AssemblyAuditResult(
                passed=False,
                reason=f"Assembly boundary condition violation: {overconstrained_err}",
                diagnostics={
                    "loaded_instances": list(loaded_instances),
                    "include_records": [asdict(r) for r in ctx.include_records],
                },
            )

    # If no assembly scope is provided, ensure at least one valid part/mesh exists
    if assembly_scope is None:
        return AssemblyAuditResult(
            passed=True,
            diagnostics={
                "mode": "unscoped_single_part",
                "resolved_include_files": [str(p) for p in ctx.resolved_include_files],
                "audited_include_hashes": dict(ctx.include_file_hashes),
                "include_records": [asdict(r) for r in ctx.include_records],
            },
        )

    # Extract contract requirements from AssemblyScope (or its dict representation)
    scope_parts: List[Dict[str, Any]] = []
    scope_contacts: List[Dict[str, Any]] = []
    
    if isinstance(assembly_scope, dict):
        scope_parts = assembly_scope.get("parts") or []
        scope_contacts = assembly_scope.get("contacts") or []
    else:
        scope_parts = [
            {"name": p.name, "instance_name": p.instance_name, "step_body_index": p.step_body_index}
            for p in getattr(assembly_scope, "parts", ())
        ]
        scope_contacts = [
            {
                "master": c.master_instance,
                "slave": c.slave_instance,
                "master_instance": c.master_instance,
                "slave_instance": c.slave_instance,
                "master_surface": c.master_surface,
                "slave_surface": c.slave_surface,
                "master_part": c.master_part,
                "slave_part": c.slave_part,
            }
            for c in getattr(assembly_scope, "contacts", ())
        ]

    part_count = len(scope_parts)

    missing_instances: List[str] = []
    empty_instances: List[str] = []
    found_instances: List[str] = []

    for sp in scope_parts:
        req_inst = sp.get("instance_name") or sp.get("name") or ""
        
        matched_inst = None
        for inp_inst in ctx.instance_to_part:
            if _is_exact_or_canonical_instance_match(req_inst, inp_inst):
                matched_inst = inp_inst
                break

        if matched_inst is None:
            missing_instances.append(req_inst)
        else:
            found_instances.append(matched_inst)
            parent_part = ctx.instance_to_part.get(matched_inst, matched_inst)
            if not ctx.parts_has_elements.get(parent_part, False):
                empty_instances.append(req_inst)

    diagnostics = {
        "contract_parts_count": part_count,
        "found_instances": found_instances,
        "missing_instances": missing_instances,
        "empty_instances": empty_instances,
        "resolved_include_files": [str(p) for p in ctx.resolved_include_files],
        "audited_include_hashes": dict(ctx.include_file_hashes),
        "include_records": [asdict(r) for r in ctx.include_records],
    }

    if missing_instances:
        return AssemblyAuditResult(
            passed=False,
            reason=(
                f"Assembly contract fidelity violation: required retained instance(s) {missing_instances} "
                f"are missing from the solver deck. Unilateral degradation to single-part is prohibited."
            ),
            diagnostics=diagnostics,
        )

    if empty_instances:
        return AssemblyAuditResult(
            passed=False,
            reason=(
                f"Assembly contract fidelity violation: required instance(s) {empty_instances} "
                f"reference parts without valid *ELEMENT definitions."
            ),
            diagnostics=diagnostics,
        )

    # Single-part contract early return
    if part_count <= 1:
        return AssemblyAuditResult(
            passed=True,
            diagnostics=dict(diagnostics, mode="single_part", part_count=part_count),
        )

    # Multi-part load transfer path check with cross-include reference verification
    contact_ok, contact_err = _verify_contacts_covered(
        inp_text=inp_text,
        scope_contacts=scope_contacts,
        inst_to_part=ctx.instance_to_part,
        defined_surfaces=ctx.defined_surfaces,
        interactions=ctx.interactions,
        surf_to_insts=ctx.surf_to_insts,
        surf_to_parts=ctx.surf_to_parts,
    )
    if not contact_ok:
        return AssemblyAuditResult(
            passed=False,
            reason=contact_err,
            diagnostics=diagnostics,
        )

    return AssemblyAuditResult(passed=True, diagnostics=diagnostics)
