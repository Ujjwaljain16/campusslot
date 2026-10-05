"""Structured JSON logging.

Every log line is one JSON object on standard output, which is what a log collector such as Loki
expects. Fields passed through ``extra=`` become top level keys, so a query like
``{app="campusslot"} | json | layer="database"`` works without any regular expression.
"""

import json
import logging
import sys
from datetime import UTC, datetime

# Attributes that every LogRecord has. Anything else came from ``extra=`` and is added to the line.
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                line[key] = value
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Route uvicorn's own messages through the same handler. The application middleware writes
    # the per-request line and can leave out the probe endpoints, so uvicorn's access log is off.
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
