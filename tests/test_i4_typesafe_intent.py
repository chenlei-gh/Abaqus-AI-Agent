"""Tests for Phase I.4 JEV-Powered Product UX & TypeSafe Intent Routing."""

from __future__ import annotations

from pathlib import Path
import pytest

from abaqus_ai_agent.typesafe_intent import (
    ChoiceJudgment,
    ExternalIntentApiError,
    GenericHttpIntentProvider,
    IntentAmbiguityError,
    JevDecisionBundle,
    JevIntentRouter,
    NoulJudgment,
    ScoreJudgment,
    TYPESAFE_SYSTEMONE_DEFAULT_URL,
    TYPESAFE_DEFAULT_MODEL,
)
from tools.i4_jev_intent_e2e import run_jev_intent_e2e

ROOT = Path(__file__).resolve().parent.parent


def test_jev_primitives_contracts():
    c = ChoiceJudgment(value="linear_static", confidence=0.98, distribution={"linear_static": 0.98})
    assert c.value == "linear_static"
    assert c.confidence == 0.98

    n1 = NoulJudgment(probability=0.85)
    assert n1.is_yes is True
    n2 = NoulJudgment(probability=0.25)
    assert n2.is_yes is False

    s = ScoreJudgment(score=4.5)
    assert s.score == 4.5


def test_jev_intent_router_static_prompt():
    router = JevIntentRouter()
    prompt = "对100mm悬臂梁端部施加1000N垂直载荷，材料为结构钢，固定根部，校核端部挠度不超过2.5mm和最大Mises应力不超过600MPa。"
    intent, bundle = router.route_prompt_to_intent(prompt)

    assert bundle.physics_choice.value == "linear_static"
    assert bundle.unit_system_choice.value == "MM_N_MPA"
    assert bundle.is_well_constrained_noul.is_yes is True
    assert bundle.completeness_score.score >= 4.0
    assert intent.material is not None
    assert intent.material["name"] == "Structural_Steel"
    assert len(intent.boundary_conditions) > 0
    assert len(intent.loads) > 0
    assert len(intent.acceptance_criteria) >= 2


def test_jev_intent_router_thermal_prompt():
    router = JevIntentRouter()
    prompt = "1D heat conduction bar with hot end at 100C and cold end at 0C. Check midpoint temperature."

    # Default strict=True must fail-closed on incomplete specification
    with pytest.raises(IntentAmbiguityError):
        router.route_prompt_to_intent(prompt)

    # Even explicit strict=False must fail-closed: executable intents are NEVER generated for ambiguous input
    with pytest.raises(IntentAmbiguityError):
        router.route_prompt_to_intent(prompt, strict=False)

    # Exploratory draft intent must be explicitly requested via create_draft_intent
    draft, bundle = router.create_draft_intent(prompt)
    assert draft.is_executable is False
    assert bundle.physics_choice.value == "steady_thermal"
    assert bundle.unit_system_choice.value == "MM_N_MPA"
    assert draft.analysis_type == "steady_thermal"


def test_jev_intent_e2e_runner(tmp_path: Path):
    out_file = tmp_path / "i4_jev_intent_evidence.json"
    manifest = run_jev_intent_e2e(out_file)

    assert manifest["schema_version"] == "jev_intent_routing_v1"
    assert manifest["total_prompts"] == 3
    assert manifest["passed_prompts"] == 3
    assert manifest["all_passed"] is True
    assert out_file.is_file()


def test_jev_intent_ambiguity_fails_closed():
    """Ambiguous prompts missing loads/materials/constraints must NOT silently pass."""
    router = JevIntentRouter()
    ambiguous_prompt = "帮我分析这个支架强度。"
    res = router.route(ambiguous_prompt)

    assert res.status == "NEEDS_CLARIFICATION"
    assert res.intent is None
    assert len(res.missing_requirements) >= 3
    assert "missing_geometry_dimensions" in res.missing_requirements
    assert "missing_material_specification" in res.missing_requirements
    assert "missing_applied_loads" in res.missing_requirements
    assert res.clarification_prompt is not None

    # Strict mode must raise explicit IntentAmbiguityError
    with pytest.raises(Exception) as excinfo:
        router.route_prompt_to_intent(ambiguous_prompt, strict=True)
    assert "Missing prerequisites" in str(excinfo.value)


def test_jev_intent_context_merge_unblocks_existing_model_evidence():
    """Verify that upstream model context (geometry, material, constraints) satisfies prerequisites without prompt duplication."""
    router = JevIntentRouter()
    # Prompt only specifies load and constraint, omitting dimensions and material
    prompt = "固定悬臂梁根部，端部施加1000N向下集中载荷。"

    # Without context -> fails closed due to missing dimensions & material
    res_no_ctx = router.route(prompt)
    assert res_no_ctx.status == "NEEDS_CLARIFICATION"
    assert "missing_geometry_dimensions" in res_no_ctx.missing_requirements
    assert "missing_material_specification" in res_no_ctx.missing_requirements

    # With model context -> prerequisites satisfied, successfully routes and merges context
    model_context = {
        "dimensions": [{"value": 200.0, "unit": "mm"}],
        "material": {
            "name": "Aluminum_6061",
            "elastic_modulus": 70000.0,
            "poisson_ratio": 0.33,
            "unit": "MPa",
        },
    }
    res_with_ctx = router.route(prompt, context=model_context)
    assert res_with_ctx.status == "ROUTED"
    assert res_with_ctx.intent is not None
    assert res_with_ctx.intent.material is not None
    assert res_with_ctx.intent.material["name"] == "Aluminum_6061"
    assert res_with_ctx.intent.metadata.get("context_merged") is True
    assert res_with_ctx.intent.metadata.get("dimensions") == [{"value": 200.0, "unit": "mm"}]
    assert len(res_with_ctx.intent.loads) > 0
    assert len(res_with_ctx.intent.boundary_conditions) > 0


def test_typesafe_provider_configuration_contracts(monkeypatch):
    """Verify explicit provider_type, trust boundaries, and endpoint resolution contracts."""
    # Ensure no ambient typesafe or external intent environment variables
    env_vars_to_clear = [
        "TYPESAFE_API_KEY", "TYPESAFE_API_URL", "TYPESAFE_PROVIDER", "TYPESAFE_RUN_MODE", "TYPESAFE_ALLOW_CUSTOM_HOST",
        "EXTERNAL_INTENT_API_KEY", "EXTERNAL_INTENT_API_URL", "EXTERNAL_INTENT_PROVIDER", "EXTERNAL_INTENT_MODEL",
        "EXTERNAL_INTENT_RUN_MODE", "EXTERNAL_INTENT_ALLOW_CUSTOM_HOST",
        "INTENT_API_KEY", "INTENT_API_URL", "INTENT_PROVIDER", "INTENT_MODEL", "INTENT_RUN_MODE",
    ]
    for var in env_vars_to_clear:
        monkeypatch.delenv(var, raising=False)

    # 1. API key containing 'typesafe' substring must NOT implicitly trigger typesafe endpoint
    generic_p = GenericHttpIntentProvider(api_key="custom_typesafe_substring_key")
    assert generic_p.endpoint is None
    assert generic_p.model == "external-intent-v1"

    # 2. Explicit provider_type="typesafe" correctly defaults to TypeSafe System One
    explicit_p = GenericHttpIntentProvider(api_key="any_key", provider_type="typesafe")
    assert explicit_p.endpoint == TYPESAFE_SYSTEMONE_DEFAULT_URL
    assert explicit_p.model == TYPESAFE_DEFAULT_MODEL

    # 3. Explicit TYPESAFE_API_KEY environment variable correctly defaults to TypeSafe System One
    monkeypatch.setenv("TYPESAFE_API_KEY", "env_ts_key")
    env_p = GenericHttpIntentProvider()
    assert env_p.endpoint == TYPESAFE_SYSTEMONE_DEFAULT_URL
    assert env_p.model == TYPESAFE_DEFAULT_MODEL

    # 4. Insecure HTTP scheme for TypeSafe provider strictly rejected
    with pytest.raises(ExternalIntentApiError, match="must use secure HTTPS scheme"):
        GenericHttpIntentProvider(endpoint="http://api.typesafe.ai/v1", provider_type="typesafe")

    # 5. Untrusted arbitrary external host for TypeSafe provider rejected by default
    with pytest.raises(ExternalIntentApiError, match="Untrusted endpoint host for TypeSafe provider"):
        GenericHttpIntentProvider(endpoint="https://untrusted.arbitrary-host.com/v1", provider_type="typesafe")

    # 6. Authorized custom endpoint overrides TypeSafe default with allow_custom_host
    custom_url = "https://custom.gateway.internal/v1"
    custom_p = GenericHttpIntentProvider(endpoint=custom_url, provider_type="typesafe", allow_custom_host=True)
    assert custom_p.endpoint == custom_url

    monkeypatch.setenv("EXTERNAL_INTENT_ALLOW_CUSTOM_HOST", "1")
    custom_env_p = GenericHttpIntentProvider(endpoint=custom_url, provider_type="typesafe")
    assert custom_env_p.endpoint == custom_url
    monkeypatch.delenv("EXTERNAL_INTENT_ALLOW_CUSTOM_HOST", raising=False)

    # 7. EngineeringIntentRouter contracts
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    router_unconfigured = JevIntentRouter(api_key="has_typesafe_in_key")
    assert router_unconfigured.api_url is None
    assert router_unconfigured.external_provider is None

    router_explicit = JevIntentRouter(api_key="any_key", provider_type="typesafe")
    assert router_explicit.api_url == TYPESAFE_SYSTEMONE_DEFAULT_URL
    assert router_explicit.external_provider is not None
    assert router_explicit.external_provider.model == TYPESAFE_DEFAULT_MODEL


def _screening_solids():
    return (
        {"solid_id": "S_HANDLE", "source_name": "Handle", "volume": 12.0},
        {"solid_id": "S_PIN", "label": "Pin", "volume": 1.5},
        {"solid_id": "S_COVER", "source_name": "Cover", "volume": 4.0},
    )


def _question_blob(payload):
    import json

    return json.dumps(payload["questions"])


def test_part_screening_request_shares_facts_once():
    """Shared policy and identities are stated once; each Noul only points at its row."""
    import json

    from abaqus_ai_agent.typesafe_intent import (
        _SCREENING_FALSE,
        _SCREENING_NOT_SUFFICIENT,
        _SCREENING_QUESTION,
        _SCREENING_TRUE,
        build_part_screening_questions,
        build_part_screening_request,
    )

    solids = _screening_solids()
    request = build_part_screening_request("  Analyze the handle  ", solids)
    encoded = json.dumps(request, sort_keys=True)

    assert request["state"]["requirement"] == "Analyze the handle"
    assert request["state"]["policy"]["not_sufficient"] == list(_SCREENING_NOT_SUFFICIENT)
    assert request["state"]["candidates"] == [
        {"solid_id": "S_HANDLE", "source_name": "Handle", "volume": 12.0, "identity": "source_name"},
        {"solid_id": "S_PIN", "source_name": "Pin", "volume": 1.5, "identity": "source_name"},
        {"solid_id": "S_COVER", "source_name": "Cover", "volume": 4.0, "identity": "source_name"},
    ]
    assert list(request["questions"]) == ["part_0", "part_1", "part_2"]
    assert request["questions"] == build_part_screening_questions(solids)

    for index, question in enumerate(request["questions"].values()):
        assert question["type"] == "noul"
        assert question["instructions"] == _SCREENING_QUESTION.format(
            candidate=f"`candidates[{index}]`"
        )
        assert question["criteria"] == {"true": _SCREENING_TRUE, "false": _SCREENING_FALSE}
        assert "not_sufficient" not in question["instructions"]
        assert "solid_id" not in question["instructions"]

    assert encoded.count("The solid merely exists in the same STEP file.") == 1
    assert encoded.count("S_HANDLE") == 1
    assert encoded.count("Judge each candidate independently") == 1
    assert "`candidates[0]`" in request["questions"]["part_0"]["instructions"]
    assert "`candidates[2]`" in request["questions"]["part_2"]["instructions"]


def test_part_screening_request_rejects_missing_identity_and_empty_input():
    from abaqus_ai_agent.typesafe_intent import build_part_screening_request

    with pytest.raises(ValueError, match="solid_id"):
        build_part_screening_request("Analyze the handle", [{"source_name": "Handle"}])
    with pytest.raises(ValueError, match="CAD solid inventory"):
        build_part_screening_request("Analyze the handle", [])
    with pytest.raises(ValueError, match="analysis requirement"):
        build_part_screening_request("   ", [{"solid_id": "S_HANDLE"}])


class _CapturingScreenProvider:
    model = "jev-test"

    def __init__(self, answers):
        self.answers = answers
        self.payloads = []

    def judge_payload(self, payload, timeout=5.0):
        self.payloads.append(payload)
        return {"answers": self.answers}


def test_live_part_screen_keeps_answer_contract_without_calling_api():
    """Payload is shared-state; answer ids and thresholds are unchanged. No live call."""
    from abaqus_ai_agent.typesafe_intent import EngineeringIntentRouter, JevApiError

    provider = _CapturingScreenProvider({
        "part_0": {"noul": 0.91},
        "part_1": {"probability": 0.05},
        "part_2": {"noul": 0.5},
    })
    router = EngineeringIntentRouter(mode="live", external_provider=provider)
    screen = router.screen_parts("Analyze the handle", _screening_solids())

    assert len(provider.payloads) == 1
    payload = provider.payloads[0]
    assert payload["model"] == "jev-test"
    assert payload["state"]["candidates"][0]["solid_id"] == "S_HANDLE"
    assert "not_sufficient" not in _question_blob(payload)
    by_id = {item.solid_id: item.disposition for item in screen.decisions}
    assert by_id == {"S_HANDLE": "retain", "S_PIN": "exclude", "S_COVER": "pending"}
    assert screen.decisions[0].confidence == 0.91
    assert screen.decisions[1].confidence == 0.05

    broken = _CapturingScreenProvider("not-a-dict")
    with pytest.raises(JevApiError, match="did not contain answers"):
        EngineeringIntentRouter(mode="live", external_provider=broken).screen_parts(
            "Analyze the handle", _screening_solids()
        )

    unlabeled = _CapturingScreenProvider({"part_0": {"noul": 0.99}})
    held = EngineeringIntentRouter(mode="live", external_provider=unlabeled).screen_parts(
        "Analyze the handle",
        ({"solid_id": "S_60", "volume": 1.0},),
    )
    assert held.decisions[0].disposition == "pending"
    assert held.decisions[0].role == "identity_missing"


def test_offline_part_screen_does_not_call_provider():
    from abaqus_ai_agent.typesafe_intent import EngineeringIntentRouter

    provider = _CapturingScreenProvider({})
    router = EngineeringIntentRouter(mode="offline", external_provider=provider)
    screen = router.screen_parts("Analyze the cover", (
        {"solid_id": "S_COVER", "source_name": "Cover", "volume": 4.0},
    ))
    assert provider.payloads == []
    assert screen.decisions[0].disposition == "pending"
