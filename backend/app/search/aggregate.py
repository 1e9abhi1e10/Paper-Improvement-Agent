"""Search both providers, merge and dedupe, convert to CSL-JSON.

Every result keeps its provenance (source, id, url, abstract) so the
agent can only ever cite works that came back from a real API call.
"""
from __future__ import annotations

from typing import Optional

from ..models import Provenance, Reference
from . import match, openalex, semantic_scholar


def _norm_title(title: str) -> str:
    return "".join(ch for ch in title.lower() if ch.isalnum())


def _work_keys(doi: str = "", title: str = "") -> set[str]:
    """Dedup keys identifying one work: lowercase DOI + normalized title."""
    keys: set[str] = set()
    if doi:
        keys.add(doi.lower())
    if title:
        keys.add(_norm_title(title))
    return keys


def result_keys(result: dict) -> set[str]:
    return _work_keys(doi=result.get("doi", ""), title=result.get("title", ""))


def csl_keys(csl: dict) -> set[str]:
    return _work_keys(doi=csl.get("DOI", ""), title=csl.get("title", ""))


def search_all(query: str, limit: int = 8,
               exclude_titles: Optional[list[str]] = None) -> list[dict]:
    results = semantic_scholar.search(query, limit) + openalex.search(query, limit)
    seen: set[str] = set()
    merged: list[dict] = []
    for r in results:
        if not r["title"]:
            continue
        key = r["doi"] or _norm_title(r["title"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(r)
    if exclude_titles:
        merged = [r for r in merged if not _is_self(r, exclude_titles)]
    merged.sort(key=lambda r: r.get("cited_by") or 0, reverse=True)
    return merged


def _is_self(result: dict, exclude_titles: list[str]) -> bool:
    title = result.get("title") or ""
    return any(match.title_similarity(title, ex) >= 0.9 for ex in exclude_titles if ex)


def _title_candidates(title: str) -> list[dict]:
    """Gather title-search hits from both APIs for corroboration."""
    seen: set[str] = set()
    out: list[dict] = []
    for result in (
        [semantic_scholar.by_title(title)] + openalex.search(title, limit=5)
    ):
        if not result or not result.get("title"):
            continue
        key = result.get("doi") or _norm_title(result["title"])
        if key in seen:
            continue
        seen.add(key)
        out.append(result)
    return out


def resolve_reference(ref: Reference) -> Optional[dict]:
    """Find the real work behind a parsed reference (for abstracts and links).

    Order: DOI, arXiv id, then corroborated title match. A title hit
    without year/author agreement is kept as low-confidence, never
    silently trusted. Never a search-results page.
    """
    doi = ref.csl.get("DOI", "")
    if doi:
        for fn in (semantic_scholar.by_doi, openalex.by_doi):
            if result := fn(doi):
                result = {**result, "match_status": "verified"}
                return result
    number = str(ref.csl.get("number") or "")
    if number.lower().startswith("arxiv:"):
        if result := semantic_scholar.by_arxiv(number.split(":", 1)[1]):
            result = {**result, "match_status": "verified"}
            return result
    title = ref.csl.get("title", "")
    if title and len(title) > 15:
        return match.pick_title_match(ref, _title_candidates(title))
    return None


def lookup_identifiers(refs: list[Reference]) -> dict[str, dict]:
    """Batch DOI (OpenAlex) then leftover DOI/arXiv (Semantic Scholar)."""
    found: dict[str, dict] = {}
    by_doi: dict[str, list[Reference]] = {}
    by_arxiv: dict[str, list[Reference]] = {}
    for ref in refs:
        if doi := (ref.csl.get("DOI") or "").strip():
            by_doi.setdefault(doi.lower(), []).append(ref)
        number = str(ref.csl.get("number") or "")
        if number.lower().startswith("arxiv:"):
            by_arxiv.setdefault(number.split(":", 1)[1].strip(), []).append(ref)

    oa_hits = openalex.by_dois(list(by_doi)) if by_doi else {}
    for doi, result in oa_hits.items():
        result = {**result, "match_status": "verified"}
        for ref in by_doi.get(doi, []):
            found[ref.id] = result

    leftover_ids: list[str] = []
    id_to_refs: dict[str, list[Reference]] = {}
    for doi, group in by_doi.items():
        if any(r.id in found for r in group):
            continue
        key = f"DOI:{doi}"
        leftover_ids.append(key)
        id_to_refs[key] = group
    for arxiv_id, group in by_arxiv.items():
        if any(r.id in found for r in group):
            continue
        key = f"ARXIV:{arxiv_id}"
        leftover_ids.append(key)
        id_to_refs[key] = group

    if leftover_ids:
        s2_hits = semantic_scholar.by_ids(leftover_ids)
        for key, result in s2_hits.items():
            result = {**result, "match_status": "verified"}
            for ref in id_to_refs.get(key, []):
                found[ref.id] = result
    return found


def enrich_references(refs: list[Reference]) -> int:
    """Attach the exact Semantic Scholar / OpenAlex paper page to each ref.

    Identifier lookups are batched when there are enough entries to justify
    it (one OpenAlex OR-filter + one S2 POST /paper/batch). Leftovers and
    title-only entries go through per-ref resolution with SBMV corroboration.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    pending = [r for r in refs if r.parse_status != "failed"]
    if not pending:
        return 0

    found: dict[str, dict] = {}
    # Skip the batch path on tiny lists so unit tests that monkeypatch
    # resolve_reference (typically 1 ref) never hit the network.
    if len(pending) >= 3:
        try:
            found.update(lookup_identifiers(pending))
        except Exception:
            pass

    leftover = [r for r in pending if r.id not in found]

    def lookup(ref: Reference) -> tuple[str, Optional[dict]]:
        try:
            return ref.id, resolve_reference(ref)
        except Exception:
            return ref.id, None

    if leftover:
        with ThreadPoolExecutor(max_workers=min(6, len(leftover))) as pool:
            futs = [pool.submit(lookup, r) for r in leftover]
            for fut in as_completed(futs):
                rid, result = fut.result()
                if result:
                    found[rid] = result

    linked = 0
    for ref in refs:
        result = found.get(ref.id)
        if not result or _is_search_url(result.get("url", "")):
            if ref.parse_status != "failed" and ref.resolution_status == "unverified":
                if not ref.resolution_note:
                    ref.resolution_note = "No match on OpenAlex or Semantic Scholar."
            continue
        status = result.get("match_status") or "verified"
        if status not in ("verified", "low-confidence"):
            status = "verified"
        ref.resolution_status = status
        ref.resolution_note = (
            "Title matches but year/author could not be corroborated."
            if status == "low-confidence" else ""
        )
        if not result.get("url"):
            continue
        ref.provenance = result_provenance(result)
        if result.get("doi"):
            ref.csl.setdefault("DOI", result["doi"])
        existing = str(ref.csl.get("URL") or "")
        if _is_search_url(existing):
            ref.csl.pop("URL", None)
            existing = ""
        if not existing and result.get("doi"):
            ref.csl["URL"] = f"https://doi.org/{result['doi']}"
        linked += 1
    return linked


def retry_unverified(refs: list[Reference]) -> int:
    """Re-resolve only unverified / low-confidence entries; leave verified alone."""
    pending = [r for r in refs if r.resolution_status != "verified"]
    return enrich_references(pending) if pending else 0


def result_to_csl(result: dict, ref_id: str) -> dict:
    csl: dict = {
        "id": ref_id,
        "type": "article-journal" if result.get("venue") else "article",
        "title": result["title"],
    }
    if result.get("authors"):
        csl["author"] = result["authors"]
    if result.get("year"):
        csl["issued"] = {"date-parts": [[result["year"]]]}
    if result.get("venue"):
        csl["container-title"] = result["venue"]
    if result.get("doi"):
        csl["DOI"] = result["doi"]
    if result.get("url"):
        csl["URL"] = result["url"]
    return csl


def result_provenance(result: dict) -> Provenance:
    return Provenance(
        source=result["source"],
        external_id=result["external_id"],
        url=result["url"],
        abstract=result.get("abstract", ""),
    )


def _is_search_url(url: str) -> bool:
    return "/search" in (url or "")


def _best_reference_url(ref: Reference) -> str:
    """Exact paper page for a reference, never a search listing."""
    if ref.provenance and ref.provenance.url and not _is_search_url(ref.provenance.url):
        return ref.provenance.url
    url = str(ref.csl.get("URL") or "")
    if url.startswith("http") and not _is_search_url(url):
        return url
    if doi := ref.csl.get("DOI"):
        return f"https://doi.org/{doi}"
    number = str(ref.csl.get("number") or "")
    if number.lower().startswith("arxiv:"):
        return f"https://arxiv.org/abs/{number.split(':', 1)[1]}"
    return ""


def repair_references(refs: list[Reference]) -> int:
    """Fix legacy refs that still carry Semantic Scholar search URLs."""
    changed = 0
    for ref in refs:
        url = str(ref.csl.get("URL") or "")
        if _is_search_url(url):
            ref.csl.pop("URL", None)
            changed += 1
        if ref.provenance and _is_search_url(ref.provenance.url):
            ref.provenance = None
            changed += 1
    pending = [
        r for r in refs
        if r.parse_status != "failed" and not _best_reference_url(r)
    ]
    linked = enrich_references(pending) if pending else 0
    return changed + linked
