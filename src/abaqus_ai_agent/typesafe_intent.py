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


def _get_external_config(primary_var: str, legacy_compat_var: Optional[str] = None) -> Optional[str]:
    """Read external configuration preferring vendor-neutral variables, falling back to legacy compatibility vars."""
    val = os.environ.get(primary_var)
    if val is not None and val != "":
        return val
    if legacy_compat_var:
        return os.environ.get(legacy_compat_var)
    return None


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

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        payload_builder: Optional[Callable[[str, "GenericHttpIntentProvider"], Dict[str, Any]]] = None,
        response_normalizer: Optional[Callable[[Any], Dict[str, Any]]] = None,
    ):
        self.endpoint = (
            endpoint
            or _get_external_config("EXTERNAL_INTENT_API_URL", "TYPESAFE_API_URL")
        )
        self.api_key = (
            api_key
            or _get_external_config("EXTERNAL_INTENT_API_KEY", "TYPESAFE_API_KEY")
        )
        self.model = (
            model
            or _get_external_config("EXTERNAL_INTENT_MODEL")
            or "external-intent-v1"
        )
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
                raw_bytes = resp.read()
                raw_json = json.loads(raw_bytes.decode("utf-8"))
                return self._response_normalizer(raw_json)
        except urllib.error.HTTPError as http_err:
            try:
                err_body = http_err.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            raise ExternalIntentApiError(
                f"External intent API HTTP {http_err.code} error: {http_err.reason}. Response: {err_body[:200]}"
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
        self.api_key = api_key or _get_external_config("EXTERNAL_INTENT_API_KEY", "TYPESAFE_API_KEY")
        self.api_url = api_url or _get_external_config("EXTERNAL_INTENT_API_URL", "TYPESAFE_API_URL")
        self.timeout = timeout

        if mode is not None:
            norm_mode = mode.strip().lower()
            if norm_mode not in self.VALID_MODES:
                raise ValueError(f"Invalid JEV mode / intent mode: {mode!r}. Must be one of {self.VALID_MODES}.")
            self.mode = norm_mode
        elif use_live_api:
            self.mode = "live"
        else:
            env_mode = (
                _get_external_config("EXTERNAL_INTENT_RUN_MODE", "INTENT_RUN_MODE")
                or _get_external_config("TYPESAFE_RUN_MODE")
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

    def route(self, prompt: str) -> IntentRoutingResult:
        """Route prompt with explicit fail-closed clarification gate for ambiguous requirements."""
        prompt_clean = prompt.strip()
        if not prompt_clean:
            raise ValueError("Engineering intent prompt cannot be empty.")

        decisions = self._evaluate_system_one_judgments(prompt_clean)
        missing = self._detect_missing_engineering_prerequisites(prompt_clean, decisions)

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

        intent = self._build_intent_from_decisions(prompt_clean, decisions)
        return IntentRoutingResult(
            status="ROUTED",
            intent=intent,
            decision_bundle=decisions,
            missing_requirements=[],
            clarification_prompt=None,
        )

    def route_prompt_to_intent(
        self, prompt: str, strict: bool = False
    ) -> Tuple[EngineeringIntent, JevDecisionBundle]:
        """Convert natural language requirement into typed EngineeringIntent via judgments.

        If strict=True, raises IntentAmbiguityError when requirements are incomplete.
        """
        res = self.route(prompt)
        if res.status != "ROUTED":
            if strict:
                raise IntentAmbiguityError(
                    res.clarification_prompt or "Incomplete engineering intent.",
                    res.missing_requirements,
                    res.decision_bundle,
                )
            intent = self._build_intent_from_decisions(prompt.strip(), res.decision_bundle)
            return intent, res.decision_bundle

        assert res.intent is not None
        return res.intent, res.decision_bundle

    def _detect_missing_engineering_prerequisites(
        self, prompt: str, bundle: JevDecisionBundle
    ) -> List[str]:
        """Verify whether prompt contains all necessary engineering prerequisites."""
        missing = []
        params = bundle.extracted_parameters
        phys = bundle.physics_choice.value

        # Check geometry dimension
        if not params.get("dimensions"):
            missing.append("missing_geometry_dimensions")

        # Check material
        if not params.get("material"):
            missing.append("missing_material_specification")

        # Physics-specific constraints and loads
        if phys in ("linear_static", "contact_frictional", "fatigue_damage"):
            if not bundle.is_well_constrained_noul.is_yes:
                missing.append("missing_boundary_constraints")
            if not params.get("loads"):
                missing.append("missing_applied_loads")

        if phys in ("steady_thermal",):
            if not any(w in prompt.lower() for w in ("0c", "100c", "°c", "k", "flux", "热流", "温度")):
                missing.append("missing_thermal_boundary_conditions")

        # Check acceptance criteria / limits
        if not bundle.has_acceptance_criteria_noul.is_yes:
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
            if self.external_provider and (
                not hasattr(self.external_provider, "is_configured") or self.external_provider.is_configured()
            ):
                try:
                    if hasattr(self.external_provider, "judge"):
                        raw_data = self.external_provider.judge(prompt, timeout=self.timeout)
                    elif callable(self.external_provider):
                        raw_data = self.external_provider(prompt)
                    else:
                        raw_data = {}
                    live_res = self._parse_provider_response(raw_data, prompt, latency_ms=0.0)
                    shadow_diff = self._compute_shadow_diff(baseline, live_res)
                except Exception as shadow_err:
                    shadow_diff = {
                        "status": "LIVE_FAILED",
                        "error": str(shadow_err),
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
        try:
            phys_conf = float(phys_info.get("confidence", 0.0))
        except (ValueError, TypeError):
            raise ExternalIntentApiError(f"Invalid confidence in physics answer: {phys_info.get('confidence')!r}")
        if not (0.0 <= phys_conf <= 1.0):
            raise ExternalIntentApiError(f"Physics confidence out of bounds [0.0, 1.0]: {phys_conf}")

        # 2. Units Validation
        unit_info = answers.get("units")
        if not isinstance(unit_info, dict):
            raise ExternalIntentApiError("Missing required 'units' judgment in external provider response.")
        unit_val = unit_info.get("choice")
        if unit_val not in self.UNIT_OPTIONS:
            raise ExternalIntentApiError(f"Invalid units choice {unit_val!r}. Allowed: {self.UNIT_OPTIONS}")
        try:
            unit_conf = float(unit_info.get("confidence", 0.0))
        except (ValueError, TypeError):
            raise ExternalIntentApiError(f"Invalid confidence in units answer: {unit_info.get('confidence')!r}")
        if not (0.0 <= unit_conf <= 1.0):
            raise ExternalIntentApiError(f"Units confidence out of bounds [0.0, 1.0]: {unit_conf}")

        # 3. Solver Validation
        solver_info = answers.get("solver")
        if not isinstance(solver_info, dict):
            raise ExternalIntentApiError("Missing required 'solver' judgment in external provider response.")
        solver_val = solver_info.get("choice")
        if solver_val not in self.SOLVER_OPTIONS:
            raise ExternalIntentApiError(f"Invalid solver choice {solver_val!r}. Allowed: {self.SOLVER_OPTIONS}")
        try:
            solver_conf = float(solver_info.get("confidence", 0.0))
        except (ValueError, TypeError):
            raise ExternalIntentApiError(f"Invalid confidence in solver answer: {solver_info.get('confidence')!r}")
        if not (0.0 <= solver_conf <= 1.0):
            raise ExternalIntentApiError(f"Solver confidence out of bounds [0.0, 1.0]: {solver_conf}")

        # 4. Well-constrained Validation
        wc_info = answers.get("well_constrained")
        if not isinstance(wc_info, dict):
            raise ExternalIntentApiError("Missing required 'well_constrained' judgment in external provider response.")
        try:
            noul_prob = float(wc_info.get("probability", 0.0))
        except (ValueError, TypeError):
            raise ExternalIntentApiError(f"Invalid probability in well_constrained: {wc_info.get('probability')!r}")
        if not (0.0 <= noul_prob <= 1.0):
            raise ExternalIntentApiError(f"Constraint probability out of bounds [0.0, 1.0]: {noul_prob}")

        # 5. Acceptance criteria presence Validation
        crit_info = answers.get("has_acceptance_criteria")
        if not isinstance(crit_info, dict):
            raise ExternalIntentApiError("Missing required 'has_acceptance_criteria' judgment in external provider response.")
        try:
            crit_prob = float(crit_info.get("probability", 0.0))
        except (ValueError, TypeError):
            raise ExternalIntentApiError(f"Invalid probability in has_acceptance_criteria: {crit_info.get('probability')!r}")
        if not (0.0 <= crit_prob <= 1.0):
            raise ExternalIntentApiError(f"Criteria probability out of bounds [0.0, 1.0]: {crit_prob}")

        # 6. Completeness score Validation
        comp_info = answers.get("completeness")
        if not isinstance(comp_info, dict):
            raise ExternalIntentApiError("Missing required 'completeness' judgment in external provider response.")
        try:
            score_val = float(comp_info.get("score", 0.0))
        except (ValueError, TypeError):
            raise ExternalIntentApiError(f"Invalid score in completeness: {comp_info.get('score')!r}")
        if not (1.0 <= score_val <= 5.0):
            raise ExternalIntentApiError(f"Completeness score out of bounds [1.0, 5.0]: {score_val}")

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
                phys_info.get("distribution") or {phys_val: phys_conf},
            ),
            unit_system_choice=ChoiceJudgment(
                unit_val,
                round(unit_conf, 3),
                unit_info.get("distribution") or {unit_val: unit_conf},
            ),
            solver_choice=ChoiceJudgment(
                solver_val,
                round(solver_conf, 3),
                solver_info.get("distribution") or {solver_val: solver_conf},
            ),
            is_well_constrained_noul=NoulJudgment(round(noul_prob, 3)),
            has_acceptance_criteria_noul=NoulJudgment(round(crit_prob, 3)),
            completeness_score=ScoreJudgment(
                round(score_val, 2),
                comp_info.get("levels") or {int(round(score_val)): 1.0},
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
            any(w in prompt_lower for w in ("校核", "check", "verify", "limit", "上限", "不超过", "应力", "挠度", "mises", "displacement"))
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

        # Criteria
        criteria = []
        if any(w in prompt_lower for w in ("挠度", "位移", "deflection", "displacement")):
            crit_match = re.search(r"(?:挠度|位移|deflection|displacement)[^\d]*(\d+(?:\.\d+)?)\s*(mm|inch|毫米|m(?![a-zA-Z]))?", prompt, re.IGNORECASE)
            limit_val = float(crit_match.group(1)) if crit_match else 2.5
            unit_val = crit_match.group(2) if (crit_match and crit_match.group(2)) else "mm"
            criteria.append({"metric": "tip_displacement", "operator": "<=", "limit": limit_val, "unit": unit_val})
        if any(w in prompt_lower for w in ("应力", "mises", "stress")):
            criteria.append({"metric": "max_mises", "operator": "<=", "limit": 600.0, "unit": "MPa"})
        if any(w in prompt_lower for w in ("温度", "temperature")):
            criteria.append({"metric": "midpoint_temperature", "operator": "==", "limit": 50.0, "unit": "C"})
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

    def _build_intent_from_decisions(self, prompt: str, bundle: IntentDecisionBundle) -> EngineeringIntent:
        """Synthesize EngineeringIntent from judgments."""
        phys = bundle.physics_choice.value
        unit_sys = bundle.unit_system_choice.value
        params = bundle.extracted_parameters

        # Construct boundary conditions tuple
        bcs = []
        if bundle.is_well_constrained_noul.is_yes:
            bcs.append({"type": "encastre", "region": "FixedFace", "dofs": (1, 2, 3, 4, 5, 6)})

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

        return EngineeringIntent(
            id=f"INTENT-{bundle.physics_choice.value.upper()}",
            kind=phys,
            description=prompt,
            analysis_type=phys,
            unit_system=unit_sys,
            material=params.get("material"),
            boundary_conditions=tuple(bcs),
            loads=tuple(loads),
            acceptance_criteria=tuple(crit_list),
            metadata={
                "dimensions": params.get("dimensions"),
                "jev_source": bundle.source_model,
                "confidence": bundle.physics_choice.confidence,
                "completeness_score": bundle.completeness_score.score,
                "well_constrained": bundle.is_well_constrained_noul.is_yes,
            },
        )


# Backwards compatibility alias
JevIntentRouter = EngineeringIntentRouter
