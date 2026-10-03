import json
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .license import LicenseHandle, LicenseProvider, LocalLicenseProvider


class QueuePriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"

    @property
    def rank(self) -> int:
        ranks = {
            QueuePriority.CRITICAL: 4,
            QueuePriority.HIGH: 3,
            QueuePriority.NORMAL: 2,
            QueuePriority.LOW: 1,
        }
        return ranks.get(self, 2)


class QueueItemState(str, Enum):
    PENDING = "pending"
    ACQUIRING_LICENSE = "acquiring_license"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RunResourceSpec:
    feature: str = "standard"
    tokens: int = 1
    cpus: int = 1
    memory_mb: Optional[int] = None
    custom: Dict[str, Any] = field(default_factory=dict)


def compute_backoff(
    retry_count: int,
    base: float = 1.0,
    max_delay: float = 30.0,
    jitter_ratio: float = 0.2,
) -> float:
    """Exponential backoff with full jitter to prevent thundering herd on license servers."""
    delay = min(max_delay, base * (2 ** retry_count))
    jitter = delay * jitter_ratio * (random.uniform(-1.0, 1.0))
    return max(0.05, delay + jitter)


@dataclass
class QueueItem:
    item_id: str
    priority: QueuePriority
    payload: Any
    resources: RunResourceSpec
    state: QueueItemState = QueueItemState.PENDING
    enqueued_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    backoff_base: float = 1.0
    backoff_max: float = 30.0
    jitter_ratio: float = 0.2
    next_eligible_at: float = field(default_factory=time.time)
    error: Optional[str] = None
    license_handle: Optional[LicenseHandle] = None
    result: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "priority": self.priority.value if hasattr(self.priority, "value") else str(self.priority),
            "state": self.state.value if hasattr(self.state, "value") else str(self.state),
            "enqueued_at": self.enqueued_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "next_eligible_at": self.next_eligible_at,
            "error": self.error,
            "license_handle": self.license_handle.to_dict() if self.license_handle else None,
            "resources": {
                "feature": self.resources.feature,
                "tokens": self.resources.tokens,
                "cpus": self.resources.cpus,
            },
        }


class AnalysisRunQueue:
    """Production job execution queue with persistent storage, concurrency throttling,

    priority dispatch, and resilient license backoff.
    """

    def __init__(
        self,
        max_concurrency: int = 2,
        license_provider: Optional[LicenseProvider] = None,
        default_timeout: float = 3600.0,
        persistence_path: Optional[str] = None,
    ):
        self.max_concurrency = max(1, max_concurrency)
        self.license_provider = license_provider or LocalLicenseProvider()
        self.default_timeout = default_timeout
        self.persistence_path = os.path.abspath(persistence_path) if persistence_path else None
        self._items: Dict[str, QueueItem] = {}
        if self.persistence_path and os.path.exists(self.persistence_path):
            self._load_state()

    def _persist_state(self) -> None:
        """Atomic write of queue state to persistence_path."""
        if not self.persistence_path:
            return
        os.makedirs(os.path.dirname(self.persistence_path), exist_ok=True)
        tmp_file = f"{self.persistence_path}.tmp_{uuid.uuid4().hex[:8]}"
        serializable_items = {}
        for k, it in self._items.items():
            payload_data = None
            if hasattr(it.payload, "to_dict"):
                payload_data = it.payload.to_dict()
            elif isinstance(it.payload, (dict, list, str, int, float, bool)) or it.payload is None:
                payload_data = it.payload

            result_data = None
            if hasattr(it.result, "to_dict"):
                result_data = it.result.to_dict()
            elif isinstance(it.result, (dict, list, str, int, float, bool)) or it.result is None:
                result_data = it.result

            serializable_items[k] = {
                "item_id": it.item_id,
                "priority": it.priority.value if hasattr(it.priority, "value") else str(it.priority),
                "state": it.state.value if hasattr(it.state, "value") else str(it.state),
                "enqueued_at": it.enqueued_at,
                "started_at": it.started_at,
                "finished_at": it.finished_at,
                "retry_count": it.retry_count,
                "max_retries": it.max_retries,
                "backoff_base": it.backoff_base,
                "backoff_max": it.backoff_max,
                "jitter_ratio": it.jitter_ratio,
                "next_eligible_at": it.next_eligible_at,
                "error": it.error,
                "resources": {
                    "feature": it.resources.feature,
                    "tokens": it.resources.tokens,
                    "cpus": it.resources.cpus,
                    "memory_mb": it.resources.memory_mb,
                    "custom": dict(it.resources.custom),
                },
                "payload": payload_data,
                "result": result_data,
            }

        data = {
            "version": "queue_state_v1",
            "saved_at": time.time(),
            "max_concurrency": self.max_concurrency,
            "items": serializable_items,
        }
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            if os.path.exists(self.persistence_path):
                os.remove(self.persistence_path)
            os.rename(tmp_file, self.persistence_path)
        except Exception:
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass

    def _load_state(self) -> None:
        """Load queue items from persistent JSON file."""
        if not self.persistence_path or not os.path.exists(self.persistence_path):
            return
        try:
            with open(self.persistence_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw_items = data.get("items", {})
            for k, it in raw_items.items():
                p_val = it.get("priority", "normal")
                try:
                    priority = QueuePriority(p_val)
                except (ValueError, TypeError):
                    priority = QueuePriority.NORMAL

                st_val = it.get("state", "pending")
                try:
                    state = QueueItemState(st_val)
                except (ValueError, TypeError):
                    state = QueueItemState.PENDING

                res_data = it.get("resources", {})
                res = RunResourceSpec(
                    feature=res_data.get("feature", "standard"),
                    tokens=res_data.get("tokens", 1),
                    cpus=res_data.get("cpus", 1),
                    memory_mb=res_data.get("memory_mb"),
                    custom=dict(res_data.get("custom", {})),
                )
                qitem = QueueItem(
                    item_id=str(it.get("item_id", k)),
                    priority=priority,
                    payload=it.get("payload"),
                    resources=res,
                    state=state,
                    enqueued_at=float(it.get("enqueued_at", time.time())),
                    started_at=it.get("started_at"),
                    finished_at=it.get("finished_at"),
                    retry_count=int(it.get("retry_count", 0)),
                    max_retries=int(it.get("max_retries", 3)),
                    backoff_base=float(it.get("backoff_base", 1.0)),
                    backoff_max=float(it.get("backoff_max", 30.0)),
                    jitter_ratio=float(it.get("jitter_ratio", 0.2)),
                    next_eligible_at=float(it.get("next_eligible_at", time.time())),
                    error=it.get("error"),
                    result=it.get("result"),
                )
                self._items[qitem.item_id] = qitem
        except Exception:
            pass

    def recover_orphaned_runs(self, recovery_strategy: str = "requeue") -> int:
        """Reset jobs left in RUNNING or ACQUIRING_LICENSE from an abnormal crash.
        
        Since previous process exited, external solver handles and in-memory licenses
        were lost. Requeues or marks them deterministically.
        """
        recovered = 0
        for it in self._items.values():
            if it.state in (QueueItemState.RUNNING, QueueItemState.ACQUIRING_LICENSE):
                it.license_handle = None
                if recovery_strategy == "requeue":
                    it.state = QueueItemState.RETRYING
                    it.retry_count += 1
                    it.error = "Recovered from process crash; requeued for clean execution"
                    it.next_eligible_at = time.time()
                else:
                    it.state = QueueItemState.FAILED
                    it.error = "Orphaned run aborted due to abnormal system termination"
                    it.finished_at = time.time()
                recovered += 1
        if recovered > 0:
            self._persist_state()
        return recovered

    def enqueue(
        self,
        payload: Any,
        priority: QueuePriority = QueuePriority.NORMAL,
        resources: Optional[RunResourceSpec] = None,
        max_retries: int = 3,
        item_id: Optional[str] = None,
        backoff_base: float = 0.5,
        backoff_max: float = 10.0,
    ) -> QueueItem:
        effective_id = item_id or (getattr(payload, "id", None) if hasattr(payload, "id") else str(uuid.uuid4()))
        res = resources or RunResourceSpec()
        now = time.time()
        item = QueueItem(
            item_id=str(effective_id),
            priority=priority,
            payload=payload,
            resources=res,
            state=QueueItemState.PENDING,
            enqueued_at=now,
            max_retries=max_retries,
            backoff_base=backoff_base,
            backoff_max=backoff_max,
            next_eligible_at=now,
        )
        self._items[item.item_id] = item
        self._persist_state()
        return item

    def get_item(self, item_id: str) -> Optional[QueueItem]:
        return self._items.get(item_id)

    def cancel(self, item_id: str, reason: str = "cancelled by user") -> bool:
        item = self._items.get(item_id)
        if not item or item.state in (QueueItemState.COMPLETED, QueueItemState.FAILED, QueueItemState.CANCELLED):
            return False

        if item.license_handle:
            self.license_provider.release(item.license_handle)
            item.license_handle = None

        item.state = QueueItemState.CANCELLED
        item.finished_at = time.time()
        item.error = reason
        self._persist_state()
        return True

    def active_running_count(self) -> int:
        return sum(1 for it in self._items.values() if it.state == QueueItemState.RUNNING)

    def list_items(self, state: Optional[QueueItemState] = None) -> List[QueueItem]:
        if state is None:
            return list(self._items.values())
        return [it for it in self._items.values() if it.state == state]

    def process_next(self, current_time: Optional[float] = None) -> Optional[QueueItem]:
        """Dispatch pump step. Evaluates pending items, acquires licenses, and promotes to RUNNING."""
        now = current_time if current_time is not None else time.time()
        if self.active_running_count() >= self.max_concurrency:
            return None

        # Gather eligible candidates
        candidates = [
            it
            for it in self._items.values()
            if it.state in (QueueItemState.PENDING, QueueItemState.RETRYING) and now >= it.next_eligible_at
        ]
        if not candidates:
            return None

        # Sort by priority rank descending, then enqueued_at ascending
        candidates.sort(key=lambda it: (-it.priority.rank, it.enqueued_at))

        for item in candidates:
            # Check license availability
            item.state = QueueItemState.ACQUIRING_LICENSE
            handle = self.license_provider.reserve(
                feature=item.resources.feature,
                tokens=item.resources.tokens,
                timeout=0.0,
            )
            if handle is not None:
                item.license_handle = handle
                item.state = QueueItemState.RUNNING
                item.started_at = now
                self._persist_state()
                return item
            else:
                # License rejected/unavailable -> backoff and retry
                item.retry_count += 1
                if item.retry_count > item.max_retries:
                    item.state = QueueItemState.FAILED
                    item.finished_at = now
                    item.error = f"Exceeded max retries ({item.max_retries}) waiting for license tokens for {item.resources.feature}"
                else:
                    delay = compute_backoff(
                        retry_count=item.retry_count,
                        base=item.backoff_base,
                        max_delay=item.backoff_max,
                        jitter_ratio=item.jitter_ratio,
                    )
                    item.state = QueueItemState.RETRYING
                    item.next_eligible_at = now + delay
                    item.error = f"License exhausted; backing off for {delay:.2f}s (retry {item.retry_count}/{item.max_retries})"
                self._persist_state()

        return None

    def complete(self, item_id: str, result: Any = None) -> bool:
        item = self._items.get(item_id)
        if not item or item.state != QueueItemState.RUNNING:
            return False

        if item.license_handle:
            self.license_provider.release(item.license_handle)
            item.license_handle = None

        item.state = QueueItemState.COMPLETED
        item.finished_at = time.time()
        item.result = result
        self._persist_state()
        return True

    def fail(self, item_id: str, error: str, retryable: bool = False) -> bool:
        item = self._items.get(item_id)
        if not item:
            return False

        if item.license_handle:
            self.license_provider.release(item.license_handle)
            item.license_handle = None

        now = time.time()
        if retryable and item.retry_count < item.max_retries:
            item.retry_count += 1
            delay = compute_backoff(
                retry_count=item.retry_count,
                base=item.backoff_base,
                max_delay=item.backoff_max,
                jitter_ratio=item.jitter_ratio,
            )
            item.state = QueueItemState.RETRYING
            item.next_eligible_at = now + delay
            item.error = f"Task failed: {error}; backing off for {delay:.2f}s"
            self._persist_state()
            return True
        else:
            item.state = QueueItemState.FAILED
            item.finished_at = now
            item.error = error
            self._persist_state()
            return True

    def stats(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for it in self._items.values():
            key = it.state.value if hasattr(it.state, "value") else str(it.state)
            counts[key] = counts.get(key, 0) + 1
        return {
            "total_items": len(self._items),
            "max_concurrency": self.max_concurrency,
            "running_count": self.active_running_count(),
            "status_counts": counts,
            "license_health": self.license_provider.health().to_dict(),
        }
