"""JSON audit events on stderr; never pass task text, arguments, or secrets here."""

import json
import sys
from datetime import datetime, timezone


class EventLogger:
    def __init__(self, agent, stream=None, task_id=None):
        self.agent = agent
        self.task_id = task_id
        self.stream = sys.stderr if stream is None else stream

    def emit(self, event, level="INFO", **fields):
        record = {"timestamp": datetime.now(timezone.utc).isoformat(),
                  "level": level, "agent": self.agent, "event": event, **fields}
        if self.task_id is not None:
            record["task_id"] = self.task_id
        print(json.dumps(record, ensure_ascii=True), file=self.stream, flush=True)
