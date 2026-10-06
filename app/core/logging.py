"""JSON log lines.

Each line has the timestamp (UTC), level, logger and message, every field
passed with `extra=` (request_id, document_id, status, ...), and the trace
and span id when a trace is active, so a log line can be found from its
trace and the other way round.
"""

import json
import logging
from datetime import datetime, timezone

# Attributes every LogRecord has; anything else on a record came from `extra`.
_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "taskName"}


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_") and key not in log_record:
                log_record[key] = value
        ids = _trace_ids()
        if ids:
            log_record["trace_id"], log_record["span_id"] = ids
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_record, default=str)


def _trace_ids():
    try:
        from app.core.tracing import current_trace_ids
    except Exception:  # tracing is optional for logging
        return None
    return current_trace_ids()


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    root_logger.addHandler(handler)
