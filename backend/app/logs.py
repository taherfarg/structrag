"""JSON logs with a per-request id, so one request's lines can be pulled out of the stream."""

import contextvars
import json
import logging
import time

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(r.created)), "level": r.levelname,
               "logger": r.name, "msg": r.getMessage(), "request_id": request_id.get()}
        out.update(getattr(r, "extra_fields", {}))
        if r.exc_info:
            out["exc"] = self.formatException(r.exc_info)
        return json.dumps(out, default=str)


def setup_logging(level: str = "INFO") -> None:
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[h], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
