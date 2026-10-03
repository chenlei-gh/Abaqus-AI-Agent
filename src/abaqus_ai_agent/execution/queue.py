import random
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

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
    """Production job execution queue with concurrency throttling, priority dispatch,

    and resilient license backoff.
    """

    def __init__(
        self,
        max_concurrency: int = 2,
        license_provider: Optional[LicenseProvider] = None,
        default_timeout: float = 3600.0,
    ):
        self.max_concurrency = max(1, max_concurrency)
        self.license_provider = license_provider or LocalLicenseProvider()
        self.default_timeout = default_timeout
        self._items: Dict[str, QueueItem] = {}

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
            return True
        else:
            item.state = QueueItemState.FAILED
            item.finished_at = now
            item.error = error
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
