"""Step 5: locate in-text citation markers and tokenize them.

Numeric markers ("[3]", "[1, 4-6]") are mapped to references by their
list position. Author-year markers — parenthetical
("(Smith et al., 2020; Lee, 2019)") and narrative ("Smith et al. (2020)")
— are matched by first-author family + year against the parsed CSL-JSON.
Ambiguous matches are reported, never guessed. Every resolved marker
becomes a token ``[[cite:ref3,ref4]]``; unresolved markers stay verbatim.
"""
from __future__ import annotations

import re
from typing import Optional

from ..models import InTextCitation, Reference

_NUMERIC_RE = re.compile(r"\[(\d{1,3}(?:\s*[,\u2013\u2014-]\s*\d{1,3})*)\]")
_AUTHOR_YEAR_RE = re.compile(
    r"\((?=[^()]*\d{4})([A-Z][^()]{0,150}?\d{4}[a-z]?(?:,\s*p+\.\s*[\d\u2013-]+)?"
    r"(?:;\s*[^();]{0,150}?\d{4}[a-z]?)*)\)"
)
_NARRATIVE_AY_RE = re.compile(
    r"\b([A-Z][\w'@.&-]+)(?:\s+et al\.?|\s+(?:and|&)\s+[A-Z][\w'\-]+)?"
    r"\s+\(((?:19|20)\d{2}[a-z]?)\)"
)
_YEAR_TOKEN_RE = re.compile(r"((?:19|20)\d{2})([a-z])?((?:\s*,\s*[a-z]\b)*)")
_SURNAME_RE = re.compile(r"[A-Z][\w'@.&-]+")
TOKEN_RE = re.compile(r"\[\[cite:([A-Za-z0-9_,-]+)\]\]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_NAME_WORD = re.compile(r"[A-Za-z][\w'\-]{2,}")


def split_sentences(text: str) -> list[str]:
    """Split on end-of-sentence punctuation. Shared by review, editing, and Q&A
    so claim/sentence boundaries stay consistent across the agent."""
    return _SENTENCE_SPLIT.split(text)


def _expand_numeric(group: str) -> list[int]:
    nums: list[int] = []
    for part in re.split(r"[,;]", group):
        part = part.strip()
        m = re.match(r"^(\d+)\s*[\u2013\u2014-]\s*(\d+)$", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if hi - lo < 50:
                nums.extend(range(lo, hi + 1))
        elif part.isdigit():
            nums.append(int(part))
    return nums


def _year_tokens(chunk: str) -> list[str]:
    """Expand natbib groups: '2023, 2024a,b' → 2023, 2024a, 2024b."""
    tokens: list[str] = []
    for ym in _YEAR_TOKEN_RE.finditer(chunk):
        if not ym.group(2):
            tokens.append(ym.group(1))
            continue
        tokens.append(ym.group(1) + ym.group(2))
        for letter in re.findall(r"[a-z]", ym.group(3) or ""):
            tokens.append(ym.group(1) + letter)
    return tokens


def _ref_year(ref: Reference) -> Optional[int]:
    issued = ref.csl.get("issued", {}).get("date-parts", [[None]])
    if issued and issued[0] and issued[0][0] is not None:
        try:
            return int(issued[0][0])
        except (TypeError, ValueError):
            return None
    return None


def _author_tokens(ref: Reference) -> set[str]:
    """Whole-token names we can match against a citation surname."""
    tokens: set[str] = set()
    authors = ref.csl.get("author") or []
    if not authors:
        return tokens
    first = authors[0]
    family = (first.get("family") or "").lower()
    if family:
        tokens.add(family)
    literal = (first.get("literal") or "").lower()
    if literal:
        tokens.add(literal)
        tokens.update(_NAME_WORD.findall(literal))
    full = f"{first.get('given', '')} {first.get('family', '')}"
    tokens.update(t.lower() for t in _NAME_WORD.findall(full)[-3:])
    return {t for t in tokens if t}


def find_by_author_year(references: list[Reference], surname: str,
                        year: str) -> Optional[str]:
    """Unique ref id for surname+year, or None if missing/ambiguous.

    Multiple surviving candidates are never guessed: a silently wrong
    link is citation corruption. Letter suffixes ('2019a') disambiguate
    via the raw entry text. Short org names match as whole tokens only.
    """
    letter = year[-1] if year and year[-1].isalpha() else ""
    try:
        year_num = int(year[:-1] if letter else year)
    except ValueError:
        return None
    lower = surname.lower()
    boundary = re.compile(
        rf"(^|[^\w]){re.escape(lower)}([^\w]|$)", re.I,
    )
    candidates: list[Reference] = []
    for ref in references:
        if _ref_year(ref) != year_num:
            continue
        names = _author_tokens(ref)
        in_authors = lower in names
        in_raw = bool(boundary.search((ref.raw or "")[:120]))
        if in_authors or in_raw:
            candidates.append(ref)
    if not candidates:
        return None
    if letter:
        suffixed = [r for r in candidates if f"{year_num}{letter}" in (r.raw or "")]
        if len(suffixed) == 1:
            return suffixed[0].id
        if suffixed:
            return None  # still ambiguous among suffixed entries
    if len(candidates) == 1:
        return candidates[0].id
    return None  # ambiguous: do not guess


def tokenize_section(
    text: str,
    section_id: str,
    references: list[Reference],
    counter: list[int],
) -> tuple[str, list[InTextCitation]]:
    citations: list[InTextCitation] = []
    num_refs = len(references)

    def next_id() -> str:
        counter[0] += 1
        return f"cit{counter[0]}"

    def sub_numeric(m: re.Match) -> str:
        nums = _expand_numeric(m.group(1))
        ref_ids = [f"ref{n}" for n in nums if 1 <= n <= num_refs]
        resolved = bool(ref_ids) and len(ref_ids) == len(nums)
        cit = InTextCitation(
            id=next_id(), raw=m.group(0), section_id=section_id,
            ref_ids=ref_ids, resolved=resolved,
        )
        citations.append(cit)
        return f"[[cite:{','.join(ref_ids)}]]" if resolved else m.group(0)

    def sub_author_year(m: re.Match) -> str:
        ref_ids: list[str] = []
        all_matched = True
        any_cite = False
        for chunk in m.group(1).split(";"):
            fam = _SURNAME_RE.search(chunk)
            years = _year_tokens(chunk)
            if not fam or not years:
                continue
            any_cite = True
            for year in years:
                rid = find_by_author_year(references, fam.group(0), year)
                if rid:
                    ref_ids.append(rid)
                else:
                    all_matched = False
        if not any_cite or not ref_ids:
            return m.group(0)
        cit = InTextCitation(
            id=next_id(), raw=m.group(0), section_id=section_id,
            ref_ids=ref_ids, resolved=all_matched,
        )
        citations.append(cit)
        return f"[[cite:{','.join(ref_ids)}]]" if all_matched else m.group(0)

    def sub_narrative(m: re.Match) -> str:
        rid = find_by_author_year(references, m.group(1), m.group(2))
        if not rid:
            # Unmatched narrative is often not a citation ("Appendix (2017)").
            # Ambiguous or unknown: leave verbatim, don't invent a link.
            return m.group(0)
        cit = InTextCitation(
            id=next_id(), raw=m.group(0), section_id=section_id,
            ref_ids=[rid], resolved=True,
        )
        citations.append(cit)
        return f"[[cite:{rid}]]"

    if num_refs:
        text = _NUMERIC_RE.sub(sub_numeric, text)
        text = _AUTHOR_YEAR_RE.sub(sub_author_year, text)
        text = _NARRATIVE_AY_RE.sub(sub_narrative, text)
    return text, citations


def extract_tokens(text: str) -> list[str]:
    """All citation tokens in a text, flattened to individual ref ids."""
    out: list[str] = []
    for m in TOKEN_RE.finditer(text):
        out.extend(r for r in m.group(1).split(",") if r)
    return out
