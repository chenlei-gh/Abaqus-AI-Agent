"""Live LLM Provider Client (OpenAI-compatible protocol).

Connects to real LLM provider endpoints (OpenAI, DeepSeek, Qwen, Moonshot, Ollama, vLLM)
to obtain authoritative provider-reported usage tokens (prompt_tokens, completion_tokens).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


def _is_valid_token_count(value: Any) -> bool:
    """A provider count must be a non-negative ``int``.

    ``bool`` is rejected explicitly: it is an ``int`` subclass in Python, so a JSON
    ``true`` would otherwise be accepted as a token count of 1. Floats are rejected
    too — no provider contract we target reports fractional tokens.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass(frozen=True)
class LiveLLMResponse:
    """Structured response from live LLM endpoint with authoritative usage.

    ``usage_measured`` is the honest gate: when the provider does not return a
    ``usage`` object, token counts stay ``None`` and ``usage_measured`` is False.
    Zero is never substituted for an unmeasured count (契约 B.1 UNMEASURED).
    """
    content: str
    model: str
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    latency_ms: float
    raw_response: Dict[str, Any] = field(default_factory=dict)
    usage_measured: bool = True
    #: Why a present-looking ``usage`` block was rejected. ``None`` when the block was
    #: either absent or accepted. A rejected block is never partially claimed.
    usage_rejected_reason: Optional[str] = None

    @property
    def token_source(self) -> str:
        return "provider_usage" if self.usage_measured else "unmeasured"

    @property
    def usage_dict(self) -> Dict[str, Optional[int]]:
        """Token counts as reported by the provider; ``None`` when unmeasured."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


class LiveLLMClient:
    """Zero-dependency client for standard /v1/chat/completions endpoints."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 45.0,
    ):
        self.api_key = (
            api_key
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("LLM_API_KEY")
        )
        raw_base_url = (
            base_url
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("DEEPSEEK_BASE_URL")
            or os.environ.get("LLM_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        if not raw_base_url.endswith("/v1") and not raw_base_url.endswith("/chat/completions"):
            self.base_url = f"{raw_base_url}/v1"
        else:
            self.base_url = raw_base_url

        self.model = (
            model
            or os.environ.get("OPENAI_MODEL")
            or os.environ.get("DEEPSEEK_MODEL")
            or os.environ.get("LLM_MODEL")
            or ("deepseek-chat" if "deepseek" in self.base_url.lower() else "gpt-4o-mini")
        )
        self.timeout_seconds = timeout_seconds

    @property
    def is_configured(self) -> bool:
        """Returns True if minimum credentials and endpoint are present."""
        return bool(self.api_key and self.base_url)

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> LiveLLMResponse:
        """Send chat completion request to live endpoint and return authoritative usage."""
        if not self.is_configured:
            raise RuntimeError(
                "LiveLLMClient is not configured. Please set OPENAI_API_KEY / DEEPSEEK_API_KEY / LLM_API_KEY "
                "and optionally OPENAI_BASE_URL / DEEPSEEK_BASE_URL / LLM_BASE_URL."
            )

        endpoint = (
            f"{self.base_url}/chat/completions"
            if not self.base_url.endswith("/chat/completions")
            else self.base_url
        )

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        req_bytes = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Abaqus-AI-Agent-Live-Benchmark/1.0",
        }

        req = urllib.request.Request(endpoint, data=req_bytes, headers=headers, method="POST")
        start_time = time.perf_counter()

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                resp_bytes = resp.read()
        except urllib.error.HTTPError as http_err:
            err_body = ""
            try:
                err_body = http_err.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError(
                f"Live LLM request failed with HTTP {http_err.code}: {http_err.reason}. Body: {err_body}"
            ) from http_err
        except urllib.error.URLError as url_err:
            raise RuntimeError(f"Live LLM connection failed: {url_err.reason}") from url_err

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        data = json.loads(resp_bytes.decode("utf-8"))

        usage = data.get("usage")
        prompt_tokens: Optional[int] = None
        completion_tokens: Optional[int] = None
        total_tokens: Optional[int] = None
        usage_measured = False
        usage_rejected_reason: Optional[str] = None

        if isinstance(usage, dict):
            raw_prompt = usage.get("prompt_tokens")
            raw_completion = usage.get("completion_tokens")
            raw_total = usage.get("total_tokens")
            if not (_is_valid_token_count(raw_prompt) and _is_valid_token_count(raw_completion)):
                usage_rejected_reason = "prompt_or_completion_missing_or_invalid"
            elif raw_total is not None and not _is_valid_token_count(raw_total):
                usage_rejected_reason = "total_tokens_invalid"
            elif raw_total is not None and raw_total != raw_prompt + raw_completion:
                usage_rejected_reason = "total_tokens_inconsistent"
            else:
                prompt_tokens = raw_prompt
                completion_tokens = raw_completion
                total_tokens = raw_total if raw_total is not None else raw_prompt + raw_completion
                usage_measured = True

        choices = data.get("choices", [])
        content = ""
        if choices and "message" in choices[0]:
            content = choices[0]["message"].get("content") or ""

        return LiveLLMResponse(
            content=content,
            model=data.get("model", self.model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=round(elapsed_ms, 2),
            raw_response=data,
            usage_measured=usage_measured,
            usage_rejected_reason=usage_rejected_reason,
        )
