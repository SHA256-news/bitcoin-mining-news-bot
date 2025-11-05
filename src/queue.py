import json
import os
import pathlib
import time
from typing import List, Dict, Optional

QUEUE_FILE = os.getenv("QUEUE_FILE", ".state/queue.json")


def _path() -> pathlib.Path:
    p = pathlib.Path(QUEUE_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load() -> List[Dict]:
    p = _path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items: List[Dict]) -> None:
    p = _path()
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def push_many(items: List[Dict]) -> None:
    q = _load()
    ts = int(time.time())
    for it in items:
        it2 = dict(it)
        it2["ts"] = ts
        q.append(it2)
    _save(q)


def pop_one() -> Optional[Dict]:
    q = _load()
    if not q:
        return None
    item = q.pop()  # LIFO
    _save(q)
    return item