from dataclasses import dataclass

from .actions.runner import execute
from .evidence.result import summarize_odb
from .planning.planner import plan_from_intents
from .validation.actions import validate_plan


@dataclass
class RunResult:
    plan: object
    execution_results: list
    job_result: object = None
    odb_summary: object = None


class AbaqusAIAgent:
    """Orchestrates planning, validation, native execution and evidence.

    It intentionally does not invent geometry. A BC/load action is executable
    only after its region expression has been produced by grounding or an
    explicit user/model selection.
    """
    def __init__(self, executor):
        self.executor = executor

    def apply_plan(self, plan):
        validate_plan(plan)
        results = []
        for action in plan.actions:
            results.append(execute(self.executor, action))
        return results

    def inspect_model(self):
        from .execution.inspection import get_model_info
        return get_model_info(self.executor)

    def snapshot(self):
        from .execution.snapshot import read_model_snapshot
        return read_model_snapshot(self.executor)

    def runtime_info(self):
        from .execution.runtime import detect_runtime
        return detect_runtime(self.executor)

    def viewport_state(self):
        from .execution.viewport import read_viewport_state
        return read_viewport_state(self.executor)

    def analysis_run(self, model_name, job_name, odb_path=None, criteria=(), result_values=None):
        from .execution.analysis_run import AnalysisRunner
        return AnalysisRunner(self.executor).run(model_name, job_name, odb_path=odb_path,
                                                criteria=criteria, result_values=result_values)

    def submit(self, job_name, wait=False):
        from .execution.jobs import JobController
        return JobController(self.executor).submit(job_name, wait=wait)

    def inspect_odb(self, path):
        from .execution.odb import inspect_odb
        return summarize_odb(inspect_odb(self.executor, path))
