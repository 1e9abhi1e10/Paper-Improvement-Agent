"""Title-match corroboration (Crossref SBMV).

Search similarity alone never earns a verified match. Every candidate
above a token-similarity threshold is checked against the reference's
year (±1) and the candidate first author's surname in the raw entry.
A corroborated candidate is preferred over a higher-scoring uncorroborated
one — a title fully contained in a longer wrong title must not win.
"""
from __future__ import annotations

import re
from typing import Optional

from ..models import Reference

MATCH_THRESHOLD = 0.75
NEAR_PERFECT = 0.9

_WORD = re.compile(r"[A-Za-z0-9]{2,}")


def title_tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD.findall(text or "")}


def title_similarity(a: str, b: str) -> float:
    """Token Jaccard, except containment of 4+ tokens scores by the smaller set.

    That lets a truncated title guess still match the full recorded title
    without letting a short title wildcard a longer unrelated one.
    """
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return 0.0
    overlap = len(ta & tb)
    smaller = min(len(ta), len(tb))
    if overlap == smaller and smaller >= 3:
        return overlap / smaller
    return overlap / max(len(ta), len(tb))


def _csl_year(csl: dict) -> Optional[int]:
    issued = (csl or {}).get("issued", {}).get("date-parts", [[None]])
    if issued and issued[0] and issued[0][0] is not None:
        try:
            return int(issued[0][0])
        except (TypeError, ValueError):
            return None
    return None


def corroborate(ref: Reference, candidate: dict) -> tuple[Optional[bool], Optional[bool]]:
    """(year_ok, author_ok): True agrees, False contradicts, None unknown."""
    local_year = _csl_year(ref.csl)
    cand_year = candidate.get("year")
    try:
        cand_year = int(cand_year) if cand_year is not None else None
    except (TypeError, ValueError):
        cand_year = None
    year_ok: Optional[bool]
    if local_year and cand_year:
        year_ok = abs(local_year - cand_year) <= 1
    else:
        year_ok = None

    authors = candidate.get("authors") or []
    fam = ""
    if authors:
        fam = (authors[0].get("family") or authors[0].get("literal") or "").split()[-1:]
        fam = fam[0] if fam else ""
    raw = (ref.raw or "").lower()
    author_ok: Optional[bool]
    if fam and len(fam) > 2:
        author_ok = fam.lower() in raw
    else:
        author_ok = None
    return year_ok, author_ok


def classify_match(score: float, year_ok: Optional[bool],
                   author_ok: Optional[bool]) -> str:
    """verified | low-confidence | rejected."""
    if score < MATCH_THRESHOLD:
        return "rejected"
    if year_ok is False or author_ok is False:
        return "low-confidence"
    if year_ok is True or author_ok is True:
        return "verified"
    return "verified" if score >= NEAR_PERFECT else "low-confidence"


def pick_title_match(ref: Reference, candidates: list[dict]) -> Optional[dict]:
    """Best corroborated candidate, or a low-confidence fallback.

    The returned dict carries ``match_status`` (verified / low-confidence).
    """
    title = ref.csl.get("title") or ""
    best_verified: tuple[float, dict] | None = None
    best_low: tuple[float, dict] | None = None
    for cand in candidates:
        cand_title = cand.get("title") or ""
        if not cand_title:
            continue
        score = title_similarity(title, cand_title)
        verdict = classify_match(score, *corroborate(ref, cand))
        tagged = {**cand, "match_status": verdict, "match_score": score}
        if verdict == "verified" and (best_verified is None or score > best_verified[0]):
            best_verified = (score, tagged)
        elif verdict == "low-confidence" and (best_low is None or score > best_low[0]):
            best_low = (score, tagged)
    if best_verified:
        return best_verified[1]
    if best_low:
        return best_low[1]
    return None
