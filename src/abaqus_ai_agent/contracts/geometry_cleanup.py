"""Contracts for conservative geometry preparation before meshing."""

from dataclasses import dataclass, field
from typing import Optional, Tuple


# Abaqus APIs that mutate geometry beyond a read-only inspection. They are
# matched as substrings because the same operations are reachable both through
# typed Actions and through the generic ``python`` escape hatch, and the escape
# hatch has no structured parameters to inspect.
REPAIR_API_TOKENS = (
    "repairGeometry",
    "removeRedundantEntities",
    "healGeometry",
    "setValues(geometryRefinement",
)
VIRTUAL_TOPOLOGY_API_TOKENS = (
    "ignoreEntity",
    "restoreIgnoredEntity",
    "ignoreEntities",
)


def _action_requires_repair(action_type):
    return action_type in ("repair_geometry", "remove_redundant_entities")


def _action_requires_virtual_topology(action_type):
    return action_type in ("ignore_entity", "restore_entity")


def _action_denying_tokens(action_type, parameters, policy):
    """Return the forbidden API tokens an action would reach, given a policy.

    Typed Actions are resolved by action type. A ``python`` Action is screened by
    text because it has no structured intent; that screen can prove a violation
    but it can never prove the absence of one, so it must not be treated as an
    authorisation.
    """
    denied = []
    if _action_requires_repair(action_type) and not policy.allow_repair:
        denied.append(action_type)
    if _action_requires_virtual_topology(action_type) and not policy.allow_virtual_topology:
        denied.append(action_type)
    if action_type == "python":
        code = str((parameters or {}).get("code") or "")
        if not policy.allow_repair:
            denied.extend(token for token in REPAIR_API_TOKENS if token in code)
        if not policy.allow_virtual_topology:
            denied.extend(
                token for token in VIRTUAL_TOPOLOGY_API_TOKENS if token in code
            )
    return denied


@dataclass(frozen=True)
class GeometryIssue:
    entity_type: str
    index: Optional[int]
    issue_type: str
    severity: str
    metric: Optional[float] = None
    threshold: Optional[float] = None
    locator: Optional[Tuple[float, float, float]] = None
    recommendation: Optional[str] = None

    def __post_init__(self):
        if self.entity_type not in ("Face", "Edge", "Vertex", "Part"):
            raise ValueError("unsupported entity_type")
        if self.severity not in ("info", "warning", "error"):
            raise ValueError("invalid severity")
        if not self.issue_type:
            raise ValueError("issue_type is required")


@dataclass(frozen=True)
class GeometryInspection:
    part: str
    issues: Tuple[GeometryIssue, ...] = field(default_factory=tuple)
    valid_geometry: Optional[bool] = None
    entity_counts: Tuple[Tuple[str, int], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GeometryCleanupPolicy:
    part: str
    min_edge_length: Optional[float] = None
    min_face_size: Optional[float] = None
    inspect_geometry: bool = True
    allow_virtual_topology: bool = False
    allow_repair: bool = False

    def __post_init__(self):
        if not self.part:
            raise ValueError("part is required")
        for name in ("min_edge_length", "min_face_size"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError("%s must be positive" % name)


DEFAULT_PART = "*"


class GeometryCleanupPolicyViolation(ValueError):
    """Raised when an action would perform work the cleanup policy forbids."""

    def __init__(self, message, *, action_type, denied, policy, policy_is_default=False):
        super().__init__(message)
        self.action_type = action_type
        self.denied = tuple(denied)
        self.policy = policy
        self.policy_is_default = bool(policy_is_default)

    def to_dict(self):
        return {
            "error": "geometry_cleanup_policy_violation",
            "action_type": self.action_type,
            "denied": list(self.denied),
            "allow_repair": self.policy.allow_repair,
            "allow_virtual_topology": self.policy.allow_virtual_topology,
            "policy_parts": [self.policy.part],
            "policy_is_default": self.policy_is_default,
        }


@dataclass(frozen=True)
class GeometryCleanupPolicySet:
    """One or more cleanup policies resolved for a whole action plan.

    A caller may hand in a single policy, a sequence of policies, or nothing.
    Nothing does not mean "permissive": the default set denies repair and
    virtual topology, and records that the default was applied so the decision
    stays auditable instead of inverting silently.
    """

    policies: Tuple[GeometryCleanupPolicy, ...] = ()
    is_default: bool = False

    @classmethod
    def default(cls):
        return cls(
            (GeometryCleanupPolicy(part=DEFAULT_PART),),
            is_default=True,
        )

    @classmethod
    def coerce(cls, policies=None):
        if policies is None:
            return cls.default()
        if isinstance(policies, GeometryCleanupPolicy):
            return cls((policies,), False)
        if isinstance(policies, GeometryCleanupPolicySet):
            return policies
        items = tuple(policies)
        if not items:
            return cls.default()
        for item in items:
            if not isinstance(item, GeometryCleanupPolicy):
                raise TypeError("expected GeometryCleanupPolicy instances")
        return cls(items, False)

    def policy_for(self, part):
        """Return the effective policy for ``part``.

        An exact part match wins. Otherwise the wildcard policy applies. The most
        restrictive policy among all matches governs, so adding policies can
        never widen permission by accident.
        """
        matches = [
            p for p in self.policies
            if p.part == part or p.part == DEFAULT_PART
        ]
        if not matches:
            return GeometryCleanupPolicy(
                part=part or DEFAULT_PART,
                allow_repair=False,
                allow_virtual_topology=False,
            )
        exact = [p for p in matches if p.part == part]
        candidates = exact or matches
        return GeometryCleanupPolicy(
            part=part or DEFAULT_PART,
            min_edge_length=min(
                (p.min_edge_length for p in candidates if p.min_edge_length is not None),
                default=None,
            ),
            min_face_size=min(
                (p.min_face_size for p in candidates if p.min_face_size is not None),
                default=None,
            ),
            inspect_geometry=all(p.inspect_geometry for p in candidates),
            allow_virtual_topology=all(p.allow_virtual_topology for p in candidates),
            allow_repair=all(p.allow_repair for p in candidates),
        )


_TRIGGERING_ACTION_TYPES = (
    "inspect_geometry",
    "ignore_entity",
    "restore_entity",
    "repair_geometry",
    "remove_redundant_entities",
)


def _screen_action(action, policies):
    """Return ``(policy, denied)`` for one action.

    Only actions that can reach a geometry-mutating API are screened; every other
    action is left untouched so the choke point stays cheap and predictable.
    """
    action_type = getattr(action, "action_type", None)
    parameters = getattr(action, "parameters", None) or {}
    if action_type not in _TRIGGERING_ACTION_TYPES and action_type != "python":
        return None, ()
    if action_type == "python":
        code = str(parameters.get("code") or "")
        reaches_repair = any(token in code for token in REPAIR_API_TOKENS)
        reaches_vt = any(token in code for token in VIRTUAL_TOPOLOGY_API_TOKENS)
        if not reaches_repair and not reaches_vt:
            return None, ()
        # A free-form snippet may touch any part; screen it against every policy.
        parts = [p.part for p in policies.policies] or [DEFAULT_PART]
        denied = []
        governing = GeometryCleanupPolicy(part=DEFAULT_PART)
        for part in parts:
            policy = policies.policy_for(part)
            denied.extend(_action_denying_tokens(action_type, parameters, policy))
            governing = policy
        return governing, tuple(dict.fromkeys(denied))

    part = str(parameters.get("part") or "")
    policy = policies.policy_for(part)
    return policy, tuple(_action_denying_tokens(action_type, parameters, policy))


def enforce_cleanup_policy(action, policies=None):
    """Single choke point for the geometry cleanup policy (fail-closed).

    Every caller that is about to turn an Action into Abaqus script passes
    through here. When the effective policy forbids the operation, a
    :class:`GeometryCleanupPolicyViolation` is raised and no script is produced.

    The ``python`` escape hatch is text-screened for the mutating APIs. That
    screen can prove a violation but cannot prove its absence, so a passing
    snippet is never recorded as evidence that a repair policy was satisfied.
    """
    resolved = GeometryCleanupPolicySet.coerce(policies)
    if not isinstance(action, object) or not getattr(action, "action_type", None):
        raise TypeError("expected an action with action_type")
    policy, denied = _screen_action(action, resolved)
    if denied:
        raise GeometryCleanupPolicyViolation(
            "geometry cleanup policy forbids %s: %s"
            % (getattr(action, "action_type", "?"), ", ".join(denied)),
            action_type=getattr(action, "action_type", None),
            denied=denied,
            policy=policy,
            policy_is_default=resolved.is_default,
        )
    return policy


@dataclass(frozen=True)
class GeometryCleanupAction:
    operation: str
    part: str
    region_expression: Optional[str] = None
    parameters: dict = field(default_factory=dict)
    requires_confirmation: bool = True

    def __post_init__(self):
        if self.operation not in (
            "inspect_geometry", "ignore_entity", "restore_entity",
            "repair_geometry", "remove_redundant_entities"
        ):
            raise ValueError("unsupported geometry cleanup operation")
        if not self.part:
            raise ValueError("part is required")
        if self.operation in ("ignore_entity", "restore_entity") and not self.region_expression:
            raise ValueError("region_expression is required")


def verify_cleanup_transition(before, after, operation):
    """Compare two inspection dictionaries and fail closed on missing post evidence.

    Returns a deterministic dictionary suitable for Evidence/ExecutionJournal.
    It never assumes that a repair succeeded merely because the Abaqus command returned.
    """
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError("before and after inspections must be dictionaries")
    if before.get("part") != after.get("part"):
        raise ValueError("before/after inspections refer to different parts")
    if operation in ("repair_geometry", "remove_redundant_entities", "ignore_entity", "restore_entity"):
        required = ("entity_counts", "issues", "valid_geometry")
        missing = [key for key in required if key not in after]
        if missing:
            return {"verified": False, "reason": "missing_post_inspection:" + ",".join(missing)}
    before_issues = len(before.get("issues") or ())
    after_issues = len(after.get("issues") or ())
    before_counts = before.get("entity_counts") or {}
    after_counts = after.get("entity_counts") or {}
    changed = before_issues != after_issues or before_counts != after_counts or before.get("valid_geometry") != after.get("valid_geometry")
    return {
        "verified": bool(changed),
        "changed": bool(changed),
        "operation": operation,
        "part": after.get("part"),
        "issues_before": before_issues,
        "issues_after": after_issues,
        "entity_counts_before": before_counts,
        "entity_counts_after": after_counts,
        "valid_geometry_before": before.get("valid_geometry"),
        "valid_geometry_after": after.get("valid_geometry"),
        "reason": "post_inspection_diff_detected" if changed else "no_observable_change",
    }
