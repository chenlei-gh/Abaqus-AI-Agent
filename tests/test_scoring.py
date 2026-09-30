from abaqus_ai_agent.grounding.scoring import weighted_score


def test_weighted_score():
    assert weighted_score(1.0, 0.5, 0.0) == 0.6


def test_rejects_invalid_score():
    try:
        weighted_score(1.2, 0.5, 0.0)
    except ValueError:
        return
    assert False, "expected ValueError"
