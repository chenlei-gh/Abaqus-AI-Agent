import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .analysis_run import AnalysisRun, AnalysisRunner
from .queue import AnalysisRunQueue, QueueItem, QueueItemState
from .recovery import RecoveryVerdict, inspect_run_state
from .sandbox import RunSandbox


class RunWorker:
    """Production runtime worker that consumes scheduled items from AnalysisRunQueue,

    executes them inside isolated RunSandbox scratch spaces, ensures license cleanup,
    promotes verified engineering artifacts, and updates canonical AnalysisRun records.
    """

    def __init__(
        self,
        queue: AnalysisRunQueue,
        runner: Optional[AnalysisRunner] = None,
        sandbox_base_dir: Optional[str] = None,
        target_artifacts_dir: Optional[str] = None,
    ):
        self.queue = queue
        self.runner = runner
        self.sandbox_base_dir = sandbox_base_dir
        self.target_artifacts_dir = target_artifacts_dir

    def execute_item(self, item: QueueItem) -> Optional[Any]:
        """Execute a single dispatched QueueItem within an isolated RunSandbox."""
        sandbox = RunSandbox(
            run_id=item.item_id,
            base_dir=self.sandbox_base_dir,
            cleanup_on_exit=True,
        )
        sandbox.create()

        job_name = "Job-1"
        try:
            payload = item.payload
            result_run = None

            if callable(payload):
                # Custom task function
                result_run = payload(sandbox=sandbox)
            elif self.runner is not None:
                # Orchestrate through canonical AnalysisRunner
                if isinstance(payload, AnalysisRun):
                    job_name = payload.job_name
                    model_name = payload.model_name
                    result_run = self.runner.run(
                        model_name=model_name,
                        job_name=job_name,
                        action_plan=payload.action_plan,
                    )
                elif isinstance(payload, dict):
                    job_name = payload.get("job_name", "Job-1")
                    model_name = payload.get("model_name", "Model-1")
                    result_run = self.runner.run(
                        model_name=model_name,
                        job_name=job_name,
                        criteria=payload.get("criteria", ()),
                        action_plan=payload.get("action_plan", ()),
                    )
                else:
                    # Generic runner call with payload as intent or model
                    result_run = self.runner.run(
                        model_name="Model-1",
                        job_name=job_name,
                    )
            else:
                result_run = payload

            # Artifact promotion
            promoted_records = []
            if self.target_artifacts_dir:
                promoted = sandbox.promote_artifacts(self.target_artifacts_dir)
                promoted_records = [p.to_dict() for p in promoted]

            if isinstance(result_run, AnalysisRun):
                meta = dict(result_run.metadata)
                meta["sandbox_id"] = sandbox.run_id
                meta["promoted_artifacts"] = promoted_records
                result_run = result_run.with_state(
                    result_run.state,
                    metadata=meta,
                )

            self.queue.complete(item.item_id, result=result_run)
            return result_run

        except Exception as exc:
            # Failure diagnosis and recovery evaluation
            inspection = inspect_run_state(sandbox.sandbox_dir, job_name)
            retryable = inspection.verdict in (
                RecoveryVerdict.RECOVERABLE_RECONNECT,
                RecoveryVerdict.NON_RECOVERABLE_RESUBMIT,
            )
            # If aborted/crashed, clear stale lock before retry
            sandbox.clear_stale_locks()
            self.queue.fail(item.item_id, error=str(exc), retryable=retryable)
            return None

        finally:
            sandbox.cleanup()

    def poll_and_execute_once(self) -> Optional[QueueItem]:
        """Poll the queue for next eligible task, execute it, and return the item."""
        item = self.queue.process_next()
        if item is None:
            return None
        self.execute_item(item)
        return item

    def run_loop(
        self,
        poll_interval: float = 0.05,
        max_steps: Optional[int] = None,
        stop_event: Optional[threading.Event] = None,
        stop_when_idle: bool = True,
    ) -> int:
        """Run worker loop. When stop_when_idle is True, stops when no pending/retrying items remain."""
        steps = 0
        while True:
            if stop_event and stop_event.is_set():
                break
            if max_steps is not None and steps >= max_steps:
                break

            item = self.poll_and_execute_once()
            if item is not None:
                steps += 1
            else:
                # Check if work remains in future retries
                remaining = self.queue.list_items(QueueItemState.PENDING) + self.queue.list_items(QueueItemState.RETRYING)
                if not remaining and stop_when_idle:
                    break
                time.sleep(poll_interval)

        return steps


class RunWorkerPool:
    """Thread pool of workers executing tasks cooperatively from an AnalysisRunQueue."""

    def __init__(
        self,
        queue: AnalysisRunQueue,
        runner: Optional[AnalysisRunner] = None,
        worker_count: int = 2,
        sandbox_base_dir: Optional[str] = None,
        target_artifacts_dir: Optional[str] = None,
    ):
        self.queue = queue
        self.runner = runner
        self.worker_count = max(1, worker_count)
        self.sandbox_base_dir = sandbox_base_dir
        self.target_artifacts_dir = target_artifacts_dir
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []

    def start(self, poll_interval: float = 0.05) -> None:
        """Spawn background worker threads."""
        self._stop_event.clear()
        for i in range(self.worker_count):
            worker = RunWorker(
                queue=self.queue,
                runner=self.runner,
                sandbox_base_dir=self.sandbox_base_dir,
                target_artifacts_dir=self.target_artifacts_dir,
            )
            t = threading.Thread(
                target=worker.run_loop,
                kwargs={
                    "poll_interval": poll_interval,
                    "stop_event": self._stop_event,
                    "stop_when_idle": False,
                },
                daemon=True,
                name=f"RunWorker-{i+1}",
            )
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 5.0) -> None:
        """Signal all workers to terminate and join threads."""
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=timeout)
        self._threads.clear()

    def wait_until_drained(self, timeout: float = 10.0, poll_interval: float = 0.05) -> bool:
        """Block until all enqueued items are COMPLETED, FAILED, or CANCELLED."""
        start = time.time()
        while time.time() - start < timeout:
            active = [
                it
                for it in self.queue.list_items()
                if it.state in (QueueItemState.PENDING, QueueItemState.ACQUIRING_LICENSE, QueueItemState.RUNNING, QueueItemState.RETRYING)
            ]
            if not active:
                return True
            time.sleep(poll_interval)
        return False
