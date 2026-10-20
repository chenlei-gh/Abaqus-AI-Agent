"""Contracts for conservative geometry preparation before meshing.

Two layers enforce the same policy:

1. A static screen at script-generation time. It can prove a violation, but it
   can never prove the absence of one, so it is a pre-check and not evidence.
2. A runtime guard emitted into the generated script. It registers an Abaqus
   ``methodCallback`` on ``ALL_TYPES`` and raises *before* a denied call mutates
   geometry. This is the layer that actually holds: it also catches calls built
   with ``getattr`` concatenation, ``eval``, alias binding or an indirect
   wrapper, because attribution happens at the call site inside Abaqus.

The method names below come from the Abaqus 2025 ``Part`` API surface. Older
spellings are retained so screens still recognise decks written against them.
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple


# Abaqus Part APIs that mutate geometry beyond a read-only inspection. Text
# screening matches these as substrings because a ``python`` Action has no
# structured intent to inspect.
REPAIR_API_TOKENS = (
    # Abaqus 2025 API surface (verified on a real installation).
    ".repair",
    "removeInvalidGeometry",
    "CreateHealedPart",
    "writeHealedPart",
    # Legacy spellings: absent in 2025 but still worth screening.
    "repairGeometry",
    "removeRedundantEntities",
    "healGeometry",
)
VIRTUAL_TOPOLOGY_API_TOKENS = (
    "ignoreEntity",
    "ignoreEntities",
    "restoreIgnoredEntity",
    "createVirtualTopology",
)

# Geometry-preparation tolerances do not delete or merge topological entities,
# so they are not repair-class denials. They do change how the mesh is built, so
# a script that sets them is recorded rather than silently ignored.
TOLERANCE_API_TOKENS = (
    "geometryRefinement",
    "geometryPrecision",
)

GEOMETRY_GUARD_SENTINEL = "__ABQAI_GEOMETRY_GUARD__"

REPAIR_MUTATORS = (
    "repair",
    "removeInvalidGeometry",
    "CreateHealedPart",
    "writeHealedPart",
    "repairGeometry",
    "removeRedundantEntities",
    "healGeometry",
)
VIRTUAL_TOPOLOGY_MUTATORS = (
    "ignoreEntity",
    "ignoreEntities",
    "restoreIgnoredEntity",
    "createVirtualTopology",
)
# Mutators whose names exist only on ``Part``. When the guard cannot attribute a
# call to a part it still blocks these, because there is no other object they can
# legitimately belong to. ``repair`` is left out: it is a generic name and could
# belong to unrelated Abaqus types.
UNATTRIBUTED_BLOCKED_MUTATORS = VIRTUAL_TOPOLOGY_MUTATORS + (
    "removeInvalidGeometry",
    "CreateHealedPart",
    "writeHealedPart",
    "repairGeometry",
    "removeRedundantEntities",
    "healGeometry",
)


_GUARD_TEMPLATE = '''# --- abaqus-ai-agent geometry cleanup guard (generated; idempotent) ---
def _abqai_install_geometry_guard():
    import sys as _abqai_sys
    _policies = @@POLICIES@@
    _state = getattr(_abqai_sys, "@@SENTINEL@@", None)
    if _state is None:
        _state = {
            "installed": False,
            "policies": {},
            "violations": [],
            "tolerance_changes": [],
            "registration_errors": [],
            "registered": [],
            "callback": None,
            "module": None,
            "tamper_events": [],
        }
        setattr(_abqai_sys, "@@SENTINEL@@", _state)
    # One callback stays registered for the life of the CAE session and always
    # consults the newest policy. Re-registering per script would mean removing
    # the previous callback first, and Abaqus removal proved unreliable when the
    # callback had already blocked a call.
    _state["policies"] = _policies
    _repair_names = @@REPAIR@@
    _vt_names = @@VT@@
    _unique_names = @@UNIQUE@@
    _mutators = {}
    for _n in _repair_names:
        _mutators[_n] = "repair"
    for _n in _vt_names:
        _mutators[_n] = "virtual_topology"

    def _part_name(_text):
        if ".parts[" not in _text:
            return None
        _tail = _text.split(".parts[", 1)[1]
        if "]" not in _tail:
            return None
        return _tail.split("]", 1)[0].strip().strip("'\\"")

    def _spec_for(_part):
        _now = _state["policies"]
        _found = _now.get(_part)
        if _found is None:
            _found = _now.get("*")
        return _found

    def _guard(_method, _args, _kargs, _userData):
        _text = repr(_method)
        _name = _text.rsplit(".", 1)[-1].split(">")[0].strip() if "." in _text else ""
        _kind = _mutators.get(_name)
        if _kind is None:
            return None
        _part = _part_name(_text)
        if _part is None:
            if _name not in _unique_names:
                return None
            _state["violations"].append({"part": None, "method": _name, "kind": _kind})
            raise RuntimeError(
                "abaqus-ai-agent geometry cleanup policy could not attribute %s to a part "
                "and refused to run it" % _name
            )
        _entry = _spec_for(_part)
        _allowed = bool(_entry.get(_kind, False)) if _entry is not None else False
        if _allowed:
            return None
        _state["violations"].append({"part": _part, "method": _name, "kind": _kind})
        raise RuntimeError(
            "abaqus-ai-agent geometry cleanup policy forbids %s on part %r (kind=%s); "
            "the call was blocked before it could change geometry"
            % (_name, _part, _kind)
        )

    _enforcement_needed = True
    if _policies:
        _enforcement_needed = any(
            (not bool(_entry.get("repair", False)))
            or (not bool(_entry.get("virtual_topology", False)))
            for _entry in _policies.values()
        )

    _mc = None
    try:
        import methodCallback as _mc_module
        _mc = _mc_module
    except Exception as _exc:
        _state["registration_errors"].append(["import:methodCallback", repr(_exc)])
    if _mc is not None:
        _state["module"] = _mc
        if _state["callback"] is None:
            _state["callback"] = _guard
        _cb = _state["callback"]
        _state["registered"] = []
        for _name in list(_mutators):
            _present = False
            try:
                _present = bool(_mc.callbackExists(_mc.ALL_TYPES, _name, _cb))
            except Exception as _exc:
                _state["registration_errors"].append(["exists:%s" % _name, repr(_exc)])
            if _present:
                _state["registered"].append(_name)
                continue
            try:
                _mc.addCallback(_mc.ALL_TYPES, _name, _cb)
                _state["registered"].append(_name)
            except Exception as _exc:
                _state["registration_errors"].append([_name, repr(_exc)])
    if _enforcement_needed:
        _unregistered = [
            _name for _name in _mutators
            if _name not in _state["registered"]
        ]
        if _unregistered:
            raise RuntimeError(
                "abaqus-ai-agent cannot enforce the geometry cleanup policy: "
                "one or more required mutator callbacks failed to register: %r (errors: %r)"
                % (_unregistered, _state["registration_errors"])
            )
    _state["installed"] = True
    return _state

_abqai_geometry_guard = _abqai_install_geometry_guard()
for _abqai_record in @@TOLERANCE@@:
    if _abqai_record not in _abqai_geometry_guard["tolerance_changes"]:
        _abqai_geometry_guard["tolerance_changes"].append(_abqai_record)
'''


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


def _policy_payload(policies):
    """Serialise resolved policies for the runtime guard.

    Every policy in the set is emitted by part name plus the wildcard entry, so
    the guard can resolve the effective policy for a part it only learns about
    at call time. A part with no matching entry falls back to the wildcard, and
    a missing wildcard denies, matching :meth:`GeometryCleanupPolicySet.policy_for`.
    """
    payload = {}
    for policy in policies.policies:
        payload[policy.part] = {
            "repair": bool(policy.allow_repair),
            "virtual_topology": bool(policy.allow_virtual_topology),
        }
    return payload


def render_geometry_guard(policies=None, code=""):
    """Return the guard prelude that must precede generated Abaqus script.

    ``policies`` is the same value accepted by :func:`enforce_cleanup_policy`.
    The prelude is idempotent: including it twice leaves one registration set.

    ``code`` is only used to record geometry-preparation tolerance changes, which
    are allowed but must stay visible in the evidence trail.

    Security boundary note:
    The guard operates within the same Abaqus Python interpreter to enforce policy
    during normal workflow execution and prevent accidental or unvetted geometry
    mutations. It does not act as an OS sandbox against actively adversarial scripts
    running inside the same interpreter process (e.g., scripts intentionally unhooking
    callbacks or modifying interpreter internals). Strong containment of untrusted
    code requires process-level or OS-level isolation.
    """
    resolved = GeometryCleanupPolicySet.coerce(policies)
    payload = _policy_payload(resolved)
    tolerance = sorted(
        {token for token in TOLERANCE_API_TOKENS if token in str(code or "")}
    )
    # ``repair`` is itself a ``Part`` method name that generic objects also use,
    # so it is only blocked when the call can be attributed to a known part.
    unique = tuple(
        name
        for name in UNATTRIBUTED_BLOCKED_MUTATORS
        if name != "repair"
    )
    return _GUARD_TEMPLATE.replace("@@SENTINEL@@", GEOMETRY_GUARD_SENTINEL).replace(
        "@@POLICIES@@", repr(payload)
    ).replace("@@REPAIR@@", repr(tuple(REPAIR_MUTATORS))).replace(
        "@@VT@@", repr(tuple(VIRTUAL_TOPOLOGY_MUTATORS))
    ).replace("@@UNIQUE@@", repr(unique)).replace("@@TOLERANCE@@", repr(tuple(tolerance)))


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
    screen can prove a violation but cannot prove its absence, so it is only a
    pre-check. The layer that actually constrains a free-form snippet is the
    runtime guard from :func:`render_geometry_guard`, which must be emitted
    ahead of any script that carries a ``python`` Action or a geometry mutation.
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

    ``valid_geometry`` may legitimately be ``None`` when the inspection could not
    decide. A value that is unknown before *and* after is not evidence that
    anything changed, and a value that only moves from ``None`` to ``True`` is
    not evidence either: ``checkGeometry`` reports failures by raising, so a
    constant ``True`` must not be treated as a positive result.
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
    validity_before = before.get("valid_geometry")
    validity_after = after.get("valid_geometry")
    validity_supported = validity_before is not None and validity_after is not None
    changed = (
        before_issues != after_issues
        or before_counts != after_counts
        or (validity_supported and validity_before != validity_after)
    )
    result = {
        "verified": bool(changed),
        "changed": bool(changed),
        "operation": operation,
        "part": after.get("part"),
        "issues_before": before_issues,
        "issues_after": after_issues,
        "entity_counts_before": before_counts,
        "entity_counts_after": after_counts,
        "valid_geometry_before": validity_before,
        "valid_geometry_after": validity_after,
        "reason": "post_inspection_diff_detected" if changed else "no_observable_change",
    }
    if not validity_supported:
        result["validity_conclusive"] = False
    return result


STATUS_REPAIR_FORBIDDEN_FAIL_CLOSED = "REPAIR_FORBIDDEN_FAIL_CLOSED"
STATUS_REPAIR_AUTHORIZED = "REPAIR_AUTHORIZED"
STATUS_CLEAN = "CLEAN"
STATUS_WARNING = "WARNING"


def evaluate_geometry_cleanup_intent(
    inspection: GeometryInspection,
    policy: Optional[GeometryCleanupPolicy] = None,
) -> dict:
    """Evaluate inspection findings against cleanup policy in a fail-closed manner.

    When geometric flaws (severity == 'error' or valid_geometry is False) are
    detected and the policy has not explicitly set allow_repair=True, this function
    returns status='REPAIR_FORBIDDEN_FAIL_CLOSED'. Destructive geometry modifications
    are strictly barred, and structured diagnostics with exact locators and actionable
    engineering recommendations are provided. Virtual topology candidates are kept
    strictly review-only.
    """
    if not isinstance(inspection, GeometryInspection):
        raise TypeError(f"expected GeometryInspection, got {type(inspection).__name__}")

    effective_policy = policy
    if effective_policy is None:
        effective_policy = GeometryCleanupPolicy(
            part=inspection.part or DEFAULT_PART,
            allow_repair=False,
            allow_virtual_topology=False,
        )

    issues = inspection.issues or ()
    error_issues = [iss for iss in issues if iss.severity == "error"]
    warning_issues = [iss for iss in issues if iss.severity == "warning"]
    info_issues = [iss for iss in issues if iss.severity == "info"]

    has_error = bool(error_issues) or (inspection.valid_geometry is False)

    diagnostics = []
    recommendations = []
    for iss in issues:
        item = {
            "entity_type": iss.entity_type,
            "index": iss.index,
            "issue_type": iss.issue_type,
            "severity": iss.severity,
            "metric": iss.metric,
            "threshold": iss.threshold,
            "locator": iss.locator,
            "recommendation": iss.recommendation,
        }
        diagnostics.append(item)
        if iss.recommendation and iss.recommendation not in recommendations:
            recommendations.append(iss.recommendation)

    if inspection.valid_geometry is False and not any(iss.issue_type == "invalid_geometry" for iss in error_issues):
        rec = "Invalid geometry detected by Abaqus kernel; manual CAD inspection required."
        diagnostics.append({
            "entity_type": "Part",
            "index": None,
            "issue_type": "invalid_geometry",
            "severity": "error",
            "metric": None,
            "threshold": None,
            "locator": None,
            "recommendation": rec,
        })
        if rec not in recommendations:
            recommendations.append(rec)

    if has_error:
        if not effective_policy.allow_repair:
            status = STATUS_REPAIR_FORBIDDEN_FAIL_CLOSED
            action_permitted = False
            summary = "Destructive geometry repair is barred (allow_repair=False); fail-closed diagnosis emitted."
        else:
            status = STATUS_REPAIR_AUTHORIZED
            action_permitted = True
            summary = "Geometry repair is explicitly authorized by policy."
    elif warning_issues:
        status = STATUS_WARNING
        action_permitted = False
        summary = "Geometric warnings found; review recommended before meshing."
    else:
        status = STATUS_CLEAN
        action_permitted = False
        summary = "Geometry inspection passed with no detected errors or warnings."

    return {
        "status": status,
        "part": inspection.part,
        "action_permitted": action_permitted,
        "allow_repair": effective_policy.allow_repair,
        "allow_virtual_topology": effective_policy.allow_virtual_topology,
        "valid_geometry": inspection.valid_geometry,
        "error_count": len(error_issues) + (1 if inspection.valid_geometry is False and not any(iss.issue_type == "invalid_geometry" for iss in error_issues) else 0),
        "warning_count": len(warning_issues),
        "info_count": len(info_issues),
        "diagnostics": diagnostics,
        "recommendations": recommendations,
        "summary": summary,
    }
