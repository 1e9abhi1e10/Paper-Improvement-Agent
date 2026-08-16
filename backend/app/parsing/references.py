"""Step 3: locate the reference list and segment it into entries.

Segmentation strategy, in order of reliability:
1. Bracketed numbers  ("[12] Author ...")        -> split on the marker.
2. Dotted numbers     ("12. Author ...")          -> split on the marker.
3. Author-year with hanging indent               -> split on x-position:
   entry-start lines sit at a smaller x0 than wrapped continuation lines,
   detected per column by clustering x0 values.
4. Fallback regex (line starts with an author-like pattern). Anything we
   cannot segment is returned as an "unsegmented" remainder and surfaced,
   never dropped.
"""
from __future__ import annotations

import re
from collections import Counter

from ..models import Diagnostic
from .extract import Line, join_hyphenated
from .structure import is_heading, normalize_heading

_BRACKET = re.compile(r"^\[(\d+)\]\s*")
_BRACKET_ENTRY = re.compile(r"\[(\d+)\]\s+(?=[A-Z])")
_DOT_NUM = re.compile(r"^(\d{1,3})\.\s+(?=\S)")
_AUTHOR_START = re.compile(r"^[A-Z][\w'\-]+,?\s+(?:[A-Z]\.|[A-Z][\w'\-]+)")

_END_HEADINGS = {"appendix", "appendices", "acknowledgments", "acknowledgements",
                 "supplementary material"}
# Headings like "Appendix A", "Appendix A: Results", "Acknowledgements and
# Disclosure" also end the reference list; match by prefix.
_END_PREFIXES = ("appendix", "acknowledgment", "acknowledgement", "supplementary")
# Figure/table captions and appendix openers that leak in after the last entry.
_STOP_LINE = re.compile(
    r"^(?:"
    r"appendices\s*$|appendix\b|acknowledg?e?ments\b|supplementary\b|"
    r"(?:figure|table|fig\.|tab\.)\s*\d|"
    r".{0,50}visualizations?\s*$"
    r")",
    re.I,
)
_TRAILING_JUNK = re.compile(
    r"\s+(?=(?:Figure|Table|Fig\.|Tab\.)\s*\d|"
    r"APPENDICES\b|Appendix\s+[A-Z0-9]|"
    r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+Visualizations?\b)",
)


_REF_HEADINGS = {"references", "bibliography", "works cited", "literature cited"}
_CITATION_SHAPED = re.compile(
    r"^(\[\d{1,3}\]|\d{1,3}\.\s|[A-Z][\w'\-]+,?\s+(?:[A-Z]\.\s*)+)"
)


def find_reference_lines(lines: list[Line], body_size: float) -> tuple[list[Line], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    start = None
    for i in range(len(lines) - 1, -1, -1):
        if normalize_heading(lines[i].text) in _REF_HEADINGS and is_heading(lines[i], body_size):
            start = i + 1
            break
    if start is None:
        # Tolerate non-heading typography for the References line itself.
        for i in range(len(lines) - 1, -1, -1):
            if normalize_heading(lines[i].text) in _REF_HEADINGS:
                start = i + 1
                break
    if start is None:
        run = _longest_citation_run(lines[len(lines) * 2 // 3:])
        if len(run) >= 5:
            diagnostics.append(Diagnostic(
                stage="references",
                message=f"No References heading found; used a citation-density "
                        f"scan ({len(run)} citation-shaped lines near the end).",
            ))
            return run, diagnostics
        diagnostics.append(Diagnostic(
            stage="references", severity="error",
            message="No 'References' section found in the PDF.",
        ))
        return [], diagnostics

    ref_lines: list[Line] = []
    table_streak = 0
    for line in lines[start:]:
        if _is_ref_section_end(line, body_size):
            break
        if _looks_like_table_row(line.text):
            table_streak += 1
            if table_streak >= 2 and ref_lines:
                break
            continue
        table_streak = 0
        ref_lines.append(line)
    return ref_lines, diagnostics


def _longest_citation_run(lines: list[Line]) -> list[Line]:
    """Longest run of citation-shaped lines, tolerating wrapped continuations."""
    best_start = best_len = 0
    run_start = -1
    misses = 0
    for i, line in enumerate(lines):
        if _CITATION_SHAPED.match(line.text.strip()):
            if run_start == -1:
                run_start = i
            misses = 0
        elif run_start != -1:
            misses += 1
            if misses > 3:
                length = i - misses - run_start
                if length > best_len:
                    best_start, best_len = run_start, length
                run_start = -1
                misses = 0
    if run_start != -1 and len(lines) - run_start > best_len:
        best_start, best_len = run_start, len(lines) - run_start
    return lines[best_start:best_start + best_len] if best_len else []


def _looks_like_table_row(text: str) -> bool:
    """True for result-table fragments (\"PE LS 1 hop 2 hops\") that leak
    in after the bibliography in many NeurIPS/ICLR PDFs."""
    t = text.strip()
    if not t or _BRACKET.match(t) or _DOT_NUM.match(t):
        return False
    tokens = t.split()
    if len(tokens) < 4:
        return False
    tiny = sum(1 for w in tokens if len(re.sub(r"[^A-Za-z0-9]", "", w)) <= 3)
    return tiny / len(tokens) >= 0.7


def _is_ref_section_end(line: Line, body_size: float) -> bool:
    """True when this line is no longer bibliography (appendix, figure, …)."""
    text = line.text.strip()
    if not text:
        return False
    if _STOP_LINE.match(text):
        return True
    norm = normalize_heading(text)
    if norm in _END_HEADINGS or norm.startswith(_END_PREFIXES):
        emphasized = line.bold or line.size > body_size + 0.3 or text.isupper()
        if is_heading(line, body_size) or emphasized:
            return True
    return False


def _column_of(line: Line) -> int:
    return 0 if line.x0 < line.page_width / 2 else 1


def _entry_start_x0s(ref_lines: list[Line]) -> dict[tuple[int, int], int]:
    """For hanging-indent layouts: per (page, column), find the x0 where
    entries begin. Of the two dominant x0 clusters, entry starts are the
    shallower one -- but only if its lines actually look like entry
    beginnings (author-name pattern). Columns that begin mid-entry have
    no valid start cluster and get none, instead of poisoning the rest."""
    groups: dict[tuple[int, int], list[Line]] = {}
    for line in ref_lines:
        groups.setdefault((line.page, _column_of(line)), []).append(line)

    starts: dict[tuple[int, int], int] = {}
    for key, lines in groups.items():
        counts = Counter(round(l.x0) for l in lines)
        top = [x for x, _ in counts.most_common(2)]
        if len(top) == 2 and abs(top[0] - top[1]) > 4:
            candidate = min(top)
        elif len(top) >= 1:
            candidate = top[0]
        else:
            continue
        members = [l for l in lines if abs(round(l.x0) - candidate) <= 2]
        author_like = sum(bool(_AUTHOR_START.match(l.text)) for l in members)
        if author_like >= max(2, len(members) * 0.5):
            starts[key] = candidate
    return starts


def segment_entries(ref_lines: list[Line]) -> tuple[list[str], str, str, list[Diagnostic]]:
    """Returns (entries, scheme, unsegmented_remainder, diagnostics)."""
    diagnostics: list[Diagnostic] = []
    if not ref_lines:
        return [], "none", "", diagnostics

    texts = [l.text for l in ref_lines]
    n = len(texts)
    blob = join_hyphenated(texts)

    def sequential(nums: list[int]) -> bool:
        """Markers of a real numbered reference list start near 1 and are
        (almost) monotonically increasing; stray bracketed numbers in prose
        or tables are not. Small gaps ([2] → [4]) are allowed — they are
        surfaced later, not a reason to reject the scheme."""
        if len(nums) < 3 or nums[0] > 2:
            return False
        stepping = sum(0 < (b - a) <= 3 for a, b in zip(nums, nums[1:]))
        return stepping >= (len(nums) - 1) * 0.8

    def split_on(pattern: re.Pattern) -> list[str]:
        entries, buf = [], []
        for t in texts:
            if pattern.match(t) and buf:
                entries.append(join_hyphenated(buf))
                buf = [t]
            else:
                buf.append(t)
        if buf:
            entries.append(join_hyphenated(buf))
        return entries

    def split_blob(pattern: re.Pattern) -> list[str] | None:
        """Split the concatenated block on markers anywhere in a line.
        Two-column PDFs often put \"[5] … 1995. [6] J. Goodman …\" on one
        extracted line; line-start matching would merge them."""
        matches = list(pattern.finditer(blob))
        if not sequential([int(m.group(1)) for m in matches]):
            return None
        entries = []
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(blob)
            entries.append(blob[m.start():end].strip())
        return entries

    if (entries := split_blob(_BRACKET_ENTRY)) is not None:
        return _finalize(entries, "bracket", diagnostics)
    if sequential([int(m.group(1)) for t in texts if (m := _DOT_NUM.match(t))]):
        return _finalize(split_on(_DOT_NUM), "dot-number", diagnostics)

    # Author-year: prefer layout (hanging indent), fall back to regex.
    start_x0s = _entry_start_x0s(ref_lines)
    entries: list[str] = []
    buf: list[str] = []
    for line in ref_lines:
        if start_x0s:
            group_start = start_x0s.get((line.page, _column_of(line)))
            is_start = group_start is not None and abs(round(line.x0) - group_start) <= 2
        else:
            is_start = bool(_AUTHOR_START.match(line.text))
        if is_start and buf:
            entries.append(join_hyphenated(buf))
            buf = [line.text]
        else:
            buf.append(line.text)
    if buf:
        entries.append(join_hyphenated(buf))

    scheme = "author-year-indent" if start_x0s else "author-year-regex"
    if len(entries) <= 1 and n > 4:
        diagnostics.append(Diagnostic(
            stage="references", severity="warning",
            message="Could not segment the reference list reliably; entries kept as one block.",
        ))
        return [], scheme, join_hyphenated(texts), diagnostics
    return _finalize(entries, scheme, diagnostics)


def _finalize(entries: list[str], scheme: str, diagnostics: list[Diagnostic]):
    cleaned = [_TRAILING_JUNK.split(e, maxsplit=1)[0].strip() for e in entries]
    cleaned = [e for e in cleaned if e]
    if scheme in {"bracket", "dot-number"}:
        nums: list[int] = []
        pat = _BRACKET if scheme == "bracket" else _DOT_NUM
        for entry in cleaned:
            if m := pat.match(entry):
                nums.append(int(m.group(1)))
        gaps = [f"{a} → {b}" for a, b in zip(nums, nums[1:]) if b != a + 1]
        if gaps:
            diagnostics.append(Diagnostic(
                stage="references",
                message=f"Numbered reference list has sequence gap(s): "
                        + ", ".join(gaps[:8]) + ". Entries kept, not dropped.",
            ))
        short = [e for e in cleaned if len(e) < 20]
        if short:
            diagnostics.append(Diagnostic(
                stage="references",
                message=f"{len(short)} implausibly short reference segment(s) kept: "
                        + "; ".join(e[:40] for e in short[:4]),
            ))
    return cleaned, scheme, "", diagnostics
