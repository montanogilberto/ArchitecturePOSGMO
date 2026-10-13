"""
Answer cache — the same question gets the same answer without a new model
call. Keyed by the request (normalized text, website, language) AND the
version of GMO_MODULES.md, so editing that file invalidates old answers.
In-memory, per process: enough for one App Service instance.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict

MAX_ENTRIES = 500
TTL_SECONDS = 24 * 3600

_store: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()


def make_key(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def get(key: str) -> dict | None:
    hit = _store.get(key)
    if not hit:
        return None
    stored_at, value = hit
    if time.monotonic() - stored_at > TTL_SECONDS:
        _store.pop(key, None)
        return None
    _store.move_to_end(key)
    return value


def put(key: str, value: dict) -> None:
    _store[key] = (time.monotonic(), value)
    _store.move_to_end(key)
    while len(_store) > MAX_ENTRIES:
        _store.popitem(last=False)


def clear() -> None:
    _store.clear()
