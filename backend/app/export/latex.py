"""Rebuild the (possibly edited) paper as a LaTeX document.

Citation tokens become \\cite{refid} commands and the bibliography is
emitted as a thebibliography environment whose entries are rendered by
citeproc in the paper's CSL style. Unparseable references are included
with their raw text and marked with a comment, never dropped.
"""
from __future__ import annotations

import re

from ..citations import csl
from ..models import Paper
from ..parsing.intext import TOKEN_RE

_SPECIALS = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def _escape(text: str) -> str:
    return "".join(_SPECIALS.get(ch, ch) for ch in text)


def _text_to_latex(text: str) -> str:
    parts: list[str] = []
    pos = 0
    for m in TOKEN_RE.finditer(text):
        parts.append(_escape(text[pos:m.start()]).rstrip())
        keys = m.group(1)
        parts.append(f"~\\cite{{{keys}}}")
        pos = m.end()
    parts.append(_escape(text[pos:]))
    return "".join(parts)


def export_latex(paper: Paper) -> str:
    rendered = csl.render(paper.references, paper.style)
    lines: list[str] = [
        "\\documentclass[11pt]{article}",
        "\\usepackage[margin=1in]{geometry}",
        "\\usepackage{cite}",
        f"% Exported by Paper Improvement Agent (citation style: {paper.style} via CSL)",
        f"\\title{{{_escape(paper.title)}}}",
        "\\date{}",
        "\\begin{document}",
        "\\maketitle",
    ]
    if paper.abstract:
        lines += ["\\begin{abstract}", _text_to_latex(paper.abstract), "\\end{abstract}"]

    for section in paper.sections:
        cmd = "section" if section.level <= 1 else ("subsection" if section.level == 2 else "subsubsection")
        title = re.sub(r"^(\d+|[IVXL]+)(\.\d+)*\.?\s+", "", section.title)
        lines += [f"\\{cmd}{{{_escape(title)}}}", "", _text_to_latex(section.text), ""]

    lines.append(f"\\begin{{thebibliography}}{{{len(paper.references)}}}")
    for ref in paper.references:
        entry = rendered.get(ref.id, {}).get("entry") or ref.raw or ref.id
        note = ""
        if ref.parse_status == "failed":
            note = "  % WARNING: entry could not be parsed; raw text kept"
        elif ref.added_by_edit and ref.provenance:
            note = f"  % added by edit, source: {ref.provenance.source} {ref.provenance.url}"
        lines.append(f"\\bibitem{{{ref.id}}} {_escape(entry)}{note}")
    lines += ["\\end{thebibliography}", "\\end{document}"]
    return "\n".join(lines)
