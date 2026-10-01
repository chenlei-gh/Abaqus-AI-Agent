import pytest

from abaqus_ai_agent.contracts.mesh import LocalSeed, MeshSpecification


def test_mesh_specification_accepts_valid_bias_and_sweep_entries():
    spec = MeshSpecification(
        "P",
        1.0,
        bias_seeds=({
            "region_expression": "p.edges",
            "min_size": 0.25,
            "max_size": 1.0,
            "end": "END2",
            "constraint": "FREE",
        },),
        sweep_paths=({
            "region_expression": "p.cells",
            "edge_expression": "p.edges[0]",
            "sense": "REVERSE",
        },),
    )
    assert spec.part == "P"


def test_bias_seed_contract_rejects_invalid_range():
    with pytest.raises(ValueError, match="max_size must be >= min_size"):
        MeshSpecification(
            "P", 1.0,
            bias_seeds=({
                "region_expression": "p.edges",
                "min_size": 2.0,
                "max_size": 1.0,
            },),
        )


def test_sweep_path_contract_requires_edge_expression():
    with pytest.raises(ValueError, match="edge_expression"):
        MeshSpecification(
            "P", 1.0,
            sweep_paths=({"region_expression": "p.cells"},),
        )


def test_local_seed_rejects_nonfinite_size():
    with pytest.raises(ValueError, match="finite"):
        LocalSeed("p.edges", size=float("nan"))
