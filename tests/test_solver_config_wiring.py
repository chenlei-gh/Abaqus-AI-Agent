"""P0/P1 solver-config wiring. Not an adaptive selector and not a machine run."""
import pytest

from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
from abaqus_ai_agent.contracts.procedure import MultiStepProcedureSpec, StepDependency
from abaqus_ai_agent.execution.jobs import JobController
from abaqus_ai_agent.execution.solver_config import resolve_explicit_job_kwargs
from abaqus_ai_agent.planning.compiler import (
    IntentGeometrySpec,
    IntentMeshSpec,
    IntentStepSpec,
    compile_engineering_intent,
    compile_intent_to_actions,
)


GEOM = IntentGeometrySpec(shape="cantilever_box", length=10.0, width=2.0, height=2.0)
MESH = IntentMeshSpec(
    global_size=2.5,
    primary_wall_thickness=2.5,
    primary_wall_thickness_source="USER_SPECIFIED",
)
_MESH_REQUIREMENTS = {
    "global_size": 2.5,
    "primary_wall_thickness": 2.5,
    "primary_wall_thickness_source": "USER_SPECIFIED",
}
MAT = MaterialDefinition(
    name="Q235",
    unit_system="MM_N_MPA",
    elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
)

_MARKERS = {
    "explicit_dynamic": "ExplicitDynamicsStep",
    "explicit": "ExplicitDynamicsStep",
    "implicit_dynamic": "ImplicitDynamicsStep",
    "dynamic": "ImplicitDynamicsStep",
    "heat_transfer": "HeatTransferStep",
    "frequency": "FrequencyStep",
}


def _intent(analysis_type):
    return EngineeringIntent(
        id="PROBE",
        kind=analysis_type,
        description="probe",
        analysis_type=analysis_type,
        material=MAT,
        mesh_requirements=dict(_MESH_REQUIREMENTS),
        metadata={"dimensions": {"shape": "cantilever_box", "length": 10.0, "width": 2.0, "height": 2.0}},
    )


@pytest.mark.parametrize("analysis_type,marker", list(_MARKERS.items()))
def test_engineering_intent_keeps_declared_procedure(analysis_type, marker):
    plan = compile_engineering_intent(_intent(analysis_type), mesh=MESH)
    assert marker in plan.cae_script
    if marker != "StaticStep":
        assert "StaticStep" not in plan.cae_script


@pytest.mark.parametrize("step_type,marker", (
    ("explicit_dynamic", "ExplicitDynamicsStep"),
    ("implicit_dynamic", "ImplicitDynamicsStep"),
    ("heat_transfer", "HeatTransferStep"),
    ("frequency", "FrequencyStep"),
))
def test_single_step_and_steps_paths_do_not_fall_back(step_type, marker):
    single = compile_intent_to_actions(
        model_name="M", part_name="P", job_name="J", geometry=GEOM, material=MAT, mesh=MESH,
        step=IntentStepSpec(name="Step-1", step_type=step_type),
    )
    listed = compile_intent_to_actions(
        model_name="M", part_name="P", job_name="J", geometry=GEOM, material=MAT, mesh=MESH,
        steps=(IntentStepSpec(name="Step-1", step_type=step_type),),
    )
    for plan in (single, listed):
        assert marker in plan.cae_script
        assert "StaticStep" not in plan.cae_script


def test_procedure_path_still_emits_explicit_step():
    plan = compile_intent_to_actions(
        model_name="M", part_name="P", job_name="J", geometry=GEOM, material=MAT, mesh=MESH,
        procedure=MultiStepProcedureSpec(steps=(
            StepDependency(name="Exp", procedure="explicit_dynamic", time_period=0.01),
        )),
    )
    assert "ExplicitDynamicsStep" in plan.cae_script
    assert "StaticStep" not in plan.cae_script


def test_unknown_step_type_fails_closed():
    with pytest.raises(ValueError, match="unsupported step_type 'buckling'"):
        compile_intent_to_actions(
            model_name="M", part_name="P", job_name="J", geometry=GEOM, material=MAT, mesh=MESH,
            step=IntentStepSpec(name="Step-1", step_type="buckling"),
        )


class _Jobs:
    def __init__(self):
        self.jobs = {}


class _RecordingExecutor:
    def __init__(self):
        self.commands = []
        self.workdir = None

    def execute(self, code, timeout=120):
        self.commands.append(code)
        if "waitForCompletion" in code or ".status" in code:
            return "COMPLETED"
        return ""

    def snapshot(self):
        return _Jobs()


def test_runner_forwards_only_explicit_cpus(tmp_path):
    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner

    workdir = str(tmp_path / "plain")
    plain = _RecordingExecutor()
    plain.workdir = workdir
    run = AnalysisRunner(plain).run(
        model_name="M", job_name="JobPlain", workdir=workdir, require_production=False,
    )
    created = [code for code in plain.commands if code.startswith("mdb.Job(")]
    assert created == ["mdb.Job(name='JobPlain', model='M')"]
    assert run.metadata["solver_parameter_decisions"][0].sent_to_solver is False

    workdir = str(tmp_path / "explicit")
    explicit = _RecordingExecutor()
    explicit.workdir = workdir
    AnalysisRunner(explicit).run(
        model_name="M", job_name="JobExplicit", workdir=workdir,
        require_production=False, job_options={"numCpus": 2},
    )
    created = [code for code in explicit.commands if code.startswith("mdb.Job(")]
    assert created == ["mdb.Job(name='JobExplicit', model='M', numCpus=2)"]


def test_job_create_omits_cpus_unless_explicit():
    executor = _RecordingExecutor()
    JobController(executor).create("Job-1", "Model-1")
    assert executor.commands == ["mdb.Job(name='Job-1', model='Model-1')"]
    assert "numCpus" not in executor.commands[0]

    executor = _RecordingExecutor()
    JobController(executor).create("Job-1", "Model-1", numCpus=2, numDomains=2)
    assert "numCpus=2" in executor.commands[0]
    assert "numDomains=2" in executor.commands[0]


def test_explicit_job_options_are_recorded_and_not_invented():
    kwargs, decisions = resolve_explicit_job_kwargs(None)
    assert kwargs == {}
    assert decisions[0].name == "numCpus"
    assert decisions[0].source == "safe_default"
    assert decisions[0].sent_to_solver is False

    kwargs, decisions = resolve_explicit_job_kwargs({"numCpus": 4})
    assert kwargs == {"numCpus": 4}
    by_name = {item.name: item for item in decisions}
    assert by_name["numCpus"].source == "explicit"
    assert by_name["numCpus"].sent_to_solver is True
    assert by_name["numDomains"].sent_to_solver is False

    kwargs, decisions = resolve_explicit_job_kwargs({"memory": 1024})
    assert kwargs == {}
    assert decisions[0].source == "refused"
    assert decisions[0].sent_to_solver is False

    with pytest.raises(ValueError, match="positive int"):
        resolve_explicit_job_kwargs({"numCpus": True})
