from dataclasses import dataclass, field
from datetime import datetime
import uuid


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
                              datetime.utcnow().isoformat() + "Z")
        self.records.append(record)
        return record

    def finish(self, record, status, result=None, error=None):
        record.finished_at = datetime.utcnow().isoformat() + "Z"
        record.status, record.result, record.error = status, result, error
        return record
