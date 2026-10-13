"""Generic & Decoupled Intent Routing for Abaqus Engineering.

Translates unconstrained natural language engineering requirements into typed,
deterministic EngineeringIntent and ResultRequirement models using declarative primitives:
- Choice: Discretely classifies physics category, unit system, and target solver.
- Noul: Assesses constraints sufficiency probability and acceptance criteria explicitness.
- Score: Quantifies engineering intent completeness (1 to 5 scale).

Architectural Decoupling Contract (REQ-P1-046 ~ REQ-P1-049, REQ-P1-053):
- Core Open-Source Engine: Deterministic offline rule engine runs 100% self-sufficiently
  without any external API keys, commercial services, or internet access.
- Optional External Provider: Cleanly isolated via ExternalIntentProviderProtocol.
  Proprietary endpoints and credentials are strictly kept outside the core open-source codebase.
- Three-State Execution Modes:
  * 'offline' (default): Pure deterministic rule engine (hermetic, reproducible, zero-cost).
  * 'live': Invokes configured external provider. Fails closed (JevApiError) on any error.
  * 'shadow': Baseline offline engine executes, while recording side-by-side discrepancy auditing.
    If external provider is not configured, records status='NOT_CONFIGURED'.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.results import ResultRequirement
from abaqus_ai_agent.contracts.units import UnitSystem


def _sanitize_error_message(err_msg: str) -> str:
    """Deep sanitization of error messages to eliminate sensitive credentials, URLs, query parameters, and unscrubbed prompts."""
    if not err_msg:
        return "Unknown error"
    # 1. Redact Authorization tokens (Bearer, Basic, etc.)
    sanitized = re.sub(r"(bearer\s+)[^\s]+", r"\1[REDACTED]", err_msg, flags=re.IGNORECASE)
    sanitized = re.sub(r"(basic\s+)[^\s]+", r"\1[REDACTED]", sanitized, flags=re.IGNORECASE)
    # 2. Redact potential API keys (e.g. sk-..., key=..., token=...)
    sanitized = re.sub(r"(sk-[a-zA-Z0-9_-]{8,})", r"[REDACTED_KEY]", sanitized)
    sanitized = re.sub(r"(?:api[_-]?key|token|secret)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-\.]+['\"]?", r"[REDACTED_CREDENTIAL]", sanitized, flags=re.IGNORECASE)
    # 3. Strip URLs and query parameters
    sanitized = re.sub(r"https?://[^\s/?#]+(?:/[^\s?#]*)?(?:\?[^\s#]*)?", r"[REDACTED_URL]", sanitized)
    # 4. Strip filesystem paths
    sanitized = re.sub(r"(?:[a-zA-Z]:\\|\/)[^\s:\"']+", r"[REDACTED_PATH]", sanitized)
    # 5. Clean extra whitespace and truncate to safe bound
    sanitized = " ".join(sanitized.split())
    return sanitized[:120] if len(sanitized) > 120 else sanitized


def _get_external_config(*var_names: str) -> Optional[str]:
    """Read external configuration in order of priority, stripping whitespace and treating empty/blank as None."""
    for name in var_names:
        if not name:
            continue
        val = os.environ.get(name)
        if val is not None:
            stripped = val.strip()
            if stripped:
                return stripped
    return None


def _validate_numeric(
    value: Any,
    min_val: float,
    max_val: float,
    field_name: str,
) -> float:
    """Strictly validate numeric values: reject booleans, NaN, Inf, and out-of-range floats."""
    if isinstance(value, bool):
        raise ExternalIntentApiError(
            f"Field {field_name!r} must not be a boolean value: {value!r}"
        )
    if not isinstance(value, (int, float)):
        raise ExternalIntentApiError(
            f"Field {field_name!r} must be a numeric value, got {type(value).__name__}: {value!r}"
        )
    fval = float(value)
    if math.isnan(fval) or math.isinf(fval):
        raise ExternalIntentApiError(
            f"Field {field_name!r} must be a finite number, got {fval!r}"
        )
    if not (min_val <= fval <= max_val):
        raise ExternalIntentApiError(
            f"Field {field_name!r} value {fval} out of bounds [{min_val}, {max_val}]"
        )
    return fval


def _validate_distribution(
    dist: Any,
    allowed_keys: Tuple[str, ...],
    field_name: str,
) -> Dict[str, float]:
    """Strictly validate probability distributions: dict type, allowed keys, non-empty, probabilities in [0.0, 1.0], and sum(probabilities) == 1.0."""
    if not isinstance(dist, dict) or not dist:
        raise ExternalIntentApiError(f"Field {field_name!r} distribution must be a non-empty dictionary.")
    validated: Dict[str, float] = {}
    for k, v in dist.items():
        if k not in allowed_keys:
            raise ExternalIntentApiError(f"Invalid {field_name} choice in distribution: {k!r}")
        prob = _validate_numeric(v, 0.0, 1.0, f"{field_name}.distribution[{k}]")
        validated[k] = prob
    total_prob = sum(validated.values())
    if not math.isclose(total_prob, 1.0, abs_tol=0.05):
        raise ExternalIntentApiError(
            f"Field {field_name!r} probability distribution must sum to 1.0 (got {total_prob:.4f})"
        )
    return validated


def _validate_score_levels(levels: Any) -> Dict[int, float]:
    """Strictly validate completeness score levels: dict type, non-empty, int keys in 1..5, probabilities in [0.0, 1.0], and sum(probabilities) == 1.0."""
    if not isinstance(levels, dict) or not levels:
        raise ExternalIntentApiError("Completeness score 'levels' must be a non-empty dictionary.")
    validated: Dict[int, float] = {}
    for k, v in levels.items():
        if isinstance(k, bool):
            raise ExternalIntentApiError(f"Invalid level key in completeness levels: {k!r}")
        try:
            ik = int(k)
        except (ValueError, TypeError):
            raise ExternalIntentApiError(f"Invalid level key in completeness levels: {k!r}")
        if not (1 <= ik <= 5):
            raise ExternalIntentApiError(f"Completeness level key out of range [1, 5]: {ik}")
        prob = _validate_numeric(v, 0.0, 1.0, f"completeness.levels[{ik}]")
        validated[ik] = prob
    total_prob = sum(validated.values())
    if not math.isclose(total_prob, 1.0, abs_tol=0.05):
        raise ExternalIntentApiError(
            f"Completeness score levels distribution must sum to 1.0 (got {total_prob:.4f})"
        )
    return validated


@dataclass(frozen=True)
class DraftEngineeringIntent:
    """Non-executable draft intent contract strictly isolated from FEA solver execution pipelines.

    Used exclusively for exploratory, interactive UI, or diagnostic inspection.
    Any attempt to execute this object directly will be blocked by downstream preflights.
    """
    id: str
    kind: str
    description: str
    analysis_type: str
    unit_system: str
    material: Optional[Dict[str, Any]] = None
    boundary_conditions: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    loads: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    acceptance_criteria: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_executable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExternalIntentApiError(RuntimeError):
    """Raised when external AI intent provider fails or returns invalid payloads in live mode."""


# Backwards compatibility alias
JevApiError = ExternalIntentApiError


class IntentAmbiguityError(ValueError):
    """Raised when natural language prompt is ambiguous or missing required physics definition."""

    def __init__(self, message: str, missing_requirements: List[str], bundle: IntentDecisionBundle):
        super().__init__(message)
        self.missing_requirements = missing_requirements
        self.bundle = bundle


@dataclass(frozen=True)
class IntentRoutingResult:
    """Complete result of intent routing with fail-closed clarification gating."""
    status: str  # "ROUTED", "NEEDS_CLARIFICATION", "BLOCKED"
    intent: Optional[EngineeringIntent]
    decision_bundle: IntentDecisionBundle
    missing_requirements: List[str] = field(default_factory=list)
    clarification_prompt: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "intent": asdict(self.intent) if self.intent else None,
            "decision_bundle": self.decision_bundle.to_dict(),
            "missing_requirements": self.missing_requirements,
            "clarification_prompt": self.clarification_prompt,
        }


@dataclass(frozen=True)
class ChoiceJudgment:
    """Discrete choice primitive result."""
    value: str
    confidence: float
    distribution: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class NoulJudgment:
    """Binary probability primitive result (probability of Yes)."""
    probability: float
    is_yes: bool = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "is_yes", self.probability >= 0.5)


@dataclass(frozen=True)
class ScoreJudgment:
    """Continuous or graded score primitive result (1 to 5 scale)."""
    score: float
    levels: Dict[int, float] = field(default_factory=dict)


@dataclass(frozen=True)
class IntentDecisionBundle:
    """Consolidated judgments from intent reasoning."""
    physics_choice: ChoiceJudgment
    unit_system_choice: ChoiceJudgment
    solver_choice: ChoiceJudgment
    is_well_constrained_noul: NoulJudgment
    has_acceptance_criteria_noul: NoulJudgment
    completeness_score: ScoreJudgment
    extracted_parameters: Dict[str, Any] = field(default_factory=dict)
    source_model: str = "offline-rule-engine-v1"
    execution_mode: str = "offline"
    latency_ms: float = 0.0
    inferred_fields: List[str] = field(default_factory=list)
    shadow_diff: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_model": self.source_model,
            "execution_mode": self.execution_mode,
            "latency_ms": self.latency_ms,
            "physics_choice": asdict(self.physics_choice),
            "unit_system_choice": asdict(self.unit_system_choice),
            "solver_choice": asdict(self.solver_choice),
            "is_well_constrained_noul": asdict(self.is_well_constrained_noul),
            "has_acceptance_criteria_noul": asdict(self.has_acceptance_criteria_noul),
            "completeness_score": asdict(self.completeness_score),
            "extracted_parameters": self.extracted_parameters,
            "inferred_fields": self.inferred_fields,
            "shadow_diff": self.shadow_diff,
        }


# Backwards compatibility alias
JevDecisionBundle = IntentDecisionBundle


@runtime_checkable
class ExternalIntentProviderProtocol(Protocol):
    """Protocol for optional external AI decision providers."""

    def judge(self, prompt: str, timeout: float = 5.0) -> Dict[str, Any]:
        """Execute judgment against external provider and return normalized judgments dictionary."""
        ...


class GenericHttpIntentProvider:
    """Vendor-neutral HTTP adapter for optional external AI intent providers.

    Zero proprietary endpoints or models are hardcoded. All service coordinates are
    explicitly injected via constructor parameters or vendor-neutral environment variables.
    """

    MAX_RESPONSE_BYTES: int = 1_048_576  # 1 MB maximum response payload gate

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        payload_builder: Optional[Callable[[str, "GenericHttpIntentProvider"], Dict[str, Any]]] = None,
        response_normalizer: Optional[Callable[[Any], Dict[str, Any]]] = None,
    ):
        raw_endpoint = endpoint or _get_external_config("EXTERNAL_INTENT_API_URL", "INTENT_API_URL", "TYPESAFE_API_URL")
        self.endpoint = raw_endpoint.strip() if raw_endpoint else None

        raw_api_key = api_key or _get_external_config("EXTERNAL_INTENT_API_KEY", "INTENT_API_KEY", "TYPESAFE_API_KEY")
        self.api_key = raw_api_key.strip() if raw_api_key else None

        raw_model = model or _get_external_config("EXTERNAL_INTENT_MODEL", "INTENT_MODEL")
        self.model = raw_model.strip() if raw_model else "external-intent-v1"

        self._payload_builder = payload_builder
        self._response_normalizer = response_normalizer or self._default_response_normalizer

    @staticmethod
    def _default_response_normalizer(raw_data: Any) -> Dict[str, Any]:
        """Normalize provider response into standard engineering judgment dictionary.

        Supports both direct standard judgment dicts and wrapped dicts (e.g. {'answers': ...}).
        """
        if not isinstance(raw_data, dict):
            return {}
        if "answers" in raw_data and isinstance(raw_data["answers"], dict):
            return raw_data["answers"]
        return raw_data

    def is_configured(self) -> bool:
        """Return True only if both endpoint and credentials are provided."""
        return bool(self.endpoint and self.api_key)

    def judge(self, prompt: str, timeout: float = 5.0) -> Dict[str, Any]:
        """Send prompt to the configured HTTP endpoint and return normalized judgments."""
        if not self.endpoint:
            raise ExternalIntentApiError(
                "External intent provider endpoint is not configured. "
                "Explicit endpoint configuration is required."
            )
        if not self.api_key:
            raise ExternalIntentApiError(
                "API credentials are required for external intent provider."
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if self._payload_builder:
            payload = self._payload_builder(prompt, self)
        else:
            payload = {
                "model": self.model,
                "prompt": prompt,
            }

        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw_bytes = resp.read(self.MAX_RESPONSE_BYTES + 1)
                if len(raw_bytes) > self.MAX_RESPONSE_BYTES:
                    raise ExternalIntentApiError(
                        f"External intent API response exceeded maximum allowed payload size of {self.MAX_RESPONSE_BYTES} bytes."
                    )
                raw_json = json.loads(raw_bytes.decode("utf-8"))
                normalized = self._response_normalizer(raw_json)
                if not isinstance(normalized, dict):
                    raise ExternalIntentApiError(
                        f"Response normalizer returned {type(normalized).__name__}, expected dict."
                    )
                return normalized
        except urllib.error.HTTPError as http_err:
            try:
                http_err.close()
            except Exception:
                pass
            raise ExternalIntentApiError(
                f"External intent API HTTP {http_err.code} error: {http_err.reason}."
            ) from http_err
        except urllib.error.URLError as url_err:
            raise ExternalIntentApiError(f"External intent API network unreachable: {url_err.reason}") from url_err
        except Exception as exc:
            if isinstance(exc, ExternalIntentApiError):
                raise
            raise ExternalIntentApiError(f"External intent API invocation failed: {exc}") from exc


class EngineeringIntentRouter:
    """Vendor-neutral Engineering Intent Router supporting deterministic offline rules and optional external AI."""

    PHYSICS_OPTIONS = (
        "linear_static",
        "steady_thermal",
        "transient_dynamic",
        "modal_frequency",
        "contact_frictional",
        "fatigue_damage",
    )

    UNIT_OPTIONS = (
        "MM_N_MPA",
        "SI",
        "IN_LBF_PSI",
    )

    SOLVER_OPTIONS = (
        "abaqus_standard",
        "abaqus_explicit",
    )

    VALID_MODES = ("offline", "live", "shadow")

    def __init__(
        self,
        api_key: Optional[str] = None,
        use_live_api: bool = False,
        mode: Optional[str] = None,
        timeout: float = 5.0,
        api_url: Optional[str] = None,
        external_provider: Optional[Any] = None,
    ):
        raw_key = api_key or _get_external_config("EXTERNAL_INTENT_API_KEY", "INTENT_API_KEY", "TYPESAFE_API_KEY")
        self.api_key = raw_key.strip() if raw_key else None
        raw_url = api_url or _get_external_config("EXTERNAL_INTENT_API_URL", "INTENT_API_URL", "TYPESAFE_API_URL")
        self.api_url = raw_url.strip() if raw_url else None
        self.timeout = timeout

        if mode is not None:
            norm_mode = mode.strip().lower()
            if norm_mode not in self.VALID_MODES:
                raise ValueError(f"Invalid JEV mode / intent mode: {mode!r}. Must be one of {self.VALID_MODES}.")
            self.mode = norm_mode
        elif use_live_api:
            self.mode = "live"
        else:
            env_mode = _get_external_config(
                "EXTERNAL_INTENT_RUN_MODE", "INTENT_RUN_MODE", "TYPESAFE_RUN_MODE"
            )
            if env_mode:
                norm_env = env_mode.strip().lower()
                if norm_env not in self.VALID_MODES:
                    raise ValueError(
                        f"Invalid intent run mode in environment: {env_mode!r}. Must be one of {self.VALID_MODES}."
                    )
                self.mode = norm_env
            else:
                self.mode = "offline"

        self.use_live_api = (self.mode == "live")

        # Configure optional external provider (zero default proprietary endpoints)
        if external_provider is not None:
            self.external_provider = external_provider
        elif self.api_url and self.api_key:
            self.external_provider = GenericHttpIntentProvider(
                endpoint=self.api_url,
                api_key=self.api_key,
            )
        else:
            self.external_provider = None

    def route(
        self, prompt: str, context: Optional[Dict[str, Any]] = None
    ) -> IntentRoutingResult:
        """Route prompt with explicit fail-closed clarification gate and optional engineering context merge."""
        prompt_clean = prompt.strip()
        if not prompt_clean:
            raise ValueError("Engineering intent prompt cannot be empty.")

        decisions = self._evaluate_system_one_judgments(prompt_clean)
        missing = self._detect_missing_engineering_prerequisites(prompt_clean, decisions, context=context)

        if missing:
            clarification_msg = (
                f"Engineering specification is ambiguous or incomplete. Missing prerequisites: {', '.join(missing)}. "
                "Please clarify structural dimensions, boundary conditions, applied loads, material properties, "
                "or acceptance thresholds before submitting simulation execution."
            )
            return IntentRoutingResult(
                status="NEEDS_CLARIFICATION",
                intent=None,
                decision_bundle=decisions,
                missing_requirements=missing,
                clarification_prompt=clarification_msg,
            )

        intent = self._build_intent_from_decisions(prompt_clean, decisions, context=context)
        return IntentRoutingResult(
            status="ROUTED",
            intent=intent,
            decision_bundle=decisions,
            missing_requirements=[],
            clarification_prompt=None,
        )

    def route_prompt_to_intent(
        self,
        prompt: str,
        strict: bool = True,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[EngineeringIntent, JevDecisionBundle]:
        """Convert natural language requirement into typed EngineeringIntent via judgments.

        Fail-closed contract: If requirements are incomplete or ambiguous (non-ROUTED),
        always raises IntentAmbiguityError. Does NOT allow bypassing execution gates
        even if strict=False is passed.
        """
        res = self.route(prompt, context=context)
        if res.status != "ROUTED":
            raise IntentAmbiguityError(
                res.clarification_prompt or "Incomplete engineering intent.",
                res.missing_requirements,
                res.decision_bundle,
            )

        assert res.intent is not None
        return res.intent, res.decision_bundle

    def create_draft_intent(
        self, prompt: str, context: Optional[Dict[str, Any]] = None
    ) -> Tuple[DraftEngineeringIntent, JevDecisionBundle]:
        """Create an exploratory, non-executable draft intent for inspection or interactive UX.

        Returns DraftEngineeringIntent (with is_executable=False) which is explicitly
        rejected from solver compilation and execution pipelines.
        """
        prompt_clean = prompt.strip()
        if not prompt_clean:
            raise ValueError("Engineering intent prompt cannot be empty.")
        decisions = self._evaluate_system_one_judgments(prompt_clean)
        draft = self._build_draft_intent_from_decisions(prompt_clean, decisions, context=context)
        return draft, decisions

    PHYSICS_PREREQUISITE_RULES: Dict[str, Dict[str, bool]] = {
        "linear_static": {
            "require_dimensions": True,
            "require_material": True,
            "require_constraints": True,
            "require_loads": True,
            "require_thermal_bcs": False,
        },
        "steady_thermal": {
            "require_dimensions": True,
            "require_material": True,
            "require_constraints": False,
            "require_loads": False,
            "require_thermal_bcs": True,
        },
        "transient_dynamic": {
            "require_dimensions": True,
            "require_material": True,
            "require_constraints": True,
            "require_loads": True,
            "require_thermal_bcs": False,
        },
        "modal_frequency": {
            "require_dimensions": True,
            "require_material": True,
            "require_constraints": True,
            "require_loads": False,
            "require_thermal_bcs": False,
        },
        "contact_frictional": {
            "require_dimensions": True,
            "require_material": True,
            "require_constraints": True,
            "require_loads": True,
            "require_thermal_bcs": False,
        },
        "fatigue_damage": {
            "require_dimensions": True,
            "require_material": True,
            "require_constraints": True,
            "require_loads": True,
            "require_thermal_bcs": False,
        },
    }

    @staticmethod
    def _has_thermal_boundary_conditions(prompt: str) -> bool:
        """Accurately detect whether prompt specifies thermal boundary conditions.

        Avoid single-character matches (like 'k' in English words such as 'check').
        Matches:
        - Specific temperatures with units: 100C, 0°C, 300 K, 25 degC, etc.
        - Bounded thermal boundary/excitation keywords: 热端, 冷端, 恒温, 绝热, 温差, 对流, 辐射, 热流,
          heat flux, heat source, thermal load, convection, radiation, insulated, adiabatic.
        """
        temp_unit_pattern = re.compile(
            r"(?<![a-zA-Z0-9])\d+(?:\.\d+)?\s*(?:°c|degc|deg\s*c|c|k|kelvin)(?![a-zA-Z0-9])",
            re.IGNORECASE,
        )
        if temp_unit_pattern.search(prompt):
            return True

        prompt_lower = prompt.lower()
        thermal_keywords = (
            "热端",
            "冷端",
            "恒温",
            "绝热",
            "温差",
            "对流",
            "辐射",
            "热流",
            "热源",
            "生热",
            "heat flux",
            "heat source",
            "thermal load",
            "convection",
            "radiation",
            "insulated",
            "adiabatic",
            "ambient temperature",
            "prescribed temperature",
            "fixed temperature",
            "applied temperature",
        )
        return any(kw in prompt_lower for kw in thermal_keywords)

    def _detect_missing_engineering_prerequisites(
        self,
        prompt: str,
        bundle: JevDecisionBundle,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Verify whether prompt contains all necessary engineering prerequisites via table-driven rules.

        Seamlessly merges model context (existing CAE/INP geometry, materials, boundary conditions)
        to prevent false-positive blocks when evidence already exists in upstream project assets.
        """
        missing = []
        params = bundle.extracted_parameters
        phys = bundle.physics_choice.value
        ctx = context or {}

        rules = self.PHYSICS_PREREQUISITE_RULES.get(
            phys,
            {
                "require_dimensions": True,
                "require_material": True,
                "require_constraints": True,
                "require_loads": True,
                "require_thermal_bcs": False,
                "require_acceptance_criteria": True,
            },
        )

        # 1. Geometry Dimensions
        has_dims = bool(
            params.get("dimensions")
            or ctx.get("dimensions")
            or ctx.get("geometry")
            or ctx.get("has_geometry")
            or ctx.get("has_model")
            or ctx.get("inp_evidence")
        )
        if rules["require_dimensions"] and not has_dims:
            missing.append("missing_geometry_dimensions")

        # 2. Material
        has_mat = bool(
            params.get("material")
            or ctx.get("material")
            or ctx.get("has_material")
            or (isinstance(ctx.get("inp_evidence"), dict) and ctx["inp_evidence"].get("material"))
        )
        if rules["require_material"] and not has_mat:
            missing.append("missing_material_specification")

        # 3. Boundary Constraints
        has_bc = bool(
            bundle.is_well_constrained_noul.is_yes
            or ctx.get("boundary_conditions")
            or ctx.get("constraints")
            or ctx.get("is_well_constrained")
            or ctx.get("has_constraints")
        )
        if rules["require_constraints"] and not has_bc:
            missing.append("missing_boundary_constraints")

        # 4. Applied Loads / Excitation
        has_load = bool(
            params.get("loads")
            or ctx.get("loads")
            or ctx.get("has_loads")
        )
        if rules["require_loads"] and not has_load:
            missing.append("missing_applied_loads")

        # 5. Thermal Boundary Conditions
        has_thermal = bool(
            self._has_thermal_boundary_conditions(prompt)
            or ctx.get("thermal_bcs")
            or ctx.get("thermal_boundary_conditions")
            or ctx.get("has_thermal_bcs")
        )
        if rules["require_thermal_bcs"] and not has_thermal:
            missing.append("missing_thermal_boundary_conditions")

        # 6. Acceptance Criteria / Limits
        # Decouple physical solver prerequisites from compliance acceptance targets.
        # Exploratory analysis does NOT require numeric acceptance thresholds.
        # Only require explicit criteria if the user specifically asked for verification/compliance check
        # without specifying metrics or limits (e.g. "校核是否达标", "校核是否合格", "check compliance").
        prompt_lower = prompt.lower()
        unspecified_compliance_check = any(
            w in prompt_lower for w in ("是否达标", "是否合格", "是否满足要求", "compliance", "is compliant")
        )
        if unspecified_compliance_check:
            has_extracted_limits = bool(params.get("acceptance_criteria") or ctx.get("acceptance_criteria"))
            if not has_extracted_limits:
                missing.append("missing_acceptance_criteria_or_limits")

        return missing

    def _evaluate_system_one_judgments(self, prompt: str) -> JevDecisionBundle:
        """Evaluate judgments over input prompt in accordance with the configured execution mode."""
        if self.mode == "live":
            if not self.external_provider:
                raise JevApiError(
                    "External intent provider is not configured. "
                    "Fail-closed: refused to silently degrade to offline engine in strict live mode."
                )
            if hasattr(self.external_provider, "is_configured") and not self.external_provider.is_configured():
                raise JevApiError(
                    "External intent provider is not fully configured (missing endpoint or credentials). "
                    "Fail-closed: refused to silently degrade to offline engine in strict live mode."
                )

            t0 = time.perf_counter()
            try:
                if hasattr(self.external_provider, "judge"):
                    raw_data = self.external_provider.judge(prompt, timeout=self.timeout)
                elif callable(self.external_provider):
                    raw_data = self.external_provider(prompt)
                else:
                    raise JevApiError(f"Unsupported external provider type: {type(self.external_provider).__name__}")
            except JevApiError:
                raise
            except Exception as exc:
                raise JevApiError(
                    f"External intent provider request failed in live mode: {exc}. "
                    "Fail-closed: refusing silent fallback to offline engine."
                ) from exc

            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return self._parse_provider_response(raw_data, prompt, latency_ms=latency_ms)

        if self.mode == "shadow":
            baseline = self._evaluate_offline_engine(prompt)
            shadow_diff: Dict[str, Any] = {
                "status": "NOT_CONFIGURED",
                "reason": "No external intent provider configured",
            }
            if self.external_provider:
                try:
                    is_conf = (
                        self.external_provider.is_configured()
                        if hasattr(self.external_provider, "is_configured")
                        else True
                    )
                    if not is_conf:
                        shadow_diff = {
                            "status": "NOT_CONFIGURED",
                            "reason": "External intent provider is not fully configured",
                        }
                    else:
                        if hasattr(self.external_provider, "judge"):
                            raw_data = self.external_provider.judge(prompt, timeout=self.timeout)
                        elif callable(self.external_provider):
                            raw_data = self.external_provider(prompt)
                        else:
                            raise ExternalIntentApiError(
                                f"Unsupported provider type: {type(self.external_provider).__name__}"
                            )
                        live_res = self._parse_provider_response(raw_data, prompt, latency_ms=0.0)
                        shadow_diff = self._compute_shadow_diff(baseline, live_res)
                except Exception as shadow_err:
                    root_cause = getattr(shadow_err, "__cause__", None)
                    if isinstance(shadow_err, urllib.error.HTTPError) or (
                        isinstance(shadow_err, ExternalIntentApiError) and "HTTP" in str(shadow_err)
                    ):
                        err_cat = "PROVIDER_HTTP_ERROR"
                    elif (
                        isinstance(shadow_err, urllib.error.URLError)
                        or isinstance(root_cause, urllib.error.URLError)
                        or "network unreachable" in str(shadow_err).lower()
                    ):
                        err_cat = "PROVIDER_NETWORK_ERROR"
                    elif isinstance(shadow_err, ExternalIntentApiError):
                        err_cat = "PROVIDER_CONTRACT_VIOLATION"
                    elif isinstance(shadow_err, TimeoutError) or isinstance(root_cause, TimeoutError):
                        err_cat = "PROVIDER_TIMEOUT"
                    else:
                        err_cat = "PROVIDER_INTERNAL_ERROR"

                    err_msg = str(shadow_err)
                    sanitized_err = _sanitize_error_message(err_msg)
                    shadow_diff = {
                        "status": "LIVE_FAILED",
                        "error_category": err_cat,
                        "error": sanitized_err,
                        "baseline_model": baseline.source_model,
                    }

            return JevDecisionBundle(
                physics_choice=baseline.physics_choice,
                unit_system_choice=baseline.unit_system_choice,
                solver_choice=baseline.solver_choice,
                is_well_constrained_noul=baseline.is_well_constrained_noul,
                has_acceptance_criteria_noul=baseline.has_acceptance_criteria_noul,
                completeness_score=baseline.completeness_score,
                extracted_parameters=baseline.extracted_parameters,
                source_model="offline-shadow-audited",
                execution_mode="shadow",
                latency_ms=baseline.latency_ms,
                inferred_fields=baseline.inferred_fields,
                shadow_diff=shadow_diff,
            )

        # Default offline deterministic execution mode (100% self-contained)
        return self._evaluate_offline_engine(prompt)

    def _compute_shadow_diff(
        self, baseline: JevDecisionBundle, live: JevDecisionBundle
    ) -> Dict[str, Any]:
        """Compute discrepancy metrics between baseline offline rule and live external provider."""
        return {
            "status": "EVALUATED",
            "physics_match": baseline.physics_choice.value == live.physics_choice.value,
            "unit_system_match": baseline.unit_system_choice.value == live.unit_system_choice.value,
            "solver_match": baseline.solver_choice.value == live.solver_choice.value,
            "constrained_match": baseline.is_well_constrained_noul.is_yes == live.is_well_constrained_noul.is_yes,
            "criteria_match": baseline.has_acceptance_criteria_noul.is_yes == live.has_acceptance_criteria_noul.is_yes,
            "baseline_physics": baseline.physics_choice.value,
            "live_physics": live.physics_choice.value,
            "baseline_model": baseline.source_model,
            "live_model": live.source_model,
            "live_latency_ms": live.latency_ms,
        }

    def _parse_provider_response(
        self, data: Dict[str, Any], prompt: str, latency_ms: float = 0.0
    ) -> IntentDecisionBundle:
        """Parse and strictly validate normalized judgments dictionary into typed bundle.

        Accepts either standard normalized dict directly or legacy dict wrapped in 'answers'.
        """
        if not isinstance(data, dict):
            raise ExternalIntentApiError(f"Expected dict response from external provider, got {type(data).__name__}")

        # Support direct normalized dictionary as well as wrapped dictionary
        answers = data.get("answers") if ("answers" in data and isinstance(data.get("answers"), dict)) else data
        if not isinstance(answers, dict) or not answers:
            raise ExternalIntentApiError("Missing or invalid normalized judgments dictionary in external provider response.")

        # 1. Physics Validation
        phys_info = answers.get("physics")
        if not isinstance(phys_info, dict):
            raise ExternalIntentApiError("Missing required 'physics' judgment in external provider response.")
        phys_val = phys_info.get("choice")
        if phys_val not in self.PHYSICS_OPTIONS:
            raise ExternalIntentApiError(f"Invalid physics choice {phys_val!r}. Allowed: {self.PHYSICS_OPTIONS}")
        if "confidence" not in phys_info or phys_info["confidence"] is None:
            raise ExternalIntentApiError("Missing required 'confidence' in physics judgment.")
        phys_conf = _validate_numeric(phys_info["confidence"], 0.0, 1.0, "physics.confidence")

        phys_dist = None
        if phys_info.get("distribution") is not None:
            phys_dist = _validate_distribution(phys_info["distribution"], self.PHYSICS_OPTIONS, "physics")

        # 2. Units Validation
        unit_info = answers.get("units")
        if not isinstance(unit_info, dict):
            raise ExternalIntentApiError("Missing required 'units' judgment in external provider response.")
        unit_val = unit_info.get("choice")
        if unit_val not in self.UNIT_OPTIONS:
            raise ExternalIntentApiError(f"Invalid units choice {unit_val!r}. Allowed: {self.UNIT_OPTIONS}")
        if "confidence" not in unit_info or unit_info["confidence"] is None:
            raise ExternalIntentApiError("Missing required 'confidence' in units judgment.")
        unit_conf = _validate_numeric(unit_info["confidence"], 0.0, 1.0, "units.confidence")

        unit_dist = None
        if unit_info.get("distribution") is not None:
            unit_dist = _validate_distribution(unit_info["distribution"], self.UNIT_OPTIONS, "units")

        # 3. Solver Validation
        solver_info = answers.get("solver")
        if not isinstance(solver_info, dict):
            raise ExternalIntentApiError("Missing required 'solver' judgment in external provider response.")
        solver_val = solver_info.get("choice")
        if solver_val not in self.SOLVER_OPTIONS:
            raise ExternalIntentApiError(f"Invalid solver choice {solver_val!r}. Allowed: {self.SOLVER_OPTIONS}")
        if "confidence" not in solver_info or solver_info["confidence"] is None:
            raise ExternalIntentApiError("Missing required 'confidence' in solver judgment.")
        solver_conf = _validate_numeric(solver_info["confidence"], 0.0, 1.0, "solver.confidence")

        solver_dist = None
        if solver_info.get("distribution") is not None:
            solver_dist = _validate_distribution(solver_info["distribution"], self.SOLVER_OPTIONS, "solver")

        # 4. Well-constrained Validation
        wc_info = answers.get("well_constrained")
        if not isinstance(wc_info, dict):
            raise ExternalIntentApiError("Missing required 'well_constrained' judgment in external provider response.")
        if "probability" not in wc_info or wc_info["probability"] is None:
            raise ExternalIntentApiError("Missing required 'probability' in well_constrained judgment.")
        noul_prob = _validate_numeric(wc_info["probability"], 0.0, 1.0, "well_constrained.probability")

        # 5. Acceptance criteria presence Validation
        crit_info = answers.get("has_acceptance_criteria")
        if not isinstance(crit_info, dict):
            raise ExternalIntentApiError("Missing required 'has_acceptance_criteria' judgment in external provider response.")
        if "probability" not in crit_info or crit_info["probability"] is None:
            raise ExternalIntentApiError("Missing required 'probability' in has_acceptance_criteria judgment.")
        crit_prob = _validate_numeric(crit_info["probability"], 0.0, 1.0, "has_acceptance_criteria.probability")

        # 6. Completeness score Validation
        comp_info = answers.get("completeness")
        if not isinstance(comp_info, dict):
            raise ExternalIntentApiError("Missing required 'completeness' judgment in external provider response.")
        if "score" not in comp_info or comp_info["score"] is None:
            raise ExternalIntentApiError("Missing required 'score' in completeness judgment.")
        score_val = _validate_numeric(comp_info["score"], 1.0, 5.0, "completeness.score")

        comp_levels = None
        if comp_info.get("levels") is not None:
            comp_levels = _validate_score_levels(comp_info["levels"])

        extracted = self._extract_domain_quantities(prompt)
        inferred = [k for k in ("dimensions", "loads", "material", "acceptance_criteria") if k in extracted]

        model_tag = "external-provider-live"
        if hasattr(self.external_provider, "model"):
            model_tag = getattr(self.external_provider, "model")
        elif hasattr(self.external_provider, "__class__"):
            model_tag = self.external_provider.__class__.__name__

        return IntentDecisionBundle(
            physics_choice=ChoiceJudgment(
                phys_val,
                round(phys_conf, 3),
                phys_dist or {phys_val: phys_conf},
            ),
            unit_system_choice=ChoiceJudgment(
                unit_val,
                round(unit_conf, 3),
                unit_dist or {unit_val: unit_conf},
            ),
            solver_choice=ChoiceJudgment(
                solver_val,
                round(solver_conf, 3),
                solver_dist or {solver_val: solver_conf},
            ),
            is_well_constrained_noul=NoulJudgment(round(noul_prob, 3)),
            has_acceptance_criteria_noul=NoulJudgment(round(crit_prob, 3)),
            completeness_score=ScoreJudgment(
                round(score_val, 2),
                comp_levels or {int(round(score_val)): 1.0},
            ),
            extracted_parameters=extracted,
            source_model=model_tag,
            execution_mode="live",
            latency_ms=latency_ms,
            inferred_fields=inferred,
        )

    def _evaluate_offline_engine(self, prompt: str) -> IntentDecisionBundle:
        """High-precision deterministic System One inference engine (100% offline & reproducible)."""
        prompt_lower = prompt.lower()
        extracted = self._extract_domain_quantities(prompt)

        # 1. Physics Choice
        physics_scores: Dict[str, float] = {p: 0.05 for p in self.PHYSICS_OPTIONS}
        if any(w in prompt_lower for w in ("热", "thermal", "temperature", "conduction", "heat", "flux", "温")):
            physics_scores["steady_thermal"] += 0.85
        elif any(w in prompt_lower for w in ("接触", "contact", "friction", "摩擦", "sliding")):
            physics_scores["contact_frictional"] += 0.85
        elif any(w in prompt_lower for w in ("疲劳", "fatigue", "rainflow", "雨流", "damage", "miner")):
            physics_scores["fatigue_damage"] += 0.85
        elif any(w in prompt_lower for w in ("模态", "modal", "frequency", "固有频率", "振型")):
            physics_scores["modal_frequency"] += 0.85
        elif any(w in prompt_lower for w in ("动态", "dynamic", "transient", "冲击", "impact")):
            physics_scores["transient_dynamic"] += 0.85
        else:
            physics_scores["linear_static"] += 0.90

        total_p = sum(physics_scores.values())
        norm_physics = {k: v / total_p for k, v in physics_scores.items()}
        best_phys = max(norm_physics.items(), key=lambda kv: kv[1])
        phys_judgment = ChoiceJudgment(value=best_phys[0], confidence=round(best_phys[1], 3), distribution=norm_physics)

        # 2. Unit System Choice
        unit_scores: Dict[str, float] = {u: 0.1 for u in self.UNIT_OPTIONS}
        if any(w in prompt_lower for w in ("mpa", "mm", "n/mm", "毫米", "牛顿")):
            unit_scores["MM_N_MPA"] += 0.85
        elif any(w in prompt_lower for w in ("pa", "meter", "kg", "米")):
            unit_scores["SI"] += 0.85
        elif any(w in prompt_lower for w in ("psi", "inch", "lbf", "英寸")):
            unit_scores["IN_LBF_PSI"] += 0.85
        else:
            unit_scores["MM_N_MPA"] += 0.80

        total_u = sum(unit_scores.values())
        norm_units = {k: v / total_u for k, v in unit_scores.items()}
        best_unit = max(norm_units.items(), key=lambda kv: kv[1])
        unit_judgment = ChoiceJudgment(value=best_unit[0], confidence=round(best_unit[1], 3), distribution=norm_units)

        # 3. Solver Choice
        if best_phys[0] in ("transient_dynamic",) and ("explicit" in prompt_lower or "高速" in prompt_lower):
            solver_judgment = ChoiceJudgment(value="abaqus_explicit", confidence=0.92, distribution={"abaqus_explicit": 0.92, "abaqus_standard": 0.08})
        else:
            solver_judgment = ChoiceJudgment(value="abaqus_standard", confidence=0.96, distribution={"abaqus_standard": 0.96, "abaqus_explicit": 0.04})

        # 4. Noul: Constraints Sufficiency
        has_negated_constraint = bool(
            re.search(r"(忽略|无需|不用|没有|未|不加|不|bypass|ignore).{0,12}(约束|固定|边界|限制)", prompt_lower)
        )
        is_constrained = False
        if not has_negated_constraint:
            is_constrained = bool(
                any(w in prompt_lower for w in ("固定", "fixed", "encastre", "约束", "clamp", "pinned", "对称"))
            )
        has_load = bool(extracted.get("loads") or any(w in prompt_lower for w in ("载荷", "load", "force", "压力", "pressure", "n", "kn")))
        prob_constrained = 0.95 if is_constrained else (0.20 if has_load else 0.50)
        noul_constrained = NoulJudgment(probability=prob_constrained)

        # 5. Noul: Acceptance Criteria Presence
        has_crit = bool(
            extracted.get("acceptance_criteria")
            or any(
                w in prompt_lower
                for w in (
                    "校核",
                    "check",
                    "verify",
                    "limit",
                    "上限",
                    "不超过",
                    "应力",
                    "挠度",
                    "mises",
                    "displacement",
                    "温度",
                    "temperature",
                    "频率",
                    "frequency",
                )
            )
        )
        noul_crit = NoulJudgment(probability=0.95 if has_crit else 0.35)

        # 6. Score: Intent Completeness (1.0 to 5.0)
        score_val = 1.0
        if best_phys[0]:
            score_val += 1.0
        if extracted.get("dimensions"):
            score_val += 1.0
        if is_constrained and has_load:
            score_val += 1.0
        if has_crit or extracted.get("material"):
            score_val += 1.0
        completeness_judgment = ScoreJudgment(score=round(score_val, 1))

        return JevDecisionBundle(
            physics_choice=phys_judgment,
            unit_system_choice=unit_judgment,
            solver_choice=solver_judgment,
            is_well_constrained_noul=noul_constrained,
            has_acceptance_criteria_noul=noul_crit,
            completeness_score=completeness_judgment,
            extracted_parameters=extracted,
            source_model="offline-rule-engine-v1",
            execution_mode="offline",
            latency_ms=0.0,
            inferred_fields=list(extracted.keys()) + ["physics", "units", "solver"],
        )

    def _extract_domain_quantities(self, prompt: str) -> Dict[str, Any]:
        """Extract engineering entities (dimensions, forces, material, criteria) via typed regex."""
        params: Dict[str, Any] = {}
        prompt_lower = prompt.lower()

        # Criteria: Only extract if explicit numeric threshold is provided (Zero Fabrication)
        criteria = []
        if any(w in prompt_lower for w in ("挠度", "位移", "deflection", "displacement")):
            crit_match = re.search(r"(?:挠度|位移|deflection|displacement)[^\d]*(\d+(?:\.\d+)?)\s*(mm|inch|毫米|m(?![a-zA-Z]))?", prompt, re.IGNORECASE)
            if crit_match and crit_match.group(1):
                limit_val = float(crit_match.group(1))
                unit_val = crit_match.group(2) if crit_match.group(2) else "mm"
                criteria.append({"metric": "tip_displacement", "operator": "<=", "limit": limit_val, "unit": unit_val})
        if any(w in prompt_lower for w in ("应力", "mises", "stress")):
            stress_match = re.search(r"(?:应力|mises|stress)[^\d]*(\d+(?:\.\d+)?)\s*(mpa|kpa|pa|psi|n/mm2)?", prompt, re.IGNORECASE)
            if stress_match and stress_match.group(1):
                limit_val = float(stress_match.group(1))
                unit_val = stress_match.group(2) if stress_match.group(2) else "MPa"
                criteria.append({"metric": "max_mises", "operator": "<=", "limit": limit_val, "unit": unit_val})
        if any(w in prompt_lower for w in ("温度", "temperature")):
            temp_match = re.search(r"(?:温度|temperature)[^\d]*(\d+(?:\.\d+)?)\s*(°c|degc|deg\s*c|c|k|kelvin)?", prompt, re.IGNORECASE)
            if temp_match and temp_match.group(1):
                limit_val = float(temp_match.group(1))
                unit_val = temp_match.group(2) if temp_match.group(2) else "C"
                criteria.append({"metric": "midpoint_temperature", "operator": "==", "limit": limit_val, "unit": unit_val})
        if any(w in prompt_lower for w in ("频率", "frequency", "hz")):
            freq_match = re.search(r"(?:频率|frequency)[^\d]*(\d+(?:\.\d+)?)\s*(hz)?", prompt, re.IGNORECASE)
            if freq_match and freq_match.group(1):
                limit_val = float(freq_match.group(1))
                criteria.append({"metric": "fundamental_frequency", "operator": ">=", "limit": limit_val, "unit": "Hz"})
        if criteria:
            params["acceptance_criteria"] = criteria

        # Dimensions: e.g. 100mm, 500 mm, 2 m
        dim_matches = re.finditer(
            r"(\d+(?:\.\d+)?)\s*(mm|inch|毫米|米|m(?![a-zA-Z]))",
            prompt,
            re.IGNORECASE,
        )
        dims = []
        for m in dim_matches:
            val = float(m.group(1))
            start_pos = max(0, m.start() - 20)
            prefix = prompt[start_pos:m.start()].lower()
            if any(w in prefix for w in ("挠度", "位移", "deflection", "displacement")):
                continue
            dims.append({"value": val, "unit": m.group(2)})
        if dims:
            params["dimensions"] = dims

        # Loads: e.g. 1000N, 50kN, 2.5 MPa
        load_matches = re.findall(
            r"(\d+(?:\.\d+)?)\s*(kn|mpa|kpa|千牛|牛|n(?![a-zA-Z]))",
            prompt,
            re.IGNORECASE,
        )
        if load_matches:
            params["loads"] = [{"magnitude": float(m[0]), "unit": m[1].upper()} for m in load_matches]

        # Material detection
        if any(w in prompt_lower for w in ("结构钢", "steel", "钢", "q235")):
            params["material"] = {
                "name": "Structural_Steel",
                "elastic_modulus": 210000.0,
                "poisson_ratio": 0.3,
                "unit": "MPa",
            }
        elif any(w in prompt_lower for w in ("铝", "aluminum", "al6061")):
            params["material"] = {
                "name": "Aluminum_6061",
                "elastic_modulus": 70000.0,
                "poisson_ratio": 0.33,
                "unit": "MPa",
            }
        elif any(w in prompt_lower for w in ("橡胶", "rubber")):
            params["material"] = {
                "name": "Rubber_Hyperelastic",
                "elastic_modulus": 10.0,
                "poisson_ratio": 0.499,
                "unit": "MPa",
            }
        elif any(w in prompt_lower for w in ("elastic", "弹性")):
            params["material"] = {
                "name": "Linear_Elastic",
                "elastic_modulus": 200000.0,
                "poisson_ratio": 0.3,
                "unit": "MPa",
            }

        return params

    def _build_intent_from_decisions(
        self,
        prompt: str,
        bundle: IntentDecisionBundle,
        context: Optional[Dict[str, Any]] = None,
    ) -> EngineeringIntent:
        """Synthesize EngineeringIntent from judgments and merge upstream model context."""
        phys = bundle.physics_choice.value
        unit_sys = bundle.unit_system_choice.value
        params = bundle.extracted_parameters
        ctx = context or {}

        # Resolve Material: Prompt extracted takes precedence, fallback to model/INP context
        material = params.get("material")
        if not material and ctx.get("material"):
            ctx_mat = ctx["material"]
            if isinstance(ctx_mat, dict):
                material = ctx_mat
            elif isinstance(ctx_mat, str):
                material = {"name": ctx_mat, "source": "model_context"}
        elif not material and isinstance(ctx.get("inp_evidence"), dict) and ctx["inp_evidence"].get("material"):
            material = ctx["inp_evidence"]["material"]

        # Construct boundary conditions tuple
        bcs = []
        if bundle.is_well_constrained_noul.is_yes:
            bcs.append({"type": "encastre", "region": "FixedFace", "dofs": (1, 2, 3, 4, 5, 6)})
        elif ctx.get("boundary_conditions"):
            bcs.extend(ctx["boundary_conditions"])
        elif ctx.get("constraints") and isinstance(ctx["constraints"], (list, tuple)):
            bcs.extend(ctx["constraints"])

        # Construct loads tuple
        loads = []
        for ld in params.get("loads", []):
            mag = ld["magnitude"]
            u = ld["unit"]
            if u == "KN" or u == "千牛":
                mag *= 1000.0
                loads.append({"type": "concentrated_force", "region": "TipFace", "magnitude": mag, "direction": "-Y"})
            elif u in ("N", "牛"):
                loads.append({"type": "concentrated_force", "region": "TipFace", "magnitude": mag, "direction": "-Y"})
            elif u in ("MPA", "KPA"):
                if any(w in prompt.lower() for w in ("压力", "压强", "pressure")):
                    loads.append({"type": "pressure", "region": "TopFace", "magnitude": mag})
        if not loads and ctx.get("loads") and isinstance(ctx["loads"], (list, tuple)):
            loads.extend(ctx["loads"])

        # Construct acceptance criteria tuple
        crit_list = []
        for c in params.get("acceptance_criteria", []):
            crit_list.append({
                "name": c["metric"],
                "value_key": c["metric"],
                "operator": c["operator"],
                "limit": c["limit"],
                "unit": c.get("unit", ""),
            })
        if not crit_list and ctx.get("acceptance_criteria"):
            if isinstance(ctx["acceptance_criteria"], (list, tuple)):
                crit_list.extend(ctx["acceptance_criteria"])
            elif isinstance(ctx["acceptance_criteria"], dict):
                crit_list.append(ctx["acceptance_criteria"])

        # Resolve dimensions
        dims = params.get("dimensions") or ctx.get("dimensions") or ctx.get("geometry")

        metadata = {
            "dimensions": dims,
            "jev_source": bundle.source_model,
            "confidence": bundle.physics_choice.confidence,
            "completeness_score": bundle.completeness_score.score,
            "well_constrained": bundle.is_well_constrained_noul.is_yes or bool(bcs),
            "context_merged": bool(ctx),
        }

        return EngineeringIntent(
            id=f"INTENT-{bundle.physics_choice.value.upper()}",
            kind=phys,
            description=prompt,
            analysis_type=phys,
            unit_system=unit_sys,
            material=material,
            boundary_conditions=tuple(bcs),
            loads=tuple(loads),
            acceptance_criteria=tuple(crit_list),
            metadata=metadata,
        )

    def _build_draft_intent_from_decisions(
        self,
        prompt: str,
        bundle: IntentDecisionBundle,
        context: Optional[Dict[str, Any]] = None,
    ) -> DraftEngineeringIntent:
        """Synthesize non-executable DraftEngineeringIntent from judgments and context."""
        phys = bundle.physics_choice.value
        unit_sys = bundle.unit_system_choice.value
        params = bundle.extracted_parameters
        ctx = context or {}

        material = params.get("material")
        if not material and ctx.get("material"):
            ctx_mat = ctx["material"]
            if isinstance(ctx_mat, dict):
                material = ctx_mat
            elif isinstance(ctx_mat, str):
                material = {"name": ctx_mat, "source": "model_context"}
        elif not material and isinstance(ctx.get("inp_evidence"), dict) and ctx["inp_evidence"].get("material"):
            material = ctx["inp_evidence"]["material"]

        bcs = []
        if bundle.is_well_constrained_noul.is_yes:
            bcs.append({"type": "encastre", "region": "FixedFace", "dofs": (1, 2, 3, 4, 5, 6)})
        elif ctx.get("boundary_conditions"):
            bcs.extend(ctx["boundary_conditions"])
        elif ctx.get("constraints") and isinstance(ctx["constraints"], (list, tuple)):
            bcs.extend(ctx["constraints"])

        loads = []
        for ld in params.get("loads", []):
            mag = ld["magnitude"]
            u = ld["unit"]
            if u in ("KN", "千牛"):
                mag *= 1000.0
                loads.append({"type": "concentrated_force", "region": "TipFace", "magnitude": mag, "direction": "-Y"})
            elif u in ("N", "牛"):
                loads.append({"type": "concentrated_force", "region": "TipFace", "magnitude": mag, "direction": "-Y"})
            elif u in ("MPA", "KPA"):
                if any(w in prompt.lower() for w in ("压力", "压强", "pressure")):
                    loads.append({"type": "pressure", "region": "TopFace", "magnitude": mag})
        if not loads and ctx.get("loads") and isinstance(ctx["loads"], (list, tuple)):
            loads.extend(ctx["loads"])

        crit_list = []
        for c in params.get("acceptance_criteria", []):
            crit_list.append({
                "name": c["metric"],
                "value_key": c["metric"],
                "operator": c["operator"],
                "limit": c["limit"],
                "unit": c.get("unit", ""),
            })
        if not crit_list and ctx.get("acceptance_criteria"):
            if isinstance(ctx["acceptance_criteria"], (list, tuple)):
                crit_list.extend(ctx["acceptance_criteria"])
            elif isinstance(ctx["acceptance_criteria"], dict):
                crit_list.append(ctx["acceptance_criteria"])

        dims = params.get("dimensions") or ctx.get("dimensions") or ctx.get("geometry")

        return DraftEngineeringIntent(
            id=f"DRAFT-INTENT-{bundle.physics_choice.value.upper()}",
            kind=phys,
            description=prompt,
            analysis_type=phys,
            unit_system=unit_sys,
            material=material,
            boundary_conditions=tuple(bcs),
            loads=tuple(loads),
            acceptance_criteria=tuple(crit_list),
            metadata={
                "dimensions": dims,
                "source_model": bundle.source_model,
                "confidence": bundle.physics_choice.confidence,
                "completeness_score": bundle.completeness_score.score,
                "well_constrained": bundle.is_well_constrained_noul.is_yes or bool(bcs),
                "context_merged": bool(ctx),
            },
            is_executable=False,
        )


# Backwards compatibility alias
JevIntentRouter = EngineeringIntentRouter
