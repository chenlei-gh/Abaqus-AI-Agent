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


def test_benchmark_dry_run_execution():
    """Verify benchmark executes in dry-run mode and produces evidence file."""
    results = run_benchmark(live_api=False)
    assert results["benchmark_id"] == "Live-Token-Benchmark-Case1-Case3"
    assert "case_01" in results["cases"]
    assert "case_03" in results["cases"]

    c1 = results["cases"]["case_01"]
    assert c1["metrics"]["prompt_token_reduction_pct"] > 75.0
    assert c1["metrics"]["measurement_source"] == "estimated"

    c3 = results["cases"]["case_03"]
    assert c3["metrics"]["prompt_token_reduction_pct"] > 75.0
    assert c3["metrics"]["measurement_source"] == "estimated"
