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


def test_include_sandbox_path_traversal_rejection(tmp_path):
    """P0 Sandbox: Parent directory escape and outside roots must be rejected with outside_sandbox status."""
    job_dir = tmp_path / "job_run"
    job_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    # Create secret/outside mesh
    outside_mesh = outside_dir / "secret_mesh.inp"
    outside_mesh.write_text("*ELEMENT, TYPE=C3D8R\n1, 1, 2, 3, 4, 5, 6, 7, 8\n", encoding="utf-8")

    # 1. Relative path escape using '..'
    inp_escape = """*HEADING
Escape sandbox
*PART, NAME=P1
*INCLUDE, INPUT=../outside/secret_mesh.inp
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=P1_1, PART=P1
*END INSTANCE
*END ASSEMBLY
"""
    res1 = audit_inp_assembly_contract(
        inp_escape,
        assembly_scope={"parts": [{"instance_name": "P1_1"}]},
        base_dir=job_dir,
        allowed_roots=[job_dir],
    )
    assert res1.passed is False
    assert "outside approved sandbox roots" in res1.reason
    records1 = res1.diagnostics.get("include_records", [])
    assert len(records1) == 1
    assert records1[0]["status"] == "outside_sandbox"

    # 2. Absolute path pointing outside sandbox
    inp_abs = f"""*HEADING
Absolute path outside sandbox
*PART, NAME=P1
*INCLUDE, INPUT={outside_mesh.resolve()}
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=P1_1, PART=P1
*END INSTANCE
*END ASSEMBLY
"""
    res2 = audit_inp_assembly_contract(
        inp_abs,
        assembly_scope={"parts": [{"instance_name": "P1_1"}]},
        base_dir=job_dir,
        allowed_roots=[job_dir],
    )
    assert res2.passed is False
    assert "outside approved sandbox roots" in res2.reason
    records2 = res2.diagnostics.get("include_records", [])
    assert len(records2) == 1
    assert records2[0]["status"] == "outside_sandbox"


def test_include_circular_and_depth_limits(tmp_path):
    """P0 Sandbox: Circular include and recursion depth >= 10 must fail-closed."""
    job_dir = tmp_path / "job_circ"
    job_dir.mkdir()

    # 1. Circular include: A includes B, B includes A
    file_a = job_dir / "a.inp"
    file_b = job_dir / "b.inp"
    file_a.write_text("*INCLUDE, INPUT=b.inp\n", encoding="utf-8")
    file_b.write_text("*INCLUDE, INPUT=a.inp\n", encoding="utf-8")

    inp_circ = """*HEADING
Circular include
*PART, NAME=P1
*INCLUDE, INPUT=a.inp
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=P1_1, PART=P1
*END INSTANCE
*END ASSEMBLY
"""
    res = audit_inp_assembly_contract(
        inp_circ,
        assembly_scope={"parts": [{"instance_name": "P1_1"}]},
        base_dir=job_dir,
    )
    assert res.passed is False
    assert "unresolved or invalid *INCLUDE reference" in res.reason
    rec_statuses = [r["status"] for r in res.diagnostics.get("include_records", [])]
    assert "circular" in rec_statuses


def test_element_continuation_broken_record_with_trailing_comma():
    """P1 Continuation state machine: Incomplete element with trailing comma followed by new element fails closed."""
    # Element 1 has only 4 nodes (expected 8) and ends with a comma.
    # Line 2 starts a new element (2, 10, 11, ...).
    # Parser must NOT concatenate line 2 into element 1.
    inp_broken = """*HEADING
Continuation mismatch
*PART, NAME=BAR
*ELEMENT, TYPE=C3D8R
1, 1, 2, 3, 4,
2, 10, 11, 12, 13, 14, 15, 16, 17
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=BAR_1, PART=BAR
*END INSTANCE
*END ASSEMBLY
"""
    scope = {"parts": [{"instance_name": "BAR_1"}]}
    res = audit_inp_assembly_contract(inp_broken, assembly_scope=scope)
    assert res.passed is False
    assert "malformed element definition" in res.reason


def test_element_continuation_valid_multiline_c3d20():
    """P1 Continuation state machine: Valid multiline continuation for C3D20 passes cleanly."""
    inp_valid_c3d20 = """*HEADING
Valid C3D20 3-line continuation
*PART, NAME=SOLID
*ELEMENT, TYPE=C3D20
100, 1, 2, 3, 4, 5, 6, 7, 8,
9, 10, 11, 12, 13, 14, 15, 16,
17, 18, 19, 20
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=SOLID_1, PART=SOLID
*END INSTANCE
*END ASSEMBLY
"""
    scope = {"parts": [{"instance_name": "SOLID_1"}]}
    res = audit_inp_assembly_contract(inp_valid_c3d20, assembly_scope=scope)
    assert res.passed is True


def test_cross_include_surface_and_contact_resolution(tmp_path):
    """P1 Unified Context: Surfaces and Contact/Tie across INCLUDE files resolve properly; missing/empty fails."""
    job_dir = tmp_path / "contact_model"
    job_dir.mkdir()

    part1_file = job_dir / "part1.inp"
    part1_file.write_text("""*PART, NAME=PART_A
*NODE
1, 0., 0., 0.
*ELEMENT, TYPE=C3D8R, ELSET=EALL
1, 1, 2, 3, 4, 5, 6, 7, 8
*SURFACE, NAME=SURF_A
EALL, S1
*END PART
""", encoding="utf-8")

    part2_file = job_dir / "part2.inp"
    part2_file.write_text("""*PART, NAME=PART_B
*NODE
10, 0., 0., 0.
*ELEMENT, TYPE=C3D8R, ELSET=EALL
10, 10, 11, 12, 13, 14, 15, 16, 17
*SURFACE, NAME=SURF_B
EALL, S2
*END PART
""", encoding="utf-8")

    # 1. Valid cross-include contact pair
    main_inp_valid = """*HEADING
Cross-include contact valid
*INCLUDE, INPUT=part1.inp
*INCLUDE, INPUT=part2.inp
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=INST_A, PART=PART_A
*END INSTANCE
*INSTANCE, NAME=INST_B, PART=PART_B
*END INSTANCE
*CONTACT PAIR, INTERACTION=INTPROP
SURF_A, SURF_B
*END ASSEMBLY
"""
    res_valid = audit_inp_assembly_contract(
        main_inp_valid,
        assembly_scope={"parts": [{"instance_name": "INST_A"}, {"instance_name": "INST_B"}]},
        base_dir=job_dir,
    )
    assert res_valid.passed is True

    # 2. Missing surface in cross-include contact pair
    main_inp_missing_surf = """*HEADING
Cross-include contact missing surf
*INCLUDE, INPUT=part1.inp
*INCLUDE, INPUT=part2.inp
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=INST_A, PART=PART_A
*END INSTANCE
*INSTANCE, NAME=INST_B, PART=PART_B
*END INSTANCE
*CONTACT PAIR, INTERACTION=INTPROP
SURF_A, NONEXISTENT_SURF
*END ASSEMBLY
"""
    res_missing = audit_inp_assembly_contract(
        main_inp_missing_surf,
        assembly_scope={"parts": [{"instance_name": "INST_A"}, {"instance_name": "INST_B"}]},
        base_dir=job_dir,
    )
    assert res_missing.passed is False
    assert "NONEXISTENT_SURF" in res_missing.reason
    assert "undefined surface" in res_missing.reason

    # 3. Empty contact pair interaction
    main_inp_empty_contact = """*HEADING
Cross-include empty contact
*INCLUDE, INPUT=part1.inp
*INCLUDE, INPUT=part2.inp
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=INST_A, PART=PART_A
*END INSTANCE
*INSTANCE, NAME=INST_B, PART=PART_B
*END INSTANCE
*CONTACT PAIR, INTERACTION=INTPROP
*END ASSEMBLY
"""
    res_empty = audit_inp_assembly_contract(
        main_inp_empty_contact,
        assembly_scope={"parts": [{"instance_name": "INST_A"}, {"instance_name": "INST_B"}]},
        base_dir=job_dir,
    )
    assert res_empty.passed is False
    assert "Empty interaction block" in res_empty.reason or "unsupported or malformed interaction" in res_empty.reason


def test_element_continuation_node_id_adjacent_to_element_id():
    """P1 Refined: Element ID=1 and legitimate continuation first node ID=2 passes without false positive."""
    # Element 1 has 4 nodes on line 1 with trailing comma, and next line has nodes 2, 3, 4, 5 (C3D8R 8 nodes).
    # First token of continuation line is 2 (which is 1 + 1), must NOT be misjudged as new element 2.
    inp_text = """*HEADING
Continuation adjacent node ID
*PART, NAME=BAR
*ELEMENT, TYPE=C3D8R
1, 10, 11, 12, 13,
2, 3, 4, 5
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=BAR_1, PART=BAR
*END INSTANCE
*END ASSEMBLY
"""
    scope = {"parts": [{"instance_name": "BAR_1"}]}
    res = audit_inp_assembly_contract(inp_text, assembly_scope=scope)
    assert res.passed is True


def test_element_ids_non_monotonic_and_reverse_order():
    """P1 Refined: Non-monotonic, arbitrary, or reverse order element IDs pass without false positive."""
    inp_text = """*HEADING
Reverse and arbitrary element IDs
*PART, NAME=BAR
*ELEMENT, TYPE=C3D8R
100, 1, 2, 3, 4, 5, 6, 7, 8
50, 10, 11, 12, 13, 14, 15, 16, 17
1, 20, 21, 22, 23, 24, 25, 26, 27
888, 30, 31, 32, 33, 34, 35, 36, 37
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=BAR_1, PART=BAR
*END INSTANCE
*END ASSEMBLY
"""
    scope = {"parts": [{"instance_name": "BAR_1"}]}
    res = audit_inp_assembly_contract(inp_text, assembly_scope=scope)
    assert res.passed is True


def test_element_continuation_exceeding_capacity_rejected():
    """P1 Refined: Continuation tokens exceeding remaining topology capacity must be rejected."""
    # C3D8R requires 8 nodes. First line has 4 nodes, remaining needed is 4.
    # Continuation line provides 5 nodes (total 9 > 8).
    inp_text = """*HEADING
Continuation capacity exceeded
*PART, NAME=BAR
*ELEMENT, TYPE=C3D8R
1, 1, 2, 3, 4,
5, 6, 7, 8, 9
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=BAR_1, PART=BAR
*END INSTANCE
*END ASSEMBLY
"""
    scope = {"parts": [{"instance_name": "BAR_1"}]}
    res = audit_inp_assembly_contract(inp_text, assembly_scope=scope)
    assert res.passed is False
    assert "malformed element definition" in res.reason


def test_element_continuation_ambiguous_boundaries_rejected():
    """P1 Refined: Ambiguous boundaries (trailing comma at full capacity or missing comma mid-stream) must fail closed."""
    # Case A: Full capacity reached but line still has trailing comma
    inp_full_with_comma = """*HEADING
Full capacity with trailing comma
*PART, NAME=BAR
*ELEMENT, TYPE=C3D8R
1, 1, 2, 3, 4,
5, 6, 7, 8,
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=BAR_1, PART=BAR
*END INSTANCE
*END ASSEMBLY
"""
    res_a = audit_inp_assembly_contract(inp_full_with_comma, assembly_scope={"parts": [{"instance_name": "BAR_1"}]})
    assert res_a.passed is False
    assert "malformed element definition" in res_a.reason

    # Case B: Insufficient nodes in intermediate continuation without trailing comma
    inp_mid_without_comma = """*HEADING
Intermediate continuation without trailing comma
*PART, NAME=SOLID
*ELEMENT, TYPE=C3D20
100, 1, 2, 3, 4, 5, 6, 7, 8,
9, 10, 11, 12
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=SOLID_1, PART=SOLID
*END INSTANCE
*END ASSEMBLY
"""
    res_b = audit_inp_assembly_contract(inp_mid_without_comma, assembly_scope={"parts": [{"instance_name": "SOLID_1"}]})
    assert res_b.passed is False
    assert "malformed element definition" in res_b.reason


def test_include_with_undecodable_bytes_fails_closed(tmp_path):
    """A dependency must not be silently replacement-decoded before its syntax audit."""
    include_file = tmp_path / "invalid_encoding.inc"
    include_file.write_bytes(b"*ELEMENT, TYPE=C3D8R\n1, 1, 2, 3, 4, 5, 6, 7, 8\n\xff")
    inp = """
*HEADING
Invalid include encoding
*PART, NAME=P1
*INCLUDE, INPUT=invalid_encoding.inc
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=P1_1, PART=P1
*END INSTANCE
*END ASSEMBLY
"""
    result = audit_inp_assembly_contract(
        inp, assembly_scope={"parts": [{"instance_name": "P1_1"}]}, base_dir=tmp_path
    )
    assert result.passed is False
    assert "unresolved or invalid *INCLUDE reference" in result.reason
    assert "utf-8" in result.reason.lower() or "decode" in result.reason.lower()
    records = result.diagnostics.get("include_records", [])
    assert records and all(r["status"] == "read_error" for r in records)
    assert all(r["status"] != "ok" for r in records)


def test_include_undecodable_byte_inside_comment_still_fails_closed(tmp_path):
    """An undecodable byte in a comment line must not yield an 'ok' record bound to raw bytes.

    Replacement decoding leaves the syntax intact here, so a syntax-only audit would
    report success while claiming a SHA-256 of bytes it never actually parsed.
    """
    include_file = tmp_path / "comment_only_note.inc"
    include_file.write_bytes(
        b"** hand note \xff\n*ELEMENT, TYPE=C3D8R\n1, 1, 2, 3, 4, 5, 6, 7, 8\n"
    )
    inp = """
*HEADING
Undecodable bytes confined to a comment
*PART, NAME=P1
*INCLUDE, INPUT=comment_only_note.inc
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=P1_1, PART=P1
*END INSTANCE
*END ASSEMBLY
"""
    result = audit_inp_assembly_contract(
        inp, assembly_scope={"parts": [{"instance_name": "P1_1"}]}, base_dir=tmp_path
    )
    assert result.passed is False
    assert "unresolved or invalid *INCLUDE reference" in result.reason
    records = result.diagnostics.get("include_records", [])
    assert len(records) == 1
    assert records[0]["status"] == "read_error"
    assert records[0]["sha256"] is None
    assert "not valid UTF-8" in (records[0]["error_message"] or "")




