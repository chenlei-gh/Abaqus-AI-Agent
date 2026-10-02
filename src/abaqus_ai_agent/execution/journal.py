from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class ActionRecord:
    action_id: str
    action_type: str
    phase: str
    started_at: str
    finished_at: str = None
    status: str = "PENDING"
    result: object = None
    error: str = None


@dataclass
class ExecutionJournal:
    records: list = field(default_factory=list)

    def start(self, action):
        record = ActionRecord(str(uuid.uuid4()), action.action_type, "execute",
                              _utc_now_iso())
        self.records.append(record)
        return record

    def finish(self, record, status, result=None, error=None):
        record.finished_at = _utc_now_iso()
        record.status, record.result, record.error = status, result, error
        return record
