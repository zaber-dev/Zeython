"""Structured (JSON) logging -- an opt-in alternative to the framework's
default human-readable log line, for shipping logs to something that
parses JSON (Datadog, ELK/Logstash, CloudWatch Logs Insights, Splunk)
instead of grepping text. See docs/observability.md.
"""

from __future__ import annotations

import json
import logging
from typing import Any

#: Attributes every LogRecord already carries that add nothing once
#: formatted into the payload below -- excluded from the "extra fields"
#: pass so `logger.info("...", extra={"order_id": 42})` shows up as
#: {"order_id": 42} without also dumping `msg`, `args`, `pathname`, etc.
_STANDARD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Renders one JSON object per line: ``timestamp``, ``level``, ``logger``,
    ``message``, ``request_id`` (present whenever
    :class:`~zeython.request_id.RequestIdServiceProvider` is registered --
    ``"-"`` outside a request, same convention as the default text format),
    ``exception`` (the formatted traceback, only when the record carries
    one), plus any extra fields passed via ``logger.info(..., extra={...})``.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            payload["request_id"] = record.request_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and key != "request_id":
                payload[key] = value
        # default=str: an extra field carrying something non-JSON-native
        # (a Decimal, a datetime, a dataclass) degrades to its str() rather
        # than raising and losing the whole log line.
        return json.dumps(payload, default=str)


__all__ = ["JsonFormatter"]
