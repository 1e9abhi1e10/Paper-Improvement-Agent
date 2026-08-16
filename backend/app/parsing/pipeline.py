"""The full parsing pipeline: PDF bytes -> Paper.

Steps (each in its own module, each surfacing diagnostics):
  1. extract.py    PDF -> layout-aware lines (font size, position)
  2. structure.py  lines -> title, abstract, sections
  3. references.py locate + segment the reference list
  4. fields.py     each entry -> CSL-JSON with a parse status
  5. intext.py     find in-text markers, resolve them, tokenize text
  6. style.py      detect the citation style (IEEE/APA) for rendering
"""
from __future__ import annotations

import uuid

from ..models import Diagnostic, Paper, Reference
from ..search import aggregate
from . import extract, fields, intext, references, structure, style


def parse_pdf(pdf_bytes: bytes, filename: str = "") -> Paper:
    diagnostics: list[Diagnostic] = []

    lines = extract.extract_lines(pdf_bytes)
    if not lines:
        return Paper(
            id=uuid.uuid4().hex[:12], filename=filename,
            year=extract.infer_year(filename, []),
            diagnostics=[Diagnostic(stage="extract", severity="error",
                                    message="No text could be extracted (scanned/image PDF?).")],
        )
    body_size = extract.body_font_size(lines)

    title, abstract, sections, diags = structure.parse_structure(lines)
    diagnostics += diags

    ref_lines, diags = references.find_reference_lines(lines, body_size)
    diagnostics += diags
    entries, scheme, remainder, diags = references.segment_entries(ref_lines)
    diagnostics += diags

    refs: list[Reference] = [fields.parse_entry(raw, f"ref{i + 1}") for i, raw in enumerate(entries)]
    if remainder:
        refs.append(Reference(id=f"ref{len(refs) + 1}", raw=remainder, parse_status="failed"))
    failed = [r for r in refs if r.parse_status == "failed"]
    partial = [r for r in refs if r.parse_status == "partial"]
    if failed:
        diagnostics.append(Diagnostic(
            stage="fields",
            message=f"{len(failed)} reference(s) could not be parsed into fields (kept raw): "
                    + ", ".join(r.id for r in failed[:10]),
        ))
    if partial:
        diagnostics.append(Diagnostic(
            stage="fields", severity="info",
            message=f"{len(partial)} reference(s) parsed only partially.",
        ))
    diagnostics.append(Diagnostic(
        stage="references", severity="info",
        message=f"Segmented {len(entries)} entries using the '{scheme}' scheme.",
    ))

    linked = aggregate.enrich_references(refs)
    verified = sum(1 for r in refs if r.resolution_status == "verified")
    low = sum(1 for r in refs if r.resolution_status == "low-confidence")
    if linked:
        diagnostics.append(Diagnostic(
            stage="fields", severity="info",
            message=f"Linked {linked} reference(s) to Semantic Scholar or OpenAlex "
                    f"({verified} verified, {low} low-confidence).",
        ))
    unverified = [r.id for r in refs if r.resolution_status == "unverified"
                  and r.parse_status != "failed"]
    if unverified:
        diagnostics.append(Diagnostic(
            stage="fields",
            message=f"{len(unverified)} parsed reference(s) could not be verified "
                    f"against OpenAlex/Semantic Scholar (kept, flagged unverified): "
                    + ", ".join(unverified[:10]),
        ))

    # Drop the references section itself from editable sections.
    sections = [s for s in sections
                if structure.normalize_heading(s.title) not in {
                    "references", "bibliography", "works cited", "literature cited"}]

    counter = [0]
    all_citations = []
    if abstract:
        abstract, abs_cits = intext.tokenize_section(abstract, "abstract", refs, counter)
        all_citations += abs_cits
    for section in sections:
        section.text, cits = intext.tokenize_section(section.text, section.id, refs, counter)
        all_citations += cits

    unresolved = [c for c in all_citations if not c.resolved]
    if unresolved:
        diagnostics.append(Diagnostic(
            stage="intext",
            message=f"{len(unresolved)} in-text marker(s) could not be fully resolved "
                    f"to reference entries; they were left verbatim in the text.",
        ))
    cited_ids = {rid for c in all_citations for rid in c.ref_ids}
    uncited = [r.id for r in refs if r.id not in cited_ids]
    if uncited:
        diagnostics.append(Diagnostic(
            stage="intext", severity="info",
            message=f"{len(uncited)} reference(s) never matched an in-text marker.",
        ))

    style_id, detected = style.detect_style(all_citations)
    if inconsistency := style.style_consistency(all_citations):
        diagnostics.append(Diagnostic(stage="style", message=inconsistency))

    return Paper(
        id=uuid.uuid4().hex[:12],
        filename=filename,
        title=title,
        abstract=abstract,
        page_count=extract.page_count(lines),
        layout=extract.detect_layout(lines),
        year=extract.infer_year(filename, lines),
        sections=sections,
        references=refs,
        intext=all_citations,
        style=style_id,
        style_detected=detected,
        diagnostics=diagnostics,
    )
