"""Contact-level stabilization contract for Abaqus/Standard surface interactions.

Why this module exists
----------------------
Step-level automatic stabilization (``*STATIC, STABILIZE``) and contact-level
stabilization (``*CONTACT CONTROLS ..., STABILIZE=``) are different control
paths. Treating them as one bag let a diagnosis report ``contact_damping=True``
while no contact object ever received the setting, so the repair claimed to be
applied but nothing reached the solver.

What Abaqus 2025 actually accepts (verified on the installed release)
--------------------------------------------------------------------
``model.StdContactControl(name, stabilizeChoice=AUTOMATIC, dampFactor=...)``
creates the control object, and ``SurfaceToSurfaceContactStd(...,
contactControls=<name>)`` binds it to an interaction. The emitted deck carries
``*Contact Controls, main=..., secondary=..., stabilize=<dampFactor>``.

Three hard constraints are enforced here because Abaqus rejects them at runtime:

1. ``Contact control cannot be specified in initial step`` -- a contact created
   in ``Initial`` cannot take controls at creation. The supported path is
   ``<interaction>.setValuesInStep(stepName=<step>, contactControls=<name>)``,
   which emits a ``*Contact Controls, reset`` pair followed by the new setting.
2. Contact stabilization is a Standard (implicit) capability. ``ExplicitDynamicsStep``
   raises ``The specified type of interaction cannot be created or resumed in
   this type of step``.
3. ``stabilizeChoice`` only accepts ``NONE`` / ``AUTOMATIC``. ``FRICTIONAL`` is
   not a constant in this release, and ``DAMPING_FACTOR`` belongs to
   ``StaticStep.stabilizationMethod``, not to the contact control object.

Anything that cannot be resolved to exactly one target step raises instead of
silently degrading to an ordinary contact.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

DEFAULT_CONTACT_CONTROL_NAME = "CC-Stabilization"

STABILIZE_NONE = "NONE"
STABILIZE_AUTOMATIC = "AUTOMATIC"
SUPPORTED_STABILIZE_CHOICES = (STABILIZE_NONE, STABILIZE_AUTOMATIC)

# ``SurfaceToSurfaceContactStd`` is the only interaction type the compiler emits.
SUPPORTED_INTERACTION_TYPES = ("surface_to_surface_contact",)

# Contact stabilization binding is verified on the installed Abaqus 2025 for
# Standard static steps only. Implicit dynamic and explicit dynamic are refused
# rather than assumed to behave identically.
SUPPORTED_TARGET_PROCEDURES = ("static", "static_general")

# Contact stabilization is not available in these procedures.
UNSUPPORTED_PROCEDURES = ("explicit_dynamic", "dynamic_explicit", "frequency", "implicit_dynamic")

INITIAL_STEP = "Initial"


class ContactStabilizationError(ValueError):
    """Raised when contact stabilization cannot be bound to exactly one target."""


@dataclass(frozen=True)
class ContactStabilizationSpec:
    """Declarative request to stabilize one contact interaction in one step."""

    stabilize_choice: str = STABILIZE_AUTOMATIC
    damp_factor: Optional[float] = None
    damp_coef: Optional[float] = 0.0
    target_step: Optional[str] = None
    control_name: str = DEFAULT_CONTACT_CONTROL_NAME

    def __post_init__(self) -> None:
        choice = str(self.stabilize_choice or STABILIZE_AUTOMATIC).upper()
        if choice not in SUPPORTED_STABILIZE_CHOICES:
            raise ContactStabilizationError(
                "unsupported contact stabilizeChoice %r; Abaqus 2025 accepts %s"
                % (self.stabilize_choice, ", ".join(SUPPORTED_STABILIZE_CHOICES))
            )
        object.__setattr__(self, "stabilize_choice", choice)

        if choice == STABILIZE_AUTOMATIC and self.damp_factor is None:
            raise ContactStabilizationError(
                "stabilizeChoice=AUTOMATIC requires an explicit damp_factor; "
                "no default damping magnitude is assumed"
            )
        for label, value in (("damp_factor", self.damp_factor), ("damp_coef", self.damp_coef)):
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                raise ContactStabilizationError("%s must be a finite number, got %r" % (label, value))
            if not math.isfinite(numeric) or numeric < 0.0:
                raise ContactStabilizationError(
                    "%s must be a non-negative finite number, got %r" % (label, value)
                )
            object.__setattr__(self, label, numeric)
        if choice == STABILIZE_AUTOMATIC and not self.damp_factor:
            # A zero factor is not a weaker stabilization, it is no
            # stabilization at all while the audit trail says otherwise.
            raise ContactStabilizationError(
                "stabilizeChoice=AUTOMATIC requires a positive damp_factor, got %r"
                % (self.damp_factor,)
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stabilize_choice": self.stabilize_choice,
            "damp_factor": self.damp_factor,
            "damp_coef": self.damp_coef,
            "target_step": self.target_step,
            "control_name": self.control_name,
        }


@dataclass(frozen=True)
class ContactStabilizationBinding:
    """Resolved plan for attaching one control object to one interaction."""

    interaction_name: str
    interaction_step: str
    target_step: str
    control_name: str
    spec: ContactStabilizationSpec
    requires_step_override: bool

    def to_dict(self) -> Dict[str, Any]:
        payload = self.spec.to_dict()
        payload.update(
            interaction_name=self.interaction_name,
            interaction_step=self.interaction_step,
            target_step=self.target_step,
            requires_step_override=self.requires_step_override,
        )
        return payload


def coerce_contact_stabilization(raw: Any) -> Optional[ContactStabilizationSpec]:
    """Build a spec from intent metadata, or ``None`` when nothing was requested."""
    if raw is None or raw is False:
        return None
    if isinstance(raw, ContactStabilizationSpec):
        return raw
    if not isinstance(raw, Mapping):
        raise ContactStabilizationError(
            "contact_stabilization must be a mapping, got %r" % (type(raw).__name__,)
        )
    if not raw:
        return None
    unknown = set(raw) - {
        "stabilize_choice",
        "stabilizeChoice",
        "damp_factor",
        "dampFactor",
        "damp_coef",
        "dampCoef",
        "target_step",
        "targetStep",
        "control_name",
        "contact_damping",
        "stabilization_method",
        "stabilization_magnitude",
    }
    if unknown:
        raise ContactStabilizationError(
            "unsupported contact_stabilization keys: %s" % ", ".join(sorted(str(k) for k in unknown))
        )
    if raw.get("stabilization_method") is not None:
        # ``stabilization_method`` is a StaticStep symbol and carries no meaning
        # for a contact control object; refusing it prevents a silent no-op.
        raise ContactStabilizationError(
            "stabilization_method does not apply to contact stabilization; "
            "use stabilize_choice and damp_factor"
        )
    choice = raw.get("stabilize_choice", raw.get("stabilizeChoice"))
    if choice is None and raw.get("contact_damping"):
        choice = STABILIZE_AUTOMATIC
    damp_factor = raw.get("damp_factor", raw.get("dampFactor"))
    if damp_factor is None:
        damp_factor = raw.get("stabilization_magnitude")
    return ContactStabilizationSpec(
        stabilize_choice=choice if choice is not None else STABILIZE_AUTOMATIC,
        damp_factor=damp_factor,
        damp_coef=raw.get("damp_coef", raw.get("dampCoef", 0.0)),
        target_step=raw.get("target_step", raw.get("targetStep")),
        control_name=raw.get("control_name") or DEFAULT_CONTACT_CONTROL_NAME,
    )


def _interaction_type(raw: Any) -> str:
    value = getattr(raw, "interaction_type", None)
    if value is None and isinstance(raw, Mapping):
        value = raw.get("interaction_type", raw.get("type"))
    return str(value or "surface_to_surface_contact").lower()


def _interaction_name(raw: Any) -> str:
    value = getattr(raw, "name", None)
    if value is None and isinstance(raw, Mapping):
        value = raw.get("name")
    return str(value or "")


def _interaction_step(raw: Any) -> str:
    value = getattr(raw, "step", None)
    if value is None and isinstance(raw, Mapping):
        value = raw.get("step")
    return str(value or INITIAL_STEP)


def resolve_contact_stabilization(
    interactions: Sequence[Any],
    spec: Optional[ContactStabilizationSpec],
    *,
    step_order: Sequence[str] = (),
    enablement_steps: Optional[Sequence[str]] = None,
) -> Tuple[ContactStabilizationSpec, Tuple[ContactStabilizationBinding, ...]]:
    """Bind ``spec`` to exactly one interaction and one analysis step.

    ``interactions`` must contain exactly one interaction; anything else is
    ambiguous and raises. ``enablement_steps`` lists the steps whose procedure
    supports contact stabilization, in ordinal order.
    """
    if spec is None:
        return spec, ()

    supported_steps = tuple(enablement_steps if enablement_steps is not None else step_order)
    if not supported_steps:
        raise ContactStabilizationError(
            "contact stabilization requires at least one supported implicit analysis step"
        )

    candidates = [
        inter for inter in interactions
        if _interaction_type(inter) in SUPPORTED_INTERACTION_TYPES
    ]
    unsupported = [
        _interaction_name(inter) or "<unnamed>"
        for inter in interactions
        if _interaction_type(inter) not in SUPPORTED_INTERACTION_TYPES
    ]
    if unsupported:
        raise ContactStabilizationError(
            "contact stabilization is not implemented for interaction type(s) %s"
            % ", ".join(sorted(unsupported))
        )
    if not candidates:
        raise ContactStabilizationError(
            "contact stabilization was requested but the model defines no surface-to-surface contact"
        )
    if len(candidates) > 1:
        raise ContactStabilizationError(
            "contact stabilization target is ambiguous across %d interactions (%s); "
            "name a single interaction before applying contact damping"
            % (len(candidates), ", ".join(_interaction_name(i) or "<unnamed>" for i in candidates))
        )

    interaction = candidates[0]
    interaction_name = _interaction_name(interaction)
    if not interaction_name:
        raise ContactStabilizationError("contact stabilization target interaction has no name")

    target = spec.target_step
    if target is None:
        if len(supported_steps) > 1:
            raise ContactStabilizationError(
                "contact stabilization spans multiple implicit steps (%s); "
                "an explicit target_step is required"
                % ", ".join(supported_steps)
            )
        target = supported_steps[0]
    elif target not in supported_steps:
        raise ContactStabilizationError(
            "contact stabilization target_step %r is not an implicit analysis step "
            "that supports contact controls (available: %s)"
            % (target, ", ".join(supported_steps))
        )

    interaction_step = _interaction_step(interaction)
    if interaction_step == INITIAL_STEP:
        requires_override = True
    elif interaction_step == target:
        requires_override = False
    elif interaction_step in supported_steps and supported_steps.index(target) > supported_steps.index(interaction_step):
        requires_override = True
    else:
        raise ContactStabilizationError(
            "contact %r is created in step %r, which is not before target step %r; "
            "contact stabilization cannot be applied retroactively"
            % (interaction_name, interaction_step, target)
        )

    binding = ContactStabilizationBinding(
        interaction_name=interaction_name,
        interaction_step=interaction_step,
        target_step=target,
        control_name=spec.control_name,
        spec=spec,
        requires_step_override=requires_override,
    )
    return spec, (binding,)


def contact_control_creation_script(binding: ContactStabilizationBinding, model_name: str) -> str:
    """Render the ``StdContactControl`` creation statement only.

    The control object must exist before the interaction references it.
    """
    args = [
        "name=%r" % binding.control_name,
        "stabilizeChoice=%s" % binding.spec.stabilize_choice,
    ]
    if binding.spec.damp_factor is not None:
        args.append("dampFactor=%r" % binding.spec.damp_factor)
    if binding.spec.damp_coef is not None:
        args.append("dampCoef=%r" % binding.spec.damp_coef)
    return "mdb.models[%r].StdContactControl(%s)" % (model_name, ", ".join(args))


def contact_control_binding_script(binding: ContactStabilizationBinding, model_name: str) -> str:
    """Render the step override that attaches the control to an existing interaction."""
    if not binding.requires_step_override:
        return ""
    return (
        "mdb.models[%r].interactions[%r].setValuesInStep("
        "stepName=%r, contactControls=%r)"
        % (model_name, binding.interaction_name, binding.target_step, binding.control_name)
    )


def contact_control_script(binding: ContactStabilizationBinding, model_name: str) -> str:
    """Render the full control block (creation plus step override when needed)."""
    lines = [contact_control_creation_script(binding, model_name)]
    binding_line = contact_control_binding_script(binding, model_name)
    if binding_line:
        lines.append(binding_line)
    return "\n".join(lines)
