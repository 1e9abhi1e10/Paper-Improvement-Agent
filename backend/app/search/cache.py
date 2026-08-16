"""Tiny on-disk JSON cache for external API calls.

Keeps the demo reproducible and polite to the APIs. Keyed by a hash of
(service, endpoint, params). No TTL: academic search results are stable
enough for this app's lifetime; delete backend/data/cache to refresh.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from ..config import CACHE_DIR


def _key(service: str, endpoint: str, params: dict, body: Any = None) -> str:
    blob = json.dumps([service, endpoint, params, body], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def get(service: str, endpoint: str, params: dict, body: Any = None) -> Optional[Any]:
    path = CACHE_DIR / f"{_key(service, endpoint, params, body)}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None
    return None


def put(service: str, endpoint: str, params: dict, value: Any, body: Any = None) -> None:
    path = CACHE_DIR / f"{_key(service, endpoint, params, body)}.json"
    path.write_text(json.dumps(value))
