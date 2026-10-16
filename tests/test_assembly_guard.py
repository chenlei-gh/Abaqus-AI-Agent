import pytest

from abaqus_ai_agent.validation.assembly_guard import (
    audit_inp_assembly_contract,
    parse_inp_parts_and_instances,
    AssemblyAuditResult,
)


LEGAL_SINGLE_PART_INP = """
*HEADING
Single part model
*PART, NAME=CANTILEVER
*NODE
1, 0.0, 0.0, 0.0
2, 10.0, 0.0, 0.0
*ELEMENT, TYPE=C3D8R, ELSET=ALLELEMS
1, 1, 2, 3, 4, 5, 6, 7, 8
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=CANTILEVER-1, PART=CANTILEVER
*END INSTANCE
*END ASSEMBLY
*STEP
*STATIC
*END STEP
"""

LEGAL_MULTIPART_INP = """
*HEADING
Door handle assembly
*PART, NAME=HANDLE
*NODE
1, 0.0, 0.0, 0.0
*ELEMENT, TYPE=C3D10M, ELSET=HANDLE_ELEMS
1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*SURFACE, NAME=HANDLE_SURF
HANDLE_ELEMS, S1
*END PART
*PART, NAME=BASE
*NODE
100, 0.0, 0.0, 0.0
*ELEMENT, TYPE=C3D10M, ELSET=BASE_ELEMS
100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110
*SURFACE, NAME=BASE_SURF
BASE_ELEMS, S1
*END PART
*PART, NAME=PIN
*NODE
200, 0.0, 0.0, 0.0
*ELEMENT, TYPE=C3D8R, ELSET=PIN_ELEMS
200, 201, 202, 203, 204, 205, 206, 207, 208
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=HANDLE_1, PART=HANDLE
*END INSTANCE
*INSTANCE, NAME=BASE_1, PART=BASE
*END INSTANCE
*INSTANCE, NAME=PIN_1, PART=PIN
*END INSTANCE
*SURFACE INTERACTION, NAME=INT-1
*CONTACT PAIR, INTERACTION=INT-1
HANDLE_SURF, BASE_SURF
*END ASSEMBLY
*BOUNDARY
BASE_1.HOLE_SET, ENCASTRE
*STEP
*STATIC
*END STEP
"""

MISSING_BASE_INP = """
*HEADING
Degraded single part handle
*PART, NAME=HANDLE
*NODE
1, 0.0, 0.0, 0.0
*ELEMENT, TYPE=C3D10M, ELSET=HANDLE_ELEMS
1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=HANDLE_1, PART=HANDLE
*END INSTANCE
*END ASSEMBLY
*STEP
*STATIC
*END STEP
"""

EMPTY_BASE_INP = """
*HEADING
Assembly with empty base mesh
*PART, NAME=HANDLE
*NODE
1, 0.0, 0.0, 0.0
*ELEMENT, TYPE=C3D10M, ELSET=HANDLE_ELEMS
1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*END PART
*PART, NAME=BASE
** Note: no *ELEMENT block inside Base part!
*NODE
100, 0.0, 0.0, 0.0
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=HANDLE_1, PART=HANDLE
*END INSTANCE
*INSTANCE, NAME=BASE_1, PART=BASE
*END INSTANCE
*CONTACT PAIR
HANDLE_SURF, BASE_SURF
*END ASSEMBLY
"""

OVERCONSTRAINED_ACTUATOR_INP = """
*HEADING
Handle completely locked with ENCASTRE
*PART, NAME=HANDLE
*ELEMENT, TYPE=C3D10M, ELSET=E1
1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*END PART
*PART, NAME=BASE
*ELEMENT, TYPE=C3D10M, ELSET=E2
100, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=HANDLE_1, PART=HANDLE
*END INSTANCE
*INSTANCE, NAME=BASE_1, PART=BASE
*END INSTANCE
*CONTACT PAIR
HANDLE_SURF, BASE_SURF
*BOUNDARY
HANDLE_1.ALL_NODES, ENCASTRE
BASE_1.HOLE_SET, ENCASTRE
*END ASSEMBLY
"""


def test_parse_inp_parts_and_instances():
    parts_elem, inst_to_part, root_elem = parse_inp_parts_and_instances(LEGAL_MULTIPART_INP)
    assert parts_elem["handle"] is True
    assert parts_elem["base"] is True
    assert parts_elem["pin"] is True
    assert inst_to_part["handle1"] == "handle"
    assert inst_to_part["base1"] == "base"
    assert inst_to_part["pin1"] == "pin"


def test_single_part_audit_passes():
    res = audit_inp_assembly_contract(LEGAL_SINGLE_PART_INP, assembly_scope=None)
    assert res.passed is True


def test_multipart_contract_passes():
    scope = {
        "parts": [
            {"instance_name": "HANDLE_1"},
            {"instance_name": "BASE_1"},
            {"instance_name": "PIN_1"},
        ],
        "contacts": [{"master": "HANDLE_1", "slave": "BASE_1"}],
    }
    res = audit_inp_assembly_contract(LEGAL_MULTIPART_INP, assembly_scope=scope)
    assert res.passed is True
    assert len(res.diagnostics["found_instances"]) == 3


def test_missing_retained_part_fails_audit():
    scope = {
        "parts": [
            {"instance_name": "HANDLE_1"},
            {"instance_name": "BASE_1"},
        ],
        "contacts": [{"master": "HANDLE_1", "slave": "BASE_1"}],
    }
    # MISSING_BASE_INP only has HANDLE_1
    res = audit_inp_assembly_contract(MISSING_BASE_INP, assembly_scope=scope)
    assert res.passed is False
    assert "BASE_1" in res.reason
    assert "Unilateral degradation to single-part is prohibited" in res.reason


def test_empty_mesh_fails_audit():
    scope = {
        "parts": [
            {"instance_name": "HANDLE_1"},
            {"instance_name": "BASE_1"},
        ],
        "contacts": [{"master": "HANDLE_1", "slave": "BASE_1"}],
    }
    res = audit_inp_assembly_contract(EMPTY_BASE_INP, assembly_scope=scope)
    assert res.passed is False
    assert "BASE_1" in res.reason
    assert "without valid *ELEMENT definitions" in res.reason


def test_overconstrained_actuator_fails_audit():
    scope = {
        "parts": [
            {"instance_name": "HANDLE_1"},
            {"instance_name": "BASE_1"},
        ],
        "contacts": [{"master": "HANDLE_1", "slave": "BASE_1"}],
    }
    res = audit_inp_assembly_contract(
        OVERCONSTRAINED_ACTUATOR_INP,
        assembly_scope=scope,
        loaded_instances=["HANDLE_1"],
    )
    assert res.passed is False
    assert "Actuator instance 'handle1' is completely locked with ENCASTRE" in res.reason


def test_instance_matching_rejects_loose_substring():
    """Verify that 'HANDLE_1' does NOT falsely match 'HANDLE_BASE_1'."""
    inp_with_similar_name = """
*HEADING
Model with similar instance name
*PART, NAME=HANDLE_BASE
*ELEMENT, TYPE=C3D10M, ELSET=E1
1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=HANDLE_BASE_1, PART=HANDLE_BASE
*END INSTANCE
*END ASSEMBLY
*STEP
*STATIC
*END STEP
"""
    scope = {
        "parts": [
            {"instance_name": "HANDLE_1"},
            {"instance_name": "OTHER_1"},
        ],
    }
    res = audit_inp_assembly_contract(inp_with_similar_name, assembly_scope=scope)
    assert res.passed is False
    assert "required retained instance(s) ['HANDLE_1', 'OTHER_1'] are missing" in res.reason


def test_unrelated_contact_pair_fails_audit():
    """Verify that contact pairs referencing unrelated objects fail the multi-part contract."""
    inp_with_unrelated_contacts = """
*HEADING
Model with unrelated contact pairs
*PART, NAME=HANDLE
*ELEMENT, TYPE=C3D10M, ELSET=E1
1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*END PART
*PART, NAME=BASE
*ELEMENT, TYPE=C3D10M, ELSET=E2
100, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=HANDLE_1, PART=HANDLE
*END INSTANCE
*INSTANCE, NAME=BASE_1, PART=BASE
*END INSTANCE
*CONTACT PAIR
FIXTURE_SURF, GROUND_SURF
*END ASSEMBLY
"""
    scope = {
        "parts": [
            {"instance_name": "HANDLE_1"},
            {"instance_name": "BASE_1"},
        ],
        "contacts": [{"master": "HANDLE_1", "slave": "BASE_1"}],
    }
    res = audit_inp_assembly_contract(inp_with_unrelated_contacts, assembly_scope=scope)
    assert res.passed is False
    assert "required load transfer between 'HANDLE_1' and 'BASE_1' is not defined" in res.reason


def test_single_part_overconstrained_actuator_fails_audit():
    """Verify single-part contract does not early-return and skip actuator boundary checks."""
    inp_single_part_locked = """
*HEADING
Single part cantilever with encastre
*PART, NAME=BEAM
*ELEMENT, TYPE=C3D8R, ELSET=BEAM_ELEMS
1, 1, 2, 3, 4, 5, 6, 7, 8
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=BEAM_1, PART=BEAM
*END INSTANCE
*END ASSEMBLY
*BOUNDARY
BEAM_1.ALL_NODES, ENCASTRE
*STEP
*STATIC
*END STEP
"""
    scope = {
        "parts": [
            {"instance_name": "BEAM_1"},
        ]
    }
    res = audit_inp_assembly_contract(
        inp_single_part_locked,
        assembly_scope=scope,
        loaded_instances=["BEAM_1"],
    )
    assert res.passed is False
    assert "Assembly boundary condition violation" in res.reason
    assert "Actuator instance 'beam1' is completely locked with ENCASTRE" in res.reason


def test_unparsed_contact_fails_closed():
    """Verify that multi-part contract fails closed if contact lines cannot be parsed."""
    inp_keyword_only = """
*HEADING
Model with keyword only and no parsable pairs
*PART, NAME=HANDLE
*ELEMENT, TYPE=C3D10M, ELSET=E1
1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*END PART
*PART, NAME=BASE
*ELEMENT, TYPE=C3D10M, ELSET=E2
100, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=HANDLE_1, PART=HANDLE
*END INSTANCE
*INSTANCE, NAME=BASE_1, PART=BASE
*END INSTANCE
*SURFACE INTERACTION, NAME=INT-1
*END ASSEMBLY
*STEP
*STATIC
*END STEP
"""
    scope = {
        "parts": [
            {"instance_name": "HANDLE_1"},
            {"instance_name": "BASE_1"},
        ],
        "contacts": [{"master": "HANDLE_1", "slave": "BASE_1"}],
    }
    res = audit_inp_assembly_contract(inp_keyword_only, assembly_scope=scope)
    assert res.passed is False
    assert "no parsable *CONTACT PAIR or *TIE interaction data lines were found" in res.reason


def test_contact_matching_rejects_substring_instance_in_surface_name():
    """Verify that candidate 'HANDLE_BASE_SURF' does NOT match instance 'HANDLE_1' via substring."""
    inp_loose_contact = """
*HEADING
Model with contact referencing another part's surface
*PART, NAME=HANDLE
*ELEMENT, TYPE=C3D10M, ELSET=E1
1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*END PART
*PART, NAME=BASE
*ELEMENT, TYPE=C3D10M, ELSET=E2
100, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*END PART
*PART, NAME=OTHER
*ELEMENT, TYPE=C3D10M, ELSET=E3
200, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*SURFACE, NAME=HANDLE_BASE_SURF, TYPE=ELEMENT
E3
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=HANDLE_1, PART=HANDLE
*END INSTANCE
*INSTANCE, NAME=BASE_1, PART=BASE
*END INSTANCE
*INSTANCE, NAME=OTHER_1, PART=OTHER
*END INSTANCE
*CONTACT PAIR
HANDLE_BASE_SURF, BASE_1.BASE_SURF
*END ASSEMBLY
*STEP
*STATIC
*END STEP
"""
    scope = {
        "parts": [
            {"instance_name": "HANDLE_1"},
            {"instance_name": "BASE_1"},
        ],
        "contacts": [{"master": "HANDLE_1", "slave": "BASE_1"}],
    }
    res = audit_inp_assembly_contract(inp_loose_contact, assembly_scope=scope)
    assert res.passed is False
    assert "required load transfer between 'HANDLE_1' and 'BASE_1' is not defined" in res.reason


def test_single_part_contract_missing_declared_instance_fails_audit():
    """Verify single-part contract fails if the declared instance is missing from the INP deck."""
    scope = {
        "parts": [
            {"instance_name": "HANDLE_1"},
        ]
    }
    # LEGAL_SINGLE_PART_INP contains CANTILEVER-1, NOT HANDLE_1
    res = audit_inp_assembly_contract(LEGAL_SINGLE_PART_INP, assembly_scope=scope)
    assert res.passed is False
    assert "HANDLE_1" in res.reason
    assert "missing from the solver deck" in res.reason


def test_single_part_contract_empty_mesh_fails_audit():
    """Verify single-part contract fails if the declared instance has an empty mesh."""
    inp_single_part_empty_mesh = """
*HEADING
Single part with empty mesh
*PART, NAME=DUMMY
*ELEMENT, TYPE=C3D8R, ELSET=ALLELEMS
1, 1, 2, 3, 4, 5, 6, 7, 8
*END PART
*PART, NAME=HANDLE
*NODE
1, 0.0, 0.0, 0.0
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=HANDLE_1, PART=HANDLE
*END INSTANCE
*END ASSEMBLY
*STEP
*STATIC
*END STEP
"""
    scope = {
        "parts": [
            {"instance_name": "HANDLE_1"},
        ]
    }
    res = audit_inp_assembly_contract(inp_single_part_empty_mesh, assembly_scope=scope)
    assert res.passed is False
    assert "HANDLE_1" in res.reason
    assert "reference parts without valid *ELEMENT definitions" in res.reason


def test_single_part_contract_valid_passes():
    """Verify single-part contract passes when declared instance exists and has mesh elements."""
    scope = {
        "parts": [
            {"instance_name": "CANTILEVER-1"},
        ]
    }
    res = audit_inp_assembly_contract(LEGAL_SINGLE_PART_INP, assembly_scope=scope)
    assert res.passed is True
    assert res.diagnostics["mode"] == "single_part"
    assert "cantilever-1" in res.diagnostics["found_instances"]

