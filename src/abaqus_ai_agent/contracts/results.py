from dataclasses import dataclass, field as dataclass_field
from typing import Any, Dict, Optional, Tuple, Union

from .units import validate_quantity_unit


@dataclass(frozen=True)
class ResultRequirement:
    """Deterministic description of one engineering result needed for acceptance."""
    name: str
    value_key: str
    field: Optional[str] = None
    component: Optional[str] = None
    invariant: Optional[str] = None
    aggregation: str = "max"
    step: Optional[str] = None
    frame: int = -1
    position: Optional[str] = None
    region: Optional[str] = None
    history_region: Optional[str] = None
    history_region_expression: Optional[str] = None
    history_variable: Optional[str] = None
    unit: str = ""
    output_kind: str = "field"
    quantity: Optional[str] = None
    source: str = "odb"
    required: bool = True
    reducer: Optional[str] = None
    metadata: Dict[str, Any] = dataclass_field(default_factory=dict)

    def __post_init__(self):
        # Normalize reducer / aggregation alias
        effective_agg = (self.reducer or self.aggregation or "max").lower()
        if effective_agg == "mean":
            effective_agg = "average"
        if effective_agg not in ("max", "min", "average", "last", "sum", "first"):
            raise ValueError("unsupported aggregation/reducer: %s" % effective_agg)
        if effective_agg != self.aggregation:
            object.__setattr__(self, "aggregation", effective_agg)
        if self.reducer is None or self.reducer != effective_agg:
            object.__setattr__(self, "reducer", effective_agg)

        if self.output_kind not in ("field", "history", "frame_value"):
            raise ValueError("unsupported output_kind: %s" % self.output_kind)
        if self.output_kind == "field" and not self.field:
            raise ValueError("field is required for field output requirements")
        if self.output_kind == "history" and not self.history_variable:
            raise ValueError("history_variable is required for history output requirements")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value_key": self.value_key,
            "field": self.field,
            "component": self.component,
            "invariant": self.invariant,
            "aggregation": self.aggregation,
            "reducer": self.reducer or self.aggregation,
            "step": self.step,
            "frame": self.frame,
            "position": self.position,
            "region": self.region,
            "history_region": self.history_region,
            "history_region_expression": self.history_region_expression,
            "history_variable": self.history_variable,
            "unit": self.unit,
            "output_kind": self.output_kind,
            "quantity": self.quantity,
            "source": self.source,
            "required": self.required,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ResultExtraction:
    requirement: ResultRequirement
    value: float
    locator: Dict[str, Any] = dataclass_field(default_factory=dict)
    evidence: Tuple[Union[Dict[str, Any], Any], ...] = ()



_RESULT_QUANTITIES = {
    "max_stress": "stress",
    "max_mises": "stress",
    "max_displacement": "displacement",
    "max_u": "displacement",
    "min_displacement": "displacement",
    "max_temperature": "temperature",
    "max_strain": None,
    "max_reaction_force": "force",
    "max_rf": "force",
    "frequency": "frequency",
    "connector_relative_motion": "displacement",
    "connector_relative_displacement": "displacement",
    "connector_relative_rotation": "angle",
    "connector_force": "force",
    "connector_total_force": "force",
    "connector_moment": "moment",
    "connector_position": "displacement",
    "joint_drift": "displacement",
    "revolute_joint_drift": "displacement",
    "fmbd_drift": "displacement",
    "relative_articulation": "angle",
    "max_mises_stress": "stress",
    "tip_displacement": "displacement",
    "tip_deflection": "displacement",
    "strain_energy_ratio": "energy",
    "energy_dissipation_ratio": "energy",
    "buckling_load": "force",
    "limit_load": "force",
    "eigenvalue_load": "force",
}


def _infer_quantity(key, field=None, history_variable=None, output_kind="field"):
    quantity = _RESULT_QUANTITIES.get(key)
    if quantity:
        return quantity
    if field == "S":
        return "stress"
    if field == "U":
        return "displacement"
    if field == "RF":
        return "force"
    if field == "NT11":
        return "temperature"
    if field in ("CU", "CUE", "CP"):
        return "displacement"
    if field in ("CTF", "CEF", "CRF"):
        return "force"
    if field in ("CTM",):
        return "moment"
    if output_kind == "history" and history_variable:
        if str(history_variable).startswith("ALL"):
            return "energy"
        if str(history_variable).startswith("RF"):
            return "force"
    return None


_FIELD_ALIASES = {
    "max_stress": ("S", "MISES"),
    "max_mises": ("S", "MISES"),
    "max_displacement": ("U", "MAGNITUDE"),
    "max_u": ("U", "MAGNITUDE"),
    "min_displacement": ("U", "MAGNITUDE"),
    "max_temperature": ("NT11", None),
    "max_strain": ("E", "MISES"),
    "max_reaction_force": ("RF", "MAGNITUDE"),
    "max_rf": ("RF", "MAGNITUDE"),
    "max_mises_stress": ("S", "MISES"),
    "tip_displacement": ("U", "MAGNITUDE"),
    "tip_deflection": ("U", "MAGNITUDE"),
    "connector_relative_motion": ("CU", "MAGNITUDE"),
    "connector_relative_displacement": ("CU", "MAGNITUDE"),
    "connector_force": ("CTF", "MAGNITUDE"),
    "connector_position": ("CU", "MAGNITUDE"),
    "buckling_load": ("RF", "MAGNITUDE"),
    "limit_load": ("RF", "MAGNITUDE"),
    "eigenvalue_load": ("RF", "MAGNITUDE"),
}


def requirement_from_criterion(criterion):
    key = criterion.get("value_key")
    if not key:
        raise ValueError("criterion requires value_key")
    explicit = criterion.get("result")
    if explicit:
        data = dict(explicit)
        data.setdefault("name", criterion.get("name", key))
        data.setdefault("value_key", key)
        data.setdefault("unit", criterion.get("unit", ""))
        data.setdefault("source", criterion.get("source", "odb"))
        data.setdefault("required", criterion.get("required", True))
        if "reducer" in criterion and "reducer" not in data:
            data["reducer"] = criterion["reducer"]
        if "region" in criterion and "region" not in data:
            data["region"] = criterion["region"]
        data.setdefault("quantity", _infer_quantity(
            key,
            field=data.get("field"),
            history_variable=data.get("history_variable"),
            output_kind=data.get("output_kind", "field"),
        ))
        if data.get("unit") and data.get("quantity"):
            validate_quantity_unit(
                data["quantity"], data["unit"], criterion.get("unit_system")
            )
        return ResultRequirement(**data)

    if key == "frequency":
        unit = criterion.get("unit", "Hz")
        validate_quantity_unit("frequency", unit, criterion.get("unit_system"))
        return ResultRequirement(
            name=criterion.get("name", key), value_key=key,
            aggregation="last", output_kind="frame_value",
            step=criterion.get("step"), unit=unit, quantity="frequency",
            source=criterion.get("source", "odb"),
            required=criterion.get("required", True))

    alias = _FIELD_ALIASES.get(key)
    if not alias:
        raise ValueError(
            "no deterministic ODB mapping for result '%s'; "
            "provide criterion.result" % key)

    field, invariant = alias
    aggregation = criterion.get("reducer") or criterion.get("aggregation") or ("min" if key == "min_displacement" else "max")
    quantity = _infer_quantity(key, field=field, output_kind="field")
    unit = criterion.get("unit", "")
    if unit and quantity:
        validate_quantity_unit(quantity, unit, criterion.get("unit_system"))
    return ResultRequirement(
        name=criterion.get("name", key), value_key=key,
        field=field, invariant=invariant, aggregation=aggregation,
        step=criterion.get("step"), frame=criterion.get("frame", -1),
        position=criterion.get("position"), region=criterion.get("region"),
        unit=unit, quantity=quantity,
        source=criterion.get("source", "odb"),
        required=criterion.get("required", True))


def requirements_from_criteria(criteria):
    return tuple(requirement_from_criterion(c) for c in criteria or ())


def required_field_variables(requirements):
    return tuple(sorted(set(
        r.field for r in requirements
        if r.output_kind == "field" and r.field)))


@dataclass(frozen=True)
class PhysicsResultProfile:
    """Declared engineering result and gate profile for an engineering physics domain."""
    domain: str
    required_fields: Tuple[str, ...]
    required_metrics: Tuple[str, ...]
    required_gates: Tuple[str, ...]
    gate_justifications: Dict[str, str] = dataclass_field(default_factory=dict)
    step_requirements: Dict[str, Tuple[str, ...]] = dataclass_field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "required_fields": list(self.required_fields),
            "required_metrics": list(self.required_metrics),
            "required_gates": list(self.required_gates),
            "gate_justifications": dict(self.gate_justifications),
            "step_requirements": {k: list(v) for k, v in self.step_requirements.items()},
        }


def get_physics_result_profile(domain: str, **custom_overrides) -> PhysicsResultProfile:
    """Resolve the canonical result requirement and gate profile for a physics domain."""
    d = (domain or "static").lower().strip()

    if d in ("static", "structural_static", "static_general"):
        prof = PhysicsResultProfile(
            domain="static",
            required_fields=("U", "S", "RF"),
            required_metrics=("max_displacement", "max_mises", "reaction_force"),
            required_gates=("execution", "odb", "criteria"),
            gate_justifications={
                "contact": "Single continuum structure; contact diagnostics gate not applicable.",
                "fatigue": "Monotonic static loading; fatigue life gate not requested.",
                "mesh_convergence": "Single mesh analysis baseline; adaptive convergence not requested.",
            },
        )
    elif d in ("thermal", "heat_transfer", "thermal_steady"):
        prof = PhysicsResultProfile(
            domain="thermal",
            required_fields=("NT11", "HFL", "RFL"),
            required_metrics=("max_temperature", "heat_flux", "reaction_flux"),
            required_gates=("execution", "odb", "criteria"),
            gate_justifications={
                "contact": "Pure thermal conduction model; mechanical contact diagnostics not applicable.",
                "fatigue": "Steady thermal field; mechanical fatigue gate not requested.",
            },
        )
    elif d in ("contact", "frictional_contact", "contact_interaction"):
        prof = PhysicsResultProfile(
            domain="contact",
            required_fields=("CPRESS", "CSHEAR", "RF"),
            required_metrics=("contact_pressure", "frictional_shear", "reaction_force"),
            required_gates=("execution", "odb", "contact", "criteria"),
            gate_justifications={
                "fatigue": "Static contact equilibrium; fatigue life gate not requested.",
            },
        )
    elif d in ("thermal_structural", "thermal_stress", "sequential_thermal_stress"):
        prof = PhysicsResultProfile(
            domain="thermal_structural",
            required_fields=("NT", "U", "S", "RF"),
            required_metrics=("max_temperature", "max_displacement", "max_mises", "reaction_force"),
            required_gates=("execution", "odb", "thermal_balance", "criteria"),
            step_requirements={
                "Step-Thermal": ("max_temperature",),
                "Step-Structural": ("max_displacement", "max_mises", "reaction_force"),
            },
            gate_justifications={
                "contact": "Single continuum thermal-structural model; contact interaction not applicable.",
                "fatigue": "Monotonic thermal stress cycle; fatigue life gate not requested.",
            },
        )
    elif d in ("preloaded_modal", "preloaded_frequency", "preloaded_dynamics"):
        prof = PhysicsResultProfile(
            domain="preloaded_modal",
            required_fields=("U", "S", "RF"),
            required_metrics=("preload_reaction", "frequency"),
            required_gates=("execution", "odb", "procedure", "criteria"),
            step_requirements={
                "Step-Preload": ("preload_reaction",),
                "Step-Modal": ("frequency",),
            },
            gate_justifications={
                "contact": "Fixed-end continuum beam; contact diagnostics not applicable.",
                "fatigue": "Frequency extraction; time-domain fatigue not requested.",
            },
        )
    elif d in ("explicit_dynamic", "explicit", "dynamic_explicit"):
        prof = PhysicsResultProfile(
            domain="explicit_dynamic",
            required_fields=("U", "V", "S", "ALLKE", "ALLIE"),
            required_metrics=("max_displacement", "max_mises", "kinetic_energy", "internal_energy"),
            required_gates=("execution", "odb", "criteria"),
            gate_justifications={
                "contact": "Impact dynamic response of continuum solid; contact not modeled.",
                "fatigue": "Short transient dynamic wave event; high-cycle fatigue not applicable.",
            },
        )
    elif d in ("modal", "frequency", "eigenvalue"):
        prof = PhysicsResultProfile(
            domain="modal",
            required_fields=("frequency", "eigenvalue"),
            required_metrics=("frequency",),
            required_gates=("execution", "odb", "criteria"),
            gate_justifications={
                "contact": "Linear eigenvalue extraction; contact diagnostics not applicable.",
                "fatigue": "Frequency domain eigenmodes; time-domain fatigue not requested.",
            },
        )
    elif d in ("buckling", "eigenvalue_buckling", "post_buckling", "riks_buckling"):
        prof = PhysicsResultProfile(
            domain="buckling",
            required_fields=("U", "RF"),
            required_metrics=("buckling_load", "limit_load"),
            required_gates=("execution", "odb", "criteria"),
            gate_justifications={
                "contact": "Continuous laminated shell; contact interaction not modeled.",
                "fatigue": "Monotonic axial compression and stability limit load; high-cycle fatigue not applicable.",
            },
        )
    elif d in ("fatigue", "cyclic_fatigue"):
        prof = PhysicsResultProfile(
            domain="fatigue",
            required_fields=("S",),
            required_metrics=("fatigue_life", "damage"),
            required_gates=("execution", "odb", "fatigue", "criteria"),
            gate_justifications={
                "contact": "Fatigue coupon model; contact interaction not applicable.",
            },
        )
    elif d in ("connector", "kinematic_connector", "connector_kinematics", "mechanism_connector"):
        prof = PhysicsResultProfile(
            domain="connector",
            required_fields=("CU", "CTF"),
            required_metrics=("connector_relative_motion", "connector_force"),
            required_gates=("execution", "odb", "connector_kinematics", "criteria"),
            gate_justifications={
                "contact": "Discrete kinematic connector elements; continuous contact diagnostics not applicable.",
                "fatigue": "Kinematic mechanism motion; high-cycle fatigue not requested.",
            },
        )
    elif d in ("fmbd", "flexible_multibody", "rigid_flexible_coupling", "fmbd_dynamics"):
        prof = PhysicsResultProfile(
            domain="fmbd",
            required_fields=("S", "U", "CU", "CTF"),
            required_metrics=("joint_drift", "max_mises_stress", "strain_energy_ratio", "energy_dissipation_ratio"),
            required_gates=("execution", "odb", "fmbd_dynamics", "criteria"),
            gate_justifications={
                "contact": "Coupled rigid-flexible mechanism via kinematic coupling and connectors; continuous contact diagnostics not required.",
                "fatigue": "Nonlinear transient flexible multibody dynamic analysis; high-cycle fatigue not requested.",
            },
        )
    elif d in ("multi_step", "bolt_service", "bolt_pretension"):
        prof = PhysicsResultProfile(
            domain="multi_step",
            required_fields=("U", "S", "RF", "RM"),
            required_metrics=("preload_force", "axial_reaction", "torque_reaction"),
            required_gates=("execution", "odb", "procedure", "criteria"),
            step_requirements={
                "Step-Preload": ("preload_force",),
                "Step-Service": ("axial_reaction", "torque_reaction"),
            },
            gate_justifications={
                "fatigue": "Multi-step static preloading & service state; fatigue not requested.",
                "contact": "Tied or continuous bolt model; contact diagnostics not requested.",
            },
        )
    else:
        prof = PhysicsResultProfile(
            domain=d,
            required_fields=("U", "S"),
            required_metrics=("max_displacement", "max_mises"),
            required_gates=("execution", "odb", "criteria"),
            gate_justifications={
                "contact": "Generic domain; contact gate not requested.",
                "fatigue": "Generic domain; fatigue gate not requested.",
            },
        )

    if custom_overrides:
        fields = custom_overrides.get("required_fields", prof.required_fields)
        metrics = custom_overrides.get("required_metrics", prof.required_metrics)
        gates = custom_overrides.get("required_gates", prof.required_gates)
        justs = dict(prof.gate_justifications)
        justs.update(custom_overrides.get("gate_justifications", {}))
        step_reqs = dict(prof.step_requirements)
        step_reqs.update(custom_overrides.get("step_requirements", {}))
        return PhysicsResultProfile(
            domain=d,
            required_fields=tuple(fields),
            required_metrics=tuple(metrics),
            required_gates=tuple(gates),
            gate_justifications=justs,
            step_requirements=step_reqs,
        )
    return prof
