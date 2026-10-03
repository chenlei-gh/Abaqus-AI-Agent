"""GA-2.6 Physical Procedure & Multi-Step Lifecycle Contracts.

Defines deterministic, solver-verifiable contracts for:
1. Multi-Step Procedure DAG and state inheritance;
2. Bolt pretension two-stage lifecycle (APPLY_FORCE -> FIX_LENGTH);
3. Moment / Torque transfer strategy matrix;
4. Safe AST-validated SpatialLoadField specifications.
"""

import ast
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


class BoltPretensionMethod(str, Enum):
    """Abaqus bolt pretension boundary/load state method."""
    APPLY_FORCE = "APPLY_FORCE"
    FIX_LENGTH = "FIX_LENGTH"


class MomentTransferStrategy(str, Enum):
    """Load transfer mechanism for concentrated moment / torque on continuous media."""
    RP_COUPLING = "RP_COUPLING"              # Reference Point + Kinematic/Distributed Coupling (Standard for 3D solids)
    DISTRIBUTED_COUPLE = "DISTRIBUTED_COUPLE" # Equivalent surface tangential force / shear couple
    EXISTING_RP = "EXISTING_RP"              # Direct torque on pre-existing reference point / connector
    DIRECT_DOF = "DIRECT_DOF"                # Direct application on beam/shell nodes with active rotational DOFs


# ---------------------------------------------------------------------------
# AST Safe Validator for Spatial Expression Fields
# ---------------------------------------------------------------------------

_ALLOWED_AST_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.USub,
    ast.UAdd,
)

# In Python 3.7/3.8 compatibility, Num is handled as Constant or Num
if hasattr(ast, "Num"):
    _ALLOWED_AST_NODES = _ALLOWED_AST_NODES + (ast.Num,)

_ALLOWED_IDENTIFIERS = frozenset({"X", "Y", "Z", "x", "y", "z"})


def validate_field_expression(expression: str) -> Tuple[bool, Optional[str]]:
    """Validate spatial field expression using a strict AST whitelist.

    Prohibits:
    - Attribute access (e.g. os.system, __class__)
    - Function calls and name lookups outside coordinate axes
    - Imports, lambdas, subscripts, comprehensions, or assignment
    Only allows:
    - Coordinate symbols: X, Y, Z (case-insensitive)
    - Numeric constants
    - Standard arithmetic operators: +, -, *, /, **
    """
    if not expression or not expression.strip():
        return False, "expression cannot be empty"

    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:
        return False, f"syntax error in field expression: {e}"

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_AST_NODES):
            return False, f"disallowed AST node: {type(node).__name__} (only arithmetic on coordinates is permitted)"
        if isinstance(node, ast.Name):
            if node.id not in _ALLOWED_IDENTIFIERS:
                return False, f"unsupported identifier '{node.id}'; only X, Y, Z coordinates are permitted"

    return True, None


@dataclass(frozen=True)
class SpatialLoadField:
    """Analytical spatial field specification for spatially varying loads."""
    name: str
    expression: str
    variables: Tuple[str, ...] = ("X", "Y", "Z")
    description: Optional[str] = None

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("field name is required")
        valid, err = validate_field_expression(self.expression)
        if not valid:
            raise ValueError(f"Invalid field expression '{self.expression}': {err}")


# ---------------------------------------------------------------------------
# Multi-Step Procedure Contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StepDependency:
    """Dependency and state configuration for a single analysis step."""
    name: str
    previous: str = "Initial"
    procedure: str = "static"                 # static, implicit_dynamic, explicit_dynamic, frequency, heat_transfer
    nlgeom: Optional[bool] = None             # None = inherit from previous step
    time_period: float = 1.0
    initial_inc: Optional[float] = None
    min_inc: Optional[float] = None
    max_inc: Optional[float] = None
    max_num_inc: int = 100
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("step name is required")
        if self.time_period <= 0 and self.procedure != "frequency":
            raise ValueError("time_period must be positive")


@dataclass(frozen=True)
class MultiStepProcedureSpec:
    """Specification of an ordered multi-step analysis sequence with state inheritance."""
    steps: Tuple[StepDependency, ...]

    def __post_init__(self):
        if not self.steps:
            raise ValueError("at least one step must be defined")
        names: Set[str] = set()
        for s in self.steps:
            if s.name in names:
                raise ValueError(f"duplicate step name '{s.name}' in procedure")
            names.add(s.name)

    def validate_dag(self) -> Tuple[bool, List[str]]:
        """Validate DAG sequence, parent existence, and nlgeom conflict safety."""
        defined: Set[str] = {"Initial"}
        errors: List[str] = []
        active_nlgeom = False

        for step in self.steps:
            if step.previous not in defined:
                errors.append(f"Step '{step.name}' references previous step '{step.previous}' which is not yet defined")
            defined.add(step.name)

            # Safety Rule: nlgeom conflict check across steps
            if step.nlgeom is True:
                active_nlgeom = True
            elif step.nlgeom is False and active_nlgeom:
                errors.append(
                    f"Safety conflict: Step '{step.name}' attempts to disable nlgeom (False) "
                    f"after previous steps enabled nlgeom (True)"
                )

        return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Physical Load & Lifecycle Contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BoltPretensionLifecycleSpec:
    """Two-stage bolt pretension lifecycle contract (APPLY_FORCE -> FIX_LENGTH)."""
    name: str
    region_expression: str
    preload_magnitude: float
    preload_step: str = "Step-Preload"
    service_step: Optional[str] = "Step-Service"
    direction_vector: Optional[Tuple[float, float, float]] = None

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("bolt pretension name is required")
        if not self.region_expression or not self.region_expression.strip():
            raise ValueError("bolt pretension region_expression is required")
        if self.preload_magnitude <= 0:
            raise ValueError("preload_magnitude must be positive")
        if self.preload_step == "Initial":
            raise ValueError("preload_step cannot be 'Initial'")


@dataclass(frozen=True)
class MomentLoadSpec:
    """Moment / Torque load specification with explicit transfer strategy."""
    name: str
    region_expression: str
    magnitude: float
    axis: str = "CM1"                         # "CM1", "CM2", "CM3"
    step: str = "Step-1"
    strategy: MomentTransferStrategy = MomentTransferStrategy.RP_COUPLING
    rp_coordinates: Optional[Tuple[float, float, float]] = None

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("moment load name is required")
        if not self.region_expression or not self.region_expression.strip():
            raise ValueError("moment load region_expression is required")
        if self.axis.upper() not in ("CM1", "CM2", "CM3"):
            raise ValueError(f"invalid moment axis '{self.axis}'; must be CM1, CM2, or CM3")
