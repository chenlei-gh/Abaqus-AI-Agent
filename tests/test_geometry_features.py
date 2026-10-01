from abaqus_ai_agent.contracts.geometry_features import characterize_geometry, GeometryFeature


def test_geometry_characterization_does_not_guess_feature_type():
    features = characterize_geometry({
        "edges": [{"index": 2, "size": 2.0}],
        "faces": [{"index": 4, "size": 20.0}],
    })
    assert len(features) == 2
    assert all(feature.feature_kind == "unknown" for feature in features)
    assert features[0].size == 2.0


def test_geometry_characterization_preserves_explicit_engineering_relevance():
    features = characterize_geometry(
        {"edges": [{"index": 2, "size": 5.0}]},
        critical_regions=(
            {"target": "Edge[2]", "priority": "critical", "reason": "load_introduction"},
        ),
    )
    assert features[0].relevance == "critical"
    assert features[0].confidence == 1.0
    assert features[0].evidence[-1].source == "engineering_region"
