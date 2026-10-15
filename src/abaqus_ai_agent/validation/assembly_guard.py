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
                    if inst in _normalize_name(stripped):
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
      must exist in the INP.
    - If primary loaded members are specified, they must not be completely locked.
    """
    if not inp_text or not inp_text.strip():
        return AssemblyAuditResult(passed=False, reason="INP text is empty or missing")

    parts_elements, inst_to_part, root_elements = parse_inp_parts_and_instances(inp_text)

    # 1. Baseline element presence: deck must not be completely empty of elements
    has_any_elements = root_elements or any(parts_elements.values())
    if not has_any_elements:
        return AssemblyAuditResult(passed=False, reason="INP contains no valid *ELEMENT definitions")

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
            {"master": c.master_instance, "slave": c.slave_instance}
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
        req_norm = _normalize_name(req_inst)

        # Look for matching instance in INP
        matched_inst = None
        for inp_inst in inst_to_part:
            if req_norm == inp_inst or req_norm in inp_inst or inp_inst in req_norm:
                matched_inst = inp_inst
                break

        # Also fallback to part name matching if instances aren't uniquely renamed
        if matched_inst is None:
            for inp_part in parts_elements:
                if req_norm == inp_part or req_norm in inp_part or inp_part in req_norm:
                    matched_inst = inp_part
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

    # Multi-part load transfer path check
    if scope_contacts and not _has_contact_or_interaction(inp_text):
        return AssemblyAuditResult(
            passed=False,
            reason=(
                "Assembly contract fidelity violation: multi-part contract requires load-transfer contact pairs, "
                "but no *CONTACT PAIR, *TIE, or *SURFACE INTERACTION was found in the deck."
            ),
            diagnostics=diagnostics,
        )

    # Actuator boundary check
    if loaded_instances:
        overconstrained_err = _detect_overconstrained_actuator(inp_text, loaded_instances)
        if overconstrained_err:
            return AssemblyAuditResult(
                passed=False,
                reason=f"Assembly boundary condition violation: {overconstrained_err}",
                diagnostics=diagnostics,
            )

    return AssemblyAuditResult(passed=True, diagnostics=diagnostics)
