"""OpenAlex client (no API key required). Honest failures: network or
empty results raise/return empty rather than fabricating anything."""
from __future__ import annotations

from typing import Any, Optional

import httpx

from ..config import OPENALEX_MAILTO
from . import cache

BASE = "https://api.openalex.org"
FIELDS = "id,doi,title,display_name,publication_year,authorships,abstract_inverted_index,primary_location,cited_by_count"


def _get(endpoint: str, params: dict) -> Optional[Any]:
    cached = cache.get("openalex", endpoint, params)
    if cached is not None:
        return cached
    try:
        resp = httpx.get(f"{BASE}{endpoint}", params={**params, "mailto": OPENALEX_MAILTO}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    cache.put("openalex", endpoint, params, data)
    return data


def _deinvert_abstract(inverted: Optional[dict]) -> str:
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        positions.extend((i, word) for i in idxs)
    return " ".join(w for _, w in sorted(positions))


def _to_result(work: dict) -> dict:
    """Normalize an OpenAlex work into our common search-result shape."""
    year = work.get("publication_year")
    authors = []
    for auth in (work.get("authorships") or [])[:25]:
        name = (auth.get("author") or {}).get("display_name", "")
        if name:
            parts = name.rsplit(" ", 1)
            authors.append({"family": parts[-1], "given": parts[0] if len(parts) > 1 else ""})
    venue = ((work.get("primary_location") or {}).get("source") or {}).get("display_name", "")
    return {
        "source": "openalex",
        "external_id": work.get("id", ""),
        "url": work.get("doi") or work.get("id", ""),
        "title": work.get("display_name") or work.get("title") or "",
        "year": year,
        "abstract": _deinvert_abstract(work.get("abstract_inverted_index")),
        "venue": venue,
        "cited_by": work.get("cited_by_count", 0),
        "doi": (work.get("doi") or "").replace("https://doi.org/", ""),
        "authors": authors,
    }


def search(query: str, limit: int = 8) -> list[dict]:
    data = _get("/works", {"search": query, "per-page": limit, "select": FIELDS})
    if not data:
        return []
    return [_to_result(w) for w in data.get("results", [])]


def by_doi(doi: str) -> Optional[dict]:
    data = _get(f"/works/https://doi.org/{doi}", {})
    return _to_result(data) if data else None


def by_dois(dois: list[str]) -> dict[str, dict]:
    """Batch DOI lookup via OpenAlex OR-filter (≤50 per request)."""
    found: dict[str, dict] = {}
    clean = [d.strip() for d in dois if d and d.strip()]
    for i in range(0, len(clean), 50):
        batch = clean[i:i + 50]
        filt = "|".join(f"doi:{d}" for d in batch)
        data = _get("/works", {"filter": filt, "per-page": 50, "select": FIELDS})
        if not data:
            continue
        for work in data.get("results") or []:
            result = _to_result(work)
            doi = (result.get("doi") or "").lower()
            if doi:
                found[doi] = result
    return found


def by_title(title: str) -> Optional[dict]:
    """Return the top search hit; callers corroborate before trusting it."""
    results = search(title, limit=5)
    return results[0] if results else None
