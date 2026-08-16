"""Step 2: layout lines -> title, abstract, sections.

Heading detection combines three signals: numbering patterns
("3", "3.1", roman numerals), canonical section names, and typography
(font size above body size, or bold). Title = the largest text near the
top of page one. Abstract = text between the "Abstract" heading and the
next heading.
"""
from __future__ import annotations

import re

from ..models import Diagnostic, Section
from .extract import Line, body_font_size, join_hyphenated

_HEADING_WORDS = {
    "abstract", "introduction", "related work", "background", "preliminaries",
    "method", "methods", "methodology", "approach", "model", "experiments",
    "experimental setup", "evaluation", "results", "results and discussion",
    "analysis", "discussion", "limitations", "conclusion", "conclusions",
    "future work", "acknowledgments", "acknowledgements", "references",
    "bibliography", "works cited", "literature cited",
    "appendix", "appendices", "broader impact", "ethics statement",
}

_NUMBERED = re.compile(r"^(\d+|[IVXL]+)(\.\d+)*\.?\s+[A-Z\u201c\"]")
_NUMBER_ONLY = re.compile(r"^(\d+(\.\d+)*|[IVXL]+)\.?$")


def normalize_heading(text: str) -> str:
    """Heading text with numbering, trailing punctuation and case stripped,
    for comparison against canonical section names."""
    return re.sub(r"^(\d+|[IVXL]+)(\.\d+)*\.?\s+", "", text).strip().rstrip(":. ").lower()


def is_heading(line: Line, body_size: float) -> bool:
    t = line.text.strip()
    if not t or len(t) > 120:
        return False
    emphasized = line.size > body_size + 0.3 or line.bold or t.isupper()
    if _NUMBERED.match(t) and emphasized and not t.rstrip().endswith((".", ",", ";")):
        # Numbered *list items* also match ("2. Layer-wise (RNN-like): the
        # input and output embeddings are..."): reject long lines and lines
        # that continue in lowercase after a colon.
        if len(t) > 70 or re.search(r":\s+[a-z]", t):
            return False
        # "2018. URL ..." and similar wrapped bibliography lines are not
        # section headings; real section numbers never exceed 99.
        num = re.match(r"^(\d+)", t)
        if num and int(num.group(1)) > 99:
            return False
        return True
    if normalize_heading(t) in _HEADING_WORDS and emphasized:
        return True
    return False


def heading_level(text: str) -> int:
    m = re.match(r"^(\d+(\.\d+)*)", text.strip())
    if m:
        return m.group(1).count(".") + 1
    return 1


def _merge_split_headings(lines: list[Line], body_size: float) -> list[Line]:
    """PDF extractors often split "3 Model Architecture" into a number
    line and a text line at the same vertical position; re-join them."""
    merged: list[Line] = []
    skip = False
    for i, line in enumerate(lines):
        if skip:
            skip = False
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if (nxt is not None
                and _NUMBER_ONLY.match(line.text.strip())
                and line.page == nxt.page
                and abs(line.y0 - nxt.y0) < 3
                and nxt.text[:1].isupper()
                and (line.size > body_size + 0.3 or line.bold)):
            merged.append(Line(
                text=f"{line.text.strip()} {nxt.text.strip()}",
                size=max(line.size, nxt.size),
                bold=line.bold or nxt.bold, x0=line.x0, y0=line.y0,
                page=line.page, page_width=line.page_width,
            ))
            skip = True
        else:
            merged.append(line)
    return merged


def parse_structure(lines: list[Line]) -> tuple[str, str, list[Section], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    body = body_font_size(lines)
    lines = _merge_split_headings(lines, body)

    # Title: largest-font line(s) near the top of page one — not the first
    # numbered heading, which is often set larger than the title itself
    # (ICLR-style papers).
    page1 = [l for l in lines if l.page == 0]
    title = ""
    if page1:
        top = [l for l in page1[:18]
               if len(l.text) > 3
               and not _NUMBER_ONLY.match(l.text.strip())
               and not _NUMBERED.match(l.text.strip())]
        if top:
            max_size = max(l.size for l in top)
            title_lines = [l.text for l in top if l.size >= max_size - 0.2]
            title = join_hyphenated(title_lines[:3])
    if not title:
        diagnostics.append(Diagnostic(stage="structure", message="Could not detect a title."))

    # Walk lines, splitting at headings.
    sections: list[Section] = []
    abstract = ""
    current_title, current_level, buffer = "", 1, []
    started = False

    def flush() -> None:
        nonlocal buffer, abstract
        text = join_hyphenated(buffer)
        norm = normalize_heading(current_title)
        if norm == "abstract":
            abstract = text
        elif started and current_title:
            sections.append(Section(
                id=f"sec{len(sections) + 1}",
                title=current_title,
                level=current_level,
                text=text,
            ))
        buffer = []

    for line in lines:
        if line.text == title:
            continue
        if is_heading(line, body):
            flush()
            current_title = line.text.strip()
            current_level = heading_level(current_title)
            started = True
        elif line.size >= body - (1.2 if normalize_heading(current_title) == "abstract" else 0.7):
            # Sub-body-size text is footnotes, captions or page banners,
            # not section prose. Abstracts are often set ~1pt smaller.
            buffer.append(line.text)
    flush()

    if not sections:
        diagnostics.append(Diagnostic(
            stage="structure", severity="error",
            message="No section headings detected; treating full text as one section.",
        ))
        sections = [Section(id="sec1", title="Body", text=join_hyphenated([l.text for l in lines]))]
    if not abstract:
        diagnostics.append(Diagnostic(stage="structure", message="No abstract detected."))
    return title, abstract, sections, diagnostics
