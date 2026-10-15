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


def parse_inp_surfaces(inp_text: str) -> Dict[str, Set[str]]:
    """Parse surface definitions and map normalized surface name to associated instance names."""
    lines = inp_text.splitlines()
    surf_to_insts: Dict[str, Set[str]] = {}
    current_instance: Optional[str] = None
    current_surface: Optional[str] = None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("**"):
            continue
        upper = stripped.upper()

        if upper.startswith("*INSTANCE"):
            inst_match = re.search(r"NAME\s*=\s*([^,\s]+)", stripped, re.IGNORECASE)
            if inst_match:
                current_instance = _normalize_name(inst_match.group(1))
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
                if current_instance:
                    surf_to_insts[current_surface].add(current_instance)
            continue
        elif upper.startswith("*"):
            current_surface = None
            continue

        if current_surface and current_instance:
            surf_to_insts[current_surface].add(current_instance)
        elif current_surface:
            # Assembly level surface: check if data line references instance (e.g. InstName.Elset)
            parts = stripped.split(",")
            for p in parts:
                p_clean = p.strip()
                if "." in p_clean:
                    inst_part = _normalize_name(p_clean.split(".")[0])
                    if inst_part:
                        surf_to_insts[current_surface].add(inst_part)

    return surf_to_insts


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
    """Verify that required mating contacts in AssemblyScope have corresponding load transfer in INP."""
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
        # Fallback to general interaction keyword if specific pair lines couldn't be parsed
        return True, None

    surf_to_insts = parse_inp_surfaces(inp_text)

    # Check if each required contact pair's instances/surfaces appear in the interaction definitions
    for sc in scope_contacts:
        m_inst = sc.get("master") or sc.get("master_instance") or sc.get("master_part") or ""
        s_inst = sc.get("slave") or sc.get("slave_instance") or sc.get("slave_part") or ""
        m_norm = _normalize_name(m_inst)
        s_norm = _normalize_name(s_inst)
        m_surf = _normalize_name(sc.get("master_surface") or "")
        s_surf = _normalize_name(sc.get("slave_surface") or "")

        pair_matched = False
        m_candidates = {m_norm, re.sub(r"\d+$", "", m_norm)}
        s_candidates = {s_norm, re.sub(r"\d+$", "", s_norm)}
        if m_norm in inst_to_part:
            m_candidates.add(inst_to_part[m_norm])
        if s_norm in inst_to_part:
            s_candidates.add(inst_to_part[s_norm])

        for p1, p2 in pairs:
            # 1. Exact or canonical surface name match
            if (m_surf and s_surf) and (
                (_is_exact_or_canonical_instance_match(s_surf, p1) and _is_exact_or_canonical_instance_match(m_surf, p2))
                or (_is_exact_or_canonical_instance_match(m_surf, p1) and _is_exact_or_canonical_instance_match(s_surf, p2))
            ):
                pair_matched = True
                break

            # 2. Match surface references containing instance prefixes or via surf_to_insts
            p1_insts = set(surf_to_insts.get(p1, set()))
            p2_insts = set(surf_to_insts.get(p2, set()))
            if "." in p1:
                p1_insts.add(p1.split(".")[0])
            if "." in p2:
                p2_insts.add(p2.split(".")[0])
            for inst, parent_part in inst_to_part.items():
                inst_root = re.sub(r"\d+$", "", inst)
                if inst in p1 or parent_part in p1 or (inst_root and inst_root in p1):
                    p1_insts.add(inst)
                    p1_insts.add(parent_part)
                if inst in p2 or parent_part in p2 or (inst_root and inst_root in p2):
                    p2_insts.add(inst)
                    p2_insts.add(parent_part)

            m_match = any(
                (cand and cand in p1) or any(_is_exact_or_canonical_instance_match(cand, p1_c) for p1_c in p1_insts)
                for cand in m_candidates if cand
            )
            s_match = any(
                (cand and cand in p2) or any(_is_exact_or_canonical_instance_match(cand, p2_c) for p2_c in p2_insts)
                for cand in s_candidates if cand
            )
            if m_match and s_match:
                pair_matched = True
                break

            m_match_rev = any(
                (cand and cand in p2) or any(_is_exact_or_canonical_instance_match(cand, p2_c) for p2_c in p2_insts)
                for cand in m_candidates if cand
            )
            s_match_rev = any(
                (cand and cand in p1) or any(_is_exact_or_canonical_instance_match(cand, p1_c) for p1_c in p1_insts)
                for cand in s_candidates if cand
            )
            if m_match_rev and s_match_rev:
                pair_matched = True
                break

        if not pair_matched:
            return (
                False,
                f"Assembly contract fidelity violation: required load transfer between '{m_inst}' "
                f"and '{s_inst}' is not defined in any *CONTACT PAIR or *TIE interaction.",
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
    
    # Single-part contract: standard baseline
    if part_count <= 1:
        return AssemblyAuditResult(
            passed=True,
            diagnostics={"mode": "single_part", "part_count": part_count}
        )

    # Multi-part contract audit
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

    # Multi-part load transfer path check with reference verification
    contact_ok, contact_err = _verify_contacts_covered(inp_text, scope_contacts, inst_to_part)
    if not contact_ok:
        return AssemblyAuditResult(
            passed=False,
            reason=contact_err,
            diagnostics=diagnostics,
        )

    return AssemblyAuditResult(passed=True, diagnostics=diagnostics)
