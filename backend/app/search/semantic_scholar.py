"""Semantic Scholar Graph API client. API key optional (higher rate limits)."""
from __future__ import annotations

from typing import Any, Optional

import httpx

from ..config import SEMANTIC_SCHOLAR_API_KEY
from . import cache

BASE = "https://api.semanticscholar.org/graph/v1"
FIELDS = "title,abstract,year,authors,externalIds,url,venue,citationCount"


def _headers() -> dict:
    return {"x-api-key": SEMANTIC_SCHOLAR_API_KEY} if SEMANTIC_SCHOLAR_API_KEY else {}


def _get(endpoint: str, params: dict) -> Optional[Any]:
    cached = cache.get("s2", endpoint, params)
    if cached is not None:
        return cached
    try:
        resp = httpx.get(f"{BASE}{endpoint}", params=params, headers=_headers(), timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    cache.put("s2", endpoint, params, data)
    return data


def _post(endpoint: str, params: dict, body: dict) -> Optional[Any]:
    cached = cache.get("s2", endpoint, params, body=body)
    if cached is not None:
        return cached
    try:
        resp = httpx.post(
            f"{BASE}{endpoint}", params=params, json=body,
            headers=_headers(), timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    cache.put("s2", endpoint, params, data, body=body)
    return data


def _to_result(paper: dict) -> dict:
    authors = []
    for auth in (paper.get("authors") or [])[:25]:
        name = auth.get("name", "")
        if name:
            parts = name.rsplit(" ", 1)
            authors.append({"family": parts[-1], "given": parts[0] if len(parts) > 1 else ""})
    ids = paper.get("externalIds") or {}
    paper_id = paper.get("paperId") or ""
    api_url = paper.get("url") or ""
    # Always the paper page, never a search-results listing.
    if "/paper/" in api_url and "/search" not in api_url:
        url = api_url
    elif paper_id:
        url = f"https://www.semanticscholar.org/paper/{paper_id}"
    elif api_url and "/search" not in api_url:
        url = api_url
    else:
        url = ""
    return {
        "source": "semanticscholar",
        "external_id": paper_id,
        "url": url,
        "title": paper.get("title") or "",
        "year": paper.get("year"),
        "abstract": paper.get("abstract") or "",
        "venue": paper.get("venue") or "",
        "cited_by": paper.get("citationCount", 0),
        "doi": ids.get("DOI", ""),
        "authors": authors,
    }


def search(query: str, limit: int = 8) -> list[dict]:
    data = _get("/paper/search", {"query": query, "limit": limit, "fields": FIELDS})
    if not data:
        return []
    return [_to_result(p) for p in data.get("data", [])]


def by_title(title: str) -> Optional[dict]:
    """S2 match endpoint; callers corroborate before trusting the hit."""
    data = _get("/paper/search/match", {"query": title, "fields": FIELDS})
    if not data:
        return None
    papers = data.get("data") or ([data] if data.get("paperId") else [])
    if not papers:
        return None
    result = _to_result(papers[0])
    return result if result.get("title") else None


def by_ids(ids: list[str]) -> dict[str, dict]:
    """Batch lookup via POST /paper/batch (DOI:… / ARXIV:…, ≤500 per call)."""
    found: dict[str, dict] = {}
    clean = [i for i in ids if i]
    for i in range(0, len(clean), 500):
        batch = clean[i:i + 500]
        data = _post("/paper/batch", {"fields": FIELDS}, {"ids": batch})
        if not data:
            continue
        rows = data if isinstance(data, list) else data.get("data") or []
        for paper, requested in zip(rows, batch):
            if not paper or not isinstance(paper, dict) or not paper.get("paperId"):
                continue
            result = _to_result(paper)
            found[requested] = result
            if doi := (result.get("doi") or "").lower():
                found[f"DOI:{doi}"] = result
    return found


def by_doi(doi: str) -> Optional[dict]:
    data = _get(f"/paper/DOI:{doi}", {"fields": FIELDS})
    return _to_result(data) if data and data.get("paperId") else None


def by_arxiv(arxiv_id: str) -> Optional[dict]:
    arxiv_id = arxiv_id.replace("arXiv:", "").strip()
    if not arxiv_id:
        return None
    data = _get(f"/paper/ARXIV:{arxiv_id}", {"fields": FIELDS})
    return _to_result(data) if data and data.get("paperId") else None
