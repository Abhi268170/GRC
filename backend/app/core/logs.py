"""Logging: one line per record, with the request (or job) id when there is one."""

import contextvars
import logging

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestId(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


def setup(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"))
    handler.addFilter(_RequestId())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
