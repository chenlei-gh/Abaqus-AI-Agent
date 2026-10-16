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
*SURFACE, NAME=BASE_SURF, TYPE=ELEMENT
E2
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
    assert (
        "no parsable *CONTACT PAIR or *TIE interaction data lines were found" in res.reason
        or "multi-part contract requires load-transfer contact pairs" in res.reason
    )


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
*SURFACE, NAME=BASE_SURF, TYPE=ELEMENT
E2
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


def test_element_keyword_without_data_lines_fails_audit():
    """Verify that *ELEMENT keyword without valid data lines fails audit closed."""
    inp_kw_no_data = """
*HEADING
Model with empty ELEMENT keyword
*PART, NAME=HANDLE
*NODE
1, 0.0, 0.0, 0.0
*ELEMENT, TYPE=C3D10M, ELSET=ALLELEMS
*SURFACE, NAME=HANDLE_SURF
ALLELEMS, S1
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
    res = audit_inp_assembly_contract(inp_kw_no_data, assembly_scope=scope)
    assert res.passed is False
    assert "no valid *ELEMENT definitions" in res.reason


def test_root_elements_cannot_mask_unmeshed_part():
    """Verify that root-level elements do not mask a declared part that lacks its own mesh."""
    inp_root_masking = """
*HEADING
Model with root elements and unmeshed declared part
*ELEMENT, TYPE=C3D8R, ELSET=ROOTELEMS
999, 1, 2, 3, 4, 5, 6, 7, 8
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
    res = audit_inp_assembly_contract(inp_root_masking, assembly_scope=scope)
    assert res.passed is False
    assert "HANDLE_1" in res.reason
    assert "reference parts without valid *ELEMENT definitions" in res.reason


def test_element_with_id_only_no_nodes_fails():
    """Boundary 2: Line with only an element ID and zero node connections must fail audit."""
    inp = """
*HEADING
Single element ID without nodes
*PART, NAME=BAR
*ELEMENT, TYPE=C3D8R
101
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=BAR_1, PART=BAR
*END INSTANCE
*END ASSEMBLY
"""
    scope = {"parts": [{"instance_name": "BAR_1"}]}
    res = audit_inp_assembly_contract(inp, assembly_scope=scope)
    assert res.passed is False
    assert "malformed element definition" in res.reason


def test_element_with_insufficient_nodes_fails():
    """Boundary 3: Element with fewer connected nodes than topology requires must fail."""
    inp = """
*HEADING
C3D8R requires 8 nodes, but only 4 are provided
*PART, NAME=BAR
*ELEMENT, TYPE=C3D8R
101, 1, 2, 3, 4
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=BAR_1, PART=BAR
*END INSTANCE
*END ASSEMBLY
"""
    scope = {"parts": [{"instance_name": "BAR_1"}]}
    res = audit_inp_assembly_contract(inp, assembly_scope=scope)
    assert res.passed is False
    assert "malformed element definition" in res.reason


def test_valid_element_definition_passes():
    """Boundary 4: Valid element definition strictly adhering to topology passes audit."""
    inp = """
*HEADING
Valid C3D8R definition
*PART, NAME=BAR
*ELEMENT, TYPE=C3D8R
101, 1, 2, 3, 4, 5, 6, 7, 8
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=BAR_1, PART=BAR
*END INSTANCE
*END ASSEMBLY
"""
    scope = {"parts": [{"instance_name": "BAR_1"}]}
    res = audit_inp_assembly_contract(inp, assembly_scope=scope)
    assert res.passed is True


def test_valid_multiline_continuation_passes():
    """Boundary 5: Valid element definition spanning across multiline continuation passes audit."""
    inp = """
*HEADING
C3D10M requires 10 nodes, given across two lines
*PART, NAME=TETRA
*ELEMENT, TYPE=C3D10M
201, 1, 2, 3, 4, 5, 6, 7,
8, 9, 10
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=TETRA_1, PART=TETRA
*END INSTANCE
*END ASSEMBLY
"""
    scope = {"parts": [{"instance_name": "TETRA_1"}]}
    res = audit_inp_assembly_contract(inp, assembly_scope=scope)
    assert res.passed is True


def test_element_output_keyword_not_misidentified_as_mesh():
    """Boundary 6: *ELEMENT OUTPUT keyword must NOT be misidentified as mesh element definitions."""
    inp = """
*HEADING
Deck with *ELEMENT OUTPUT but zero *ELEMENT definitions
*PART, NAME=BAR
*ELEMENT OUTPUT
1, 2, 3, 4, 5, 6, 7, 8
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=BAR_1, PART=BAR
*END INSTANCE
*END ASSEMBLY
"""
    scope = {"parts": [{"instance_name": "BAR_1"}]}
    res = audit_inp_assembly_contract(inp, assembly_scope=scope)
    assert res.passed is False
    assert "INP contains no valid *ELEMENT definitions" in res.reason


def test_unsupported_or_unknown_element_type_fails_closed():
    """Boundary 7: Unsupported/unknown element type fails closed and cannot silently pass."""
    inp = """
*HEADING
Unknown element type must fail-closed
*PART, NAME=BAR
*ELEMENT, TYPE=NONEXISTENT_MAGIC_ELEM
1, 1, 2, 3, 4, 5, 6, 7, 8
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=BAR_1, PART=BAR
*END INSTANCE
*END ASSEMBLY
"""
    scope = {"parts": [{"instance_name": "BAR_1"}]}
    res = audit_inp_assembly_contract(inp, assembly_scope=scope)
    assert res.passed is False
    assert "unsupported or unknown element type" in res.reason


def test_supported_element_types_comprehensive_matrix():
    """Boundary 9: Matrix of standard Abaqus element types supported by project pass topology audit."""
    types_and_nodes = [
        ("C3D8R", 8),
        ("C3D4", 4),
        ("C3D10M", 10),
        ("S4R", 4),
        ("S3", 3),
        ("B31", 2),
        ("CPE4", 4),
        ("MASS", 1),
        ("GK3D8", 8),
    ]
    for elem_type, node_count in types_and_nodes:
        node_ids = ", ".join(str(i + 1) for i in range(node_count))
        inp = f"""
*HEADING
Validation for {elem_type}
*PART, NAME=P1
*ELEMENT, TYPE={elem_type}
1, {node_ids}
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=P1_1, PART=P1
*END INSTANCE
*END ASSEMBLY
"""
        res = audit_inp_assembly_contract(inp, assembly_scope={"parts": [{"instance_name": "P1_1"}]})
        assert res.passed is True, f"Failed for supported type {elem_type}"


def test_external_include_element_fail_closed_and_resolution(tmp_path):
    """External *INCLUDE: unresolved external include fails closed; resolved valid include passes."""
    # 1. Missing / unresolvable include file fails closed
    inp_unresolved = """
*HEADING
Deck referencing missing external file
*PART, NAME=P1
*INCLUDE, INPUT=missing_mesh.inp
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=P1_1, PART=P1
*END INSTANCE
*END ASSEMBLY
"""
    res = audit_inp_assembly_contract(inp_unresolved, assembly_scope={"parts": [{"instance_name": "P1_1"}]}, base_dir=tmp_path)
    assert res.passed is False
    assert "unresolved or invalid *INCLUDE reference" in res.reason

    # 2. Existing include file with valid topology passes
    include_file = tmp_path / "valid_mesh.inp"
    include_file.write_text("*ELEMENT, TYPE=C3D8R\n1, 1, 2, 3, 4, 5, 6, 7, 8\n", encoding="utf-8")
    inp_resolved = f"""
*HEADING
Deck referencing existing valid external file
*PART, NAME=P1
*INCLUDE, INPUT=valid_mesh.inp
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=P1_1, PART=P1
*END INSTANCE
*END ASSEMBLY
"""
    res2 = audit_inp_assembly_contract(inp_resolved, assembly_scope={"parts": [{"instance_name": "P1_1"}]}, base_dir=tmp_path)
    assert res2.passed is True


def test_include_path_escape_outside_allowed_root_fails_closed(tmp_path):
    """An INCLUDE resolved outside the initial deck directory is rejected."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside = tmp_path / "outside_mesh.inp"
    outside.write_text("*ELEMENT, TYPE=C3D8R\n1, 1, 2, 3, 4, 5, 6, 7, 8\n", encoding="utf-8")
    inp = """
*HEADING
Path escape probe
*PART, NAME=P1
*INCLUDE, INPUT=../outside_mesh.inp
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=P1_1, PART=P1
*END INSTANCE
*END ASSEMBLY
"""
    result = audit_inp_assembly_contract(
        inp, assembly_scope={"parts": [{"instance_name": "P1_1"}]}, base_dir=sandbox
    )
    assert result.passed is False
    assert "escapes allowed roots" in result.reason


def test_malformed_element_cannot_be_completed_by_overlong_next_record():
    """A next line shaped like a new element must not be concatenated past topology size."""
    inp = """
*HEADING
Broken continuation followed by a full new record
*PART, NAME=BAR
*ELEMENT, TYPE=C3D8R
101, 1, 2, 3, 4,
102, 5, 6, 7, 8, 9, 10, 11, 12
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=BAR_1, PART=BAR
*END INSTANCE
*END ASSEMBLY
"""
    result = audit_inp_assembly_contract(inp, assembly_scope={"parts": [{"instance_name": "BAR_1"}]})
    assert result.passed is False
    assert "malformed element definition" in result.reason


def test_contact_pair_and_surfaces_inside_include_are_resolved(tmp_path):
    """Interaction and Surface definitions in nested include content join the full parse context."""
    include_file = tmp_path / "assembly_contact.inc"
    include_file.write_text(
        """*PART, NAME=BASE
*ELEMENT, TYPE=C3D8R
2, 1, 2, 3, 4, 5, 6, 7, 8
*SURFACE, NAME=BASE_SURF
2, S1
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=BASE_1, PART=BASE
*END INSTANCE
*CONTACT PAIR, INTERACTION=INT-1
HANDLE_1.HANDLE_SURF, BASE_1.BASE_SURF
*END ASSEMBLY
""",
        encoding="utf-8",
    )
    inp = """
*HEADING
Top-level handle and included base/contact
*PART, NAME=HANDLE
*ELEMENT, TYPE=C3D8R
1, 1, 2, 3, 4, 5, 6, 7, 8
*SURFACE, NAME=HANDLE_SURF
1, S1
*END PART
*INCLUDE, INPUT=assembly_contact.inc
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=HANDLE_1, PART=HANDLE
*END INSTANCE
*END ASSEMBLY
"""
    scope = {
        "parts": [{"instance_name": "HANDLE_1"}, {"instance_name": "BASE_1"}],
        "contacts": [{"master": "HANDLE_1", "slave": "BASE_1",
                      "master_surface": "HANDLE_SURF", "slave_surface": "BASE_SURF"}],
    }
    result = audit_inp_assembly_contract(inp, assembly_scope=scope, base_dir=tmp_path)
    assert result.passed is True, result.reason
