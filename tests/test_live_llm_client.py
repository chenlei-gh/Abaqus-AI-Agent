"""Unit Tests for Live LLM Provider Client and Token Benchmark Suite."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

from abaqus_ai_agent.llm.client import LiveLLMClient, LiveLLMResponse
from tools.live_token_benchmark import (
    build_case_01_payloads,
    build_case_03_payloads,
    run_benchmark,
)


def test_live_llm_client_unconfigured():
    """Verify that unconfigured client raises clear RuntimeError."""
    client = LiveLLMClient(api_key=None, base_url=None)
    with patch.dict("os.environ", {}, clear=True):
        client = LiveLLMClient()
        assert not client.is_configured
        with pytest.raises(RuntimeError, match="LiveLLMClient is not configured"):
            client.chat_completion(messages=[{"role": "user", "content": "hi"}])


def test_live_llm_client_mocked_completion():
    """Verify live client correctly extracts usage and completion from provider response."""
    client = LiveLLMClient(
        api_key="sk-mock-key",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )
    assert client.is_configured

    mock_response_body = {
        "id": "chatcmpl-mock-123",
        "object": "chat.completion",
        "created": 1728000000,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '{"observations": "Stress concentrated around bolt holes", "acceptance": "PASS"}',
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 842,
            "completion_tokens": 45,
            "total_tokens": 887,
        },
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_response_body).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.chat_completion(
            messages=[{"role": "user", "content": "Analyze state"}],
            tools=[{"type": "function", "function": {"name": "query_hotspot"}}],
        )

        assert isinstance(res, LiveLLMResponse)
        assert res.prompt_tokens == 842
        assert res.completion_tokens == 45
        assert res.total_tokens == 887
        assert res.usage_dict == {"prompt_tokens": 842, "completion_tokens": 45, "total_tokens": 887}
        assert "observations" in res.content
        assert res.model == "gpt-4o-mini"
        assert res.latency_ms >= 0.0


def test_benchmark_payload_construction():
    """Verify Case 1 and Case 3 benchmark payload isolation between Branch A and B."""
    # Case 1
    branch_a_1, branch_b_1 = build_case_01_payloads()
    assert len(branch_a_1["tools"]) >= 15
    assert len(branch_b_1["tools"]) < 10
    assert "Current Verified Engineering State" in branch_b_1["messages"][-1]["content"]

    # Case 3
    branch_a_3, branch_b_3 = build_case_03_payloads()
    assert len(branch_a_3["tools"]) >= 15
    assert len(branch_b_3["tools"]) < 10
    assert "Current Verified Engineering State" in branch_b_3["messages"][-1]["content"]


def test_live_llm_client_missing_usage_is_unmeasured_not_zero():
    """A provider response without a usage object must not be silently zero-filled."""
    client = LiveLLMClient(
        api_key="sk-mock-key",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )

    body_without_usage = {
        "model": "gpt-4o-mini",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(body_without_usage).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.chat_completion(messages=[{"role": "user", "content": "hi"}])

    assert res.usage_measured is False
    assert res.token_source == "unmeasured"
    assert res.prompt_tokens is None
    assert res.completion_tokens is None
    assert res.total_tokens is None


def test_live_llm_client_partial_usage_is_unmeasured():
    """Only a complete prompt/completion pair counts as a provider measurement."""
    client = LiveLLMClient(
        api_key="sk-mock-key",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )

    body = {
        "model": "gpt-4o-mini",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 120},
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(body).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.chat_completion(messages=[{"role": "user", "content": "hi"}])

    assert res.usage_measured is False
    assert res.total_tokens is None


# ---------------------------------------------------------------------------
# Malformed provider usage blocks
# ---------------------------------------------------------------------------

def _client() -> LiveLLMClient:
    return LiveLLMClient(
        api_key="sk-mock-key",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )


def _completion_with_usage(usage) -> LiveLLMResponse:
    body = {
        "model": "gpt-4o-mini",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
        "usage": usage,
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(body).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    with patch("urllib.request.urlopen", return_value=mock_resp):
        return _client().chat_completion(messages=[{"role": "user", "content": "hi"}])


@pytest.mark.parametrize(
    "usage, reason",
    [
        pytest.param({"prompt_tokens": True, "completion_tokens": 10}, "prompt_or_completion_missing_or_invalid", id="bool_prompt"),
        pytest.param({"prompt_tokens": 100, "completion_tokens": False}, "prompt_or_completion_missing_or_invalid", id="bool_completion"),
        pytest.param({"prompt_tokens": -5, "completion_tokens": 10}, "prompt_or_completion_missing_or_invalid", id="negative_prompt"),
        pytest.param({"prompt_tokens": 100, "completion_tokens": -1}, "prompt_or_completion_missing_or_invalid", id="negative_completion"),
        pytest.param({"prompt_tokens": 100.5, "completion_tokens": 10}, "prompt_or_completion_missing_or_invalid", id="float_prompt"),
        pytest.param({"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": -110}, "total_tokens_invalid", id="negative_total"),
        pytest.param({"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": True}, "total_tokens_invalid", id="bool_total"),
        pytest.param({"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 999}, "total_tokens_inconsistent", id="total_mismatch"),
    ],
)
def test_malformed_provider_usage_is_rejected_not_claimed(usage, reason):
    """`bool` is an `int` subclass and negatives are ints; neither is a token count."""
    res = _completion_with_usage(usage)

    assert res.usage_measured is False
    assert res.token_source == "unmeasured"
    assert res.usage_rejected_reason == reason
    # Never partially claim a rejected block.
    assert res.prompt_tokens is None
    assert res.completion_tokens is None
    assert res.total_tokens is None


def test_valid_provider_usage_is_accepted_with_consistent_total():
    res = _completion_with_usage({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})

    assert res.usage_measured is True
    assert res.usage_rejected_reason is None
    assert res.total_tokens == 0


def test_benchmark_dry_run_execution():
    """Offline mode must be labeled UNMEASURED, never sold as a measured saving."""
    results = run_benchmark(live_api=False)
    assert results["benchmark_id"] == "Live-Token-Benchmark-Case1-Case3"
    assert "case_01" in results["cases"]
    assert "case_03" in results["cases"]

    for case_key in ("case_01", "case_03"):
        case = results["cases"][case_key]
        # Heuristic sizes may still be printed, but the source is never a measurement.
        assert case["metrics"]["measurement_source"] == "unmeasured"
        # Response usage and billing reconciliation are separate claims; neither is made here.
        assert case["metrics"]["evidence_scope"] == "none"
        assert case["metrics"]["billing_reconciled"] is False
        assert case["metrics"]["claimable"] is False
        assert case["metrics"]["status"] == "UNMEASURED"
        assert case["branch_a"]["source"] == "unmeasured"
        assert case["branch_b"]["source"] == "unmeasured"
        assert case["branch_a"]["heuristic_size_estimate"] is True
