"""Fail-closed pre-submission audit for assembly contract fidelity.

Verifies that the final solver deck (INP) faithfully represents the approved
AssemblyScope:
1. Resolves *PART definitions and their element blocks.
2. Resolves *INSTANCE definitions and maps each instance to its parent Part.
3. Verifies that all retained parts/instances from the contract exist and possess
   non-empty element definitions.
4. Verifies multi-part load transfer paths (contacts/ties) when required by contract.
5. Verifies boundary conditions do not erroneously lock primary moving/loaded members.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from ..geometry.assembly_scope import AssemblyScope


class AssemblyContractViolation(RuntimeError):
    """Raised when an INP violates the approved assembly contract prior to solver submission."""
    pass


@dataclass(frozen=True)
class AssemblyAuditResult:
    passed: bool
    reason: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)


def _normalize_name(name: str) -> str:
    """Normalize identifier for case-insensitive comparison, trimming whitespace and quotes."""
    return re.sub(r'[\s"\'_]+', '', str(name).strip().lower())


def parse_inp_parts_and_instances(inp_text: str) -> Tuple[Dict[str, bool], Dict[str, str], bool]:
    """Parse *PART and *INSTANCE blocks to resolve Part-Instance mapping and element presence.

    Returns:
        (parts_has_elements, instance_to_part, root_has_elements)
        - parts_has_elements: Dict[part_name_norm, bool]
        - instance_to_part: Dict[instance_name_norm, part_name_norm]
        - root_has_elements: bool (True if elements are defined at root or directly in instance)
    """
    lines = inp_text.splitlines()
    
    parts_has_elements: Dict[str, bool] = {}
    instance_to_part: Dict[str, str] = {}
    instance_direct_elements: Dict[str, bool] = {}
    root_has_elements = False

    current_part: Optional[str] = None
    current_instance: Optional[str] = None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("**"):
            continue

        upper = stripped.upper()

        # Part start / end
        if upper.startswith("*PART"):
            match = re.search(r"NAME\s*=\s*([^,\s]+)", stripped, re.IGNORECASE)
            if match:
                current_part = _normalize_name(match.group(1))
                parts_has_elements[current_part] = False
            continue
        elif upper.startswith("*END PART"):
            current_part = None
            continue

        # Instance start / end
        if upper.startswith("*INSTANCE"):
            inst_match = re.search(r"NAME\s*=\s*([^,\s]+)", stripped, re.IGNORECASE)
            part_match = re.search(r"PART\s*=\s*([^,\s]+)", stripped, re.IGNORECASE)
            if inst_match:
                inst_name = _normalize_name(inst_match.group(1))
                current_instance = inst_name
                instance_direct_elements[inst_name] = False
                if part_match:
                    instance_to_part[inst_name] = _normalize_name(part_match.group(1))
            continue
        elif upper.startswith("*END INSTANCE"):
            current_instance = None
            continue

        # Element declaration
        if upper.startswith("*ELEMENT"):
            if current_part is not None:
                parts_has_elements[current_part] = True
            elif current_instance is not None:
                instance_direct_elements[current_instance] = True
            else:
                root_has_elements = True

    # If instance defined elements directly, record it as a self-part
    for inst, has_elem in instance_direct_elements.items():
        if has_elem and inst not in instance_to_part:
            instance_to_part[inst] = inst
            parts_has_elements[inst] = True

    return parts_has_elements, instance_to_part, root_has_elements


def _is_exact_or_canonical_instance_match(req_name: str, candidate_name: str) -> bool:
    """Check if candidate instance matches requested instance or canonical Part-1 format.
    
    Strictly forbids loose substring containment (e.g., 'Handle' must NOT match 'Handle_Base').
    """
    req_norm = _normalize_name(req_name)
    cand_norm = _normalize_name(candidate_name)
    if req_norm == cand_norm:
        return True
    # If request is 'PartName' and candidate is 'PartName1' (Abaqus auto PartName-1 instance)
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
            parts = [p.strip() for p in stripped.split(",")]
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
    # 1. Instance match: strict exact or canonical mapping (NO loose substring matching)
    inst_matched = any(_is_exact_or_canonical_instance_match(req_inst, cand) for cand in cand_insts)
    if not inst_matched:
        return False

    # 2. Surface match: if required surface name is provided, verify strict match
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
        "*SURFACE INTERACTION",
        "*CONNECTOR SECTION",
        "*COUPLING",
        "*COHESIVE SECTION",
    ]
    return any(kw in upper for kw in keywords)


def _verify_contacts_covered(
    inp_text: str,
    scope_contacts: Sequence[Dict[str, Any]],
    inst_to_part: Dict[str, str],
) -> Tuple[bool, Optional[str]]:
    """Verify that required mating contacts in AssemblyScope have corresponding load transfer in INP.
    
    Adheres strictly to fail-closed principles: if interactions cannot be parsed or mapped,
    verification fails rather than passing silently.
    """
    if not scope_contacts:
        return True, None

    # Check keyword existence first
    if not _has_contact_or_interaction(inp_text):
        return (
            False,
            "Assembly contract fidelity violation: multi-part contract requires load-transfer contact pairs, "
            "but no *CONTACT PAIR, *TIE, or *SURFACE INTERACTION was found in the deck.",
        )

    pairs = parse_inp_interactions(inp_text)
    if not pairs:
        # P0-1 FIX: Fail-closed when contact data lines cannot be parsed
        return (
            False,
            "Assembly contract fidelity violation: multi-part contract requires load-transfer contact pairs, "
            "but no parsable *CONTACT PAIR or *TIE interaction data lines were found in the deck.",
        )

    surf_to_insts, surf_to_parts = parse_inp_surfaces(inp_text)

    # Invert inst_to_part: map Part name to all instances instantiating it
    part_to_insts: Dict[str, Set[str]] = {}
    for inst, part in inst_to_part.items():
        part_to_insts.setdefault(part, set()).add(inst)

    # Resolve all interaction pairs into structured candidate sides
    resolved_pairs = []
    for p1, p2 in pairs:
        p1_insts, p1_surf = _resolve_interaction_token(p1, surf_to_insts, surf_to_parts, part_to_insts)
        p2_insts, p2_surf = _resolve_interaction_token(p2, surf_to_insts, surf_to_parts, part_to_insts)
        resolved_pairs.append((p1_insts, p1_surf, p2_insts, p2_surf))

    # Check if each required contact pair is covered by a strictly matching interaction pair
    for sc in scope_contacts:
        m_inst = sc.get("master") or sc.get("master_instance") or sc.get("master_part") or ""
        s_inst = sc.get("slave") or sc.get("slave_instance") or sc.get("slave_part") or ""
        m_surf = sc.get("master_surface") or ""
        s_surf = sc.get("slave_surface") or ""

        pair_matched = False
        for p1_insts, p1_surf, p2_insts, p2_surf in resolved_pairs:
            # Check direct match (master on side 1, slave on side 2)
            if (
                _matches_contact_side(m_inst, m_surf, p1_insts, p1_surf)
                and _matches_contact_side(s_inst, s_surf, p2_insts, p2_surf)
            ):
                pair_matched = True
                break

            # Check reversed match (master on side 2, slave on side 1)
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
            # Check for ENCASTRE or all-DOFs fixed on actuator instance
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
) -> AssemblyAuditResult:
    """Audit the solver input deck against an approved AssemblyScope contract.

    Fail-closed:
    - If assembly_scope requires multiple parts, all retained parts must exist
      with verified element definitions.
    - If contact interactions are specified in the scope, load-transfer pairs
      must exist in the INP and reference valid mating objects.
    - If primary loaded members are specified, they must not be completely locked.
    """
    if not inp_text or not inp_text.strip():
        return AssemblyAuditResult(passed=False, reason="INP text is empty or missing")

    parts_elements, inst_to_part, root_elements = parse_inp_parts_and_instances(inp_text)

    # 1. Baseline element presence: deck must not be completely empty of elements
    has_any_elements = root_elements or any(parts_elements.values())
    if not has_any_elements:
        return AssemblyAuditResult(passed=False, reason="INP contains no valid *ELEMENT definitions")

    # 2. Actuator boundary check MUST execute regardless of single-part or multi-part
    if loaded_instances:
        overconstrained_err = _detect_overconstrained_actuator(inp_text, loaded_instances)
        if overconstrained_err:
            return AssemblyAuditResult(
                passed=False,
                reason=f"Assembly boundary condition violation: {overconstrained_err}",
                diagnostics={"loaded_instances": list(loaded_instances)},
            )

    # If no assembly scope is provided, ensure at least one valid part/mesh exists
    if assembly_scope is None:
        return AssemblyAuditResult(passed=True, diagnostics={"mode": "unscoped_single_part"})

    # Extract contract requirements from AssemblyScope (or its dict representation)
    scope_parts: List[Dict[str, Any]] = []
    scope_contacts: List[Dict[str, Any]] = []
    
    if isinstance(assembly_scope, dict):
        scope_parts = assembly_scope.get("parts") or []
        scope_contacts = assembly_scope.get("contacts") or []
    else:
        # AssemblyScope object
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

    # Multi-part and single-part instance & mesh fidelity audit
    missing_instances: List[str] = []
    empty_instances: List[str] = []
    found_instances: List[str] = []

    for sp in scope_parts:
        req_inst = sp.get("instance_name") or sp.get("name") or ""
        
        # Look for strictly matching instance in INP (no arbitrary substring match, no fallback to Part)
        matched_inst = None
        for inp_inst in inst_to_part:
            if _is_exact_or_canonical_instance_match(req_inst, inp_inst):
                matched_inst = inp_inst
                break

        if matched_inst is None:
            missing_instances.append(req_inst)
        else:
            found_instances.append(matched_inst)
            # Check if parent part has elements
            parent_part = inst_to_part.get(matched_inst, matched_inst)
            if not parts_elements.get(parent_part, False) and not root_elements:
                empty_instances.append(req_inst)

    diagnostics = {
        "contract_parts_count": part_count,
        "found_instances": found_instances,
        "missing_instances": missing_instances,
        "empty_instances": empty_instances,
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

    # P0-2 FIX: Verify all declared instances and mesh existence BEFORE single-part early return.
    # Single-part contract can safely pass without requiring multi-part contact pairs.
    if part_count <= 1:
        return AssemblyAuditResult(
            passed=True,
            diagnostics=dict(diagnostics, mode="single_part", part_count=part_count),
        )

    # Multi-part load transfer path check with reference verification
    contact_ok, contact_err = _verify_contacts_covered(inp_text, scope_contacts, inst_to_part)
    if not contact_ok:
        return AssemblyAuditResult(
            passed=False,
            reason=contact_err,
            diagnostics=diagnostics,
        )

    return AssemblyAuditResult(passed=True, diagnostics=diagnostics)
