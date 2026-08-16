"""CSL-JSON -> biblatex export.

A mechanical field mapping from the canonical CSL-JSON items. Entries
whose CSL couldn't be parsed are emitted as @misc with their raw text in
a note -- surfaced, never dropped.
"""
from __future__ import annotations

from ..models import Paper, Reference

_TYPE_MAP = {
    "article-journal": "article",
    "paper-conference": "inproceedings",
    "chapter": "incollection",
    "book": "book",
    "thesis": "thesis",
    "report": "report",
}


def _escape(value: str) -> str:
    return value.replace("\\", "").replace("{", "\\{").replace("}", "\\}") \
                .replace("&", "\\&").replace("%", "\\%")


def _authors(csl: dict) -> str:
    names = []
    for author in csl.get("author") or []:
        family = author.get("family", "").strip()
        given = author.get("given", "").strip()
        if family and given:
            names.append(f"{family}, {given}")
        elif family or given:
            names.append(family or given)
    return " and ".join(names)


def _entry(ref: Reference) -> str:
    csl = ref.csl
    if not csl.get("title"):
        raw = _escape(ref.raw or ref.id)
        return (f"@misc{{{ref.id},\n"
                f"  note = {{Unparsed reference, raw text kept: {raw}}},\n}}")

    bibtype = _TYPE_MAP.get(csl.get("type", ""), "misc")
    fields: list[tuple[str, str]] = [("title", f"{{{_escape(csl['title'])}}}")]
    if authors := _authors(csl):
        fields.append(("author", _escape(authors)))
    issued = csl.get("issued", {}).get("date-parts", [[None]])
    if issued and issued[0] and issued[0][0]:
        fields.append(("year", str(issued[0][0])))
    if container := csl.get("container-title"):
        key = "journal" if bibtype == "article" else "booktitle"
        if bibtype not in ("article", "inproceedings", "incollection"):
            key = "howpublished"
        fields.append((key, _escape(container)))
    if doi := csl.get("DOI"):
        fields.append(("doi", doi))
    if url := csl.get("URL"):
        fields.append(("url", url))
    if (num := csl.get("number", "")) and num.startswith("arXiv:"):
        fields.append(("eprint", num.removeprefix("arXiv:")))
        fields.append(("eprinttype", "arxiv"))
    if ref.added_by_edit and ref.provenance:
        fields.append(("note", _escape(
            f"Added by edit; source: {ref.provenance.source} {ref.provenance.url}")))

    body = ",\n".join(f"  {k} = {{{v}}}" if not v.startswith("{") else f"  {k} = {v}"
                      for k, v in fields)
    return f"@{bibtype}{{{ref.id},\n{body},\n}}"


def export_bibtex(paper: Paper) -> str:
    header = (f"% Bibliography for: {paper.title}\n"
              f"% Exported from CSL-JSON by Paper Improvement Agent\n\n")
    return header + "\n\n".join(_entry(ref) for ref in paper.references) + "\n"
