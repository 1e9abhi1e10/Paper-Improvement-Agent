"""Citation rendering via citeproc-py and official CSL styles.

CSL-JSON is the one canonical citation model in this app. This module is
the only place citations are ever *formatted*: inline labels and
bibliography entries both come from the CSL style file (apa.csl /
ieee.csl), never from hand-written templates.
"""
from __future__ import annotations

import re
import warnings
from functools import lru_cache

from citeproc import (Citation, CitationItem, CitationStylesBibliography,
                      CitationStylesStyle, formatter)
from citeproc.source.json import CiteProcJSON

from ..config import STYLES_DIR
from ..models import Paper, Reference

AVAILABLE_STYLES = ["ieee", "apa"]


@lru_cache(maxsize=8)
def _load_style(style_id: str) -> CitationStylesStyle:
    path = STYLES_DIR / f"{style_id}.csl"
    if not path.exists():
        path = STYLES_DIR / "ieee.csl"
    return CitationStylesStyle(str(path), validate=False)


def _sanitize(ref: Reference) -> dict:
    """Keep only fields citeproc-py handles well. Bibliography text only
    ever shows identifier URLs (DOI, arXiv); paper-page links with long
    hashes stay in provenance for the UI to render as chips."""
    keep = {"id", "type", "title", "author", "issued", "container-title",
            "volume", "issue", "page", "DOI", "URL", "publisher", "number"}
    clean = {k: v for k, v in ref.csl.items() if k in keep and v}
    clean.setdefault("type", "article-journal")
    url = str(clean.get("URL") or "")
    if "DOI" in clean or not ("arxiv.org" in url or "doi.org" in url):
        clean.pop("URL", None)
    return clean


def _build_bibliography(references: list[Reference], style_id: str):
    items = []
    for ref in references:
        if ref.csl.get("title"):
            items.append(_sanitize(ref))
    source = CiteProcJSON(items)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        bib = CitationStylesBibliography(_load_style(style_id), source, formatter.plain)
    return bib, {i["id"] for i in items}


def render(paper_refs: list[Reference], style_id: str) -> dict[str, dict[str, str]]:
    """Render every reference: {ref_id: {"inline": "[1]", "entry": "..."}}.

    References whose CSL couldn't be parsed fall back to their raw text
    and an inline label of their id, flagged upstream via parse_status.
    """
    bib, renderable = _build_bibliography(paper_refs, style_id)
    citations: dict[str, Citation] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for ref in paper_refs:
            if ref.id in renderable:
                cit = Citation([CitationItem(ref.id)])
                bib.register(cit)
                citations[ref.id] = cit

        out: dict[str, dict[str, str]] = {}
        for ref in paper_refs:
            if ref.id in citations:
                try:
                    inline = str(bib.cite(citations[ref.id], lambda item: None))
                except Exception:
                    inline = f"[{ref.id}]"
            else:
                inline = f"[{ref.id}]"
            out[ref.id] = {"inline": inline, "entry": ""}

        # IEEE numbers are list position, not citeproc's citation-order
        # counter. That keeps \"[8]\" in the paper aligned with bibliography
        # item 8, and never falls back to a raw id like \"[ref8]\".
        if style_id == "ieee":
            for i, ref in enumerate(paper_refs, 1):
                out[ref.id]["inline"] = f"[{i}]"

        try:
            entries = [str(e) for e in bib.bibliography()]
            order = [ref.id for ref in paper_refs if ref.id in renderable]
            for ref_id, entry in zip(order, entries):
                if style_id == "ieee":
                    entry = re.sub(r"^\[\d+\]\s*", "", entry)
                out[ref_id]["entry"] = entry
        except Exception:
            pass

    for ref in paper_refs:
        if not out.get(ref.id, {}).get("entry"):
            out.setdefault(ref.id, {"inline": f"[{ref.id}]", "entry": ""})
            out[ref.id]["entry"] = ref.raw or ref.csl.get("title", ref.id)
    if style_id == "ieee":
        for i, ref in enumerate(paper_refs, 1):
            out.setdefault(ref.id, {"inline": f"[{i}]", "entry": ""})
            out[ref.id]["inline"] = f"[{i}]"
    return out


def bibliography_payload(paper: Paper) -> list[dict]:
    """CSL-rendered bibliography for the UI: one entry + inline label per
    reference, in list order, with its parse status."""
    rendered = render(paper.references, paper.style)
    return [{"ref_id": r.id, "entry": rendered[r.id]["entry"],
             "inline": rendered[r.id]["inline"],
             "parse_status": r.parse_status} for r in paper.references]
