import logging
import json
import os
from datetime import datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Attach extras if present
        for key, val in getattr(record, "__dict__", {}).items():
            if key.startswith("_extra_"):
                payload[key[7:]] = val
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(default_level: str | None = None) -> None:
    level_name = (default_level or os.getenv("LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    # Drop existing handlers (clean slate)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level)
    handler = logging.StreamHandler()
    # JSON by default; set LOG_PLAIN=1 for plain text
    if os.getenv("LOG_PLAIN", "0") in {"1", "true", "yes", "on"}:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    else:
        fmt = JsonFormatter()
    handler.setFormatter(fmt)
    root.addHandler(handler)
