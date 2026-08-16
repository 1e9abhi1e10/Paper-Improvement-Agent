"""Step 4: one raw reference entry -> a CSL-JSON item.

Best-effort field extraction with an explicit parse status:
- "parsed"  : title and year found (enough to resolve against the APIs)
- "partial" : some fields found
- "failed"  : nothing beyond the raw string; surfaced, never dropped
"""
from __future__ import annotations

import re

from ..models import Reference

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s,;]+)", re.I)
# Tolerate "arXiv:1607.06450", "arXiv preprint: 1502.03044", "arxiv.org/abs/1611.06194".
_ARXIV_RE = re.compile(r"arxiv\D{0,15}(\d{4}\.\d{4,5})", re.I)
# CoRR / "abs/1409.0473" (often without the word arXiv on the same span).
_CORR_ABS_RE = re.compile(r"\babs[/:]\s*(\d{4}\.\d{4,5})", re.I)
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})[a-z]?\b")
_PAREN_YEAR_RE = re.compile(r"\(((19|20)\d{2})[a-z]?\)")
# ACL/CS: "Authors. 2018. Title." — year as its own sentence.
_ACL_YEAR_RE = re.compile(r"\.\s*((?:19|20)\d{2}[a-z]?)\.\s+")
_QUOTED_TITLE_RE = re.compile(r"[\"\u201c](.+?)[\"\u201d]")
# IEEE Access sets quotes as doubled single quotes: ‘‘Title,’’
_DOUBLED_QUOTE_RE = re.compile(r"[\u2018']{2}(.+?)[,.]?[\u2019']{2}")
_URL_RE = re.compile(r"https?://[^\s,;]+")

_MARKER = re.compile(r"^(\[\d+\]|\d{1,3}\.)\s*")
_NAME_TOKEN = re.compile(r"(?:[A-Z][\w'\u00c0-\u017f\-]*\.?|and|&|et|al\.?|[A-Z]\.)$")
_TITLE_FUNCTION_WORDS = {
    "a", "an", "the", "of", "for", "and", "in", "on", "to", "with", "from",
    "using", "via", "into", "over", "by", "at",
}
_PARTICLES = {
    "van", "von", "der", "den", "de", "del", "della", "da", "di", "la", "le",
    "ter", "ten", "dos", "du",
}
# Wrapped identifiers that join_hyphenated missed (space already inserted).
_GLUE_ID = re.compile(
    r"((?:arxiv:|abs/|arxiv\.org/abs/)\d{4}\.)\s+(\d{4,5})", re.I,
)


def _repair_wrapped_ids(text: str) -> str:
    return _GLUE_ID.sub(r"\1\2", text)


def _extract_arxiv_id(text: str) -> str | None:
    if m := _ARXIV_RE.search(text):
        return m.group(1)
    if m := _CORR_ABS_RE.search(text):
        return m.group(1)
    return None


def _year_from_arxiv(arxiv_id: str) -> int:
    yy = int(arxiv_id[:2])
    return 2000 + yy if yy < 80 else 1900 + yy


def _extract_year(text: str) -> int | None:
    """The publication year. Prefer a parenthesized year (APA); otherwise
    take the LAST plausible year, skipping numbers that are part of a
    numeric range like page spans ("pages 1914– 1925" or "15(1):1929-1958")."""
    if m := _PAREN_YEAR_RE.search(text):
        return int(m.group(1))
    if m := _ACL_YEAR_RE.search(text):
        return int(m.group(1)[:4])
    candidates = []
    for m in _YEAR_RE.finditer(text):
        before = text[max(0, m.start() - 3):m.start()]
        after = text[m.end():m.end() + 1]
        if re.search(r"[\-\u2013\u2014:]\s*$", before) or after in "-\u2013\u2014":
            continue  # part of a page/number range
        candidates.append(int(m.group(1)))
    return candidates[-1] if candidates else None


def _looks_like_name_list(segment: str) -> bool:
    """True for strings that are just author names, not a real title."""
    if ":" in segment:
        return False  # "Show, Attend and Tell: Neural …" is a title
    words = [w for w in re.split(r"[\s,]+", segment.strip(" .")) if w]
    if "," not in segment or not words:
        return False
    lower = {w.lower().strip(".,;:") for w in words}
    if lower & (_TITLE_FUNCTION_WORDS - {"and"}):
        return False
    namey = sum(bool(_NAME_TOKEN.fullmatch(w)) for w in words)
    return namey / len(words) >= 0.8


def _split_authors(segment: str) -> list[dict[str, str]]:
    segment = re.sub(r"\b(and|&)\b", ",", segment)
    names = []
    for part in re.split(r",\s*", segment):
        part = part.strip(" .")
        if not part or len(part) < 2 or not re.search(r"[A-Za-z]{2}", part):
            continue
        # Org / consortium authors ("AI@Meta", "DeepSeek-AI"): keep as a
        # CSL literal — imperfect data beats dropping the name.
        if "@" in part or re.search(r"[A-Za-z]-AI\b", part):
            names.append({"literal": part})
            if len(names) >= 25:
                break
            continue
        # "Family, G." style arrives already split; "G. Family" style has the
        # initials first. Particles ("van der Maaten") stay on the family.
        words = part.split()
        family_start = len(words) - 1
        for i, w in enumerate(words[:-1]):
            if i > 0 and w.lower() in _PARTICLES:
                family_start = i
                break
        else:
            caps = [w for w in words if w[:1].isupper() and len(w.strip(".")) > 1]
            family = caps[-1] if caps else words[-1]
            given = part.replace(family, "").strip(" ,.")
            names.append({"family": family.strip("."), "given": given})
            if len(names) >= 25:
                break
            continue
        names.append({
            "family": " ".join(words[family_start:]).strip("."),
            "given": " ".join(words[:family_start]).strip(" ,."),
        })
        if len(names) >= 25:
            break
    return names


def _looks_like_title(sentence: str) -> bool:
    sentence = sentence.strip().rstrip(".")
    if len(sentence) < 8 or len(sentence.split()) < 2:
        return False
    if re.search(r"\b[A-Z][^\w\s]{0,2}$", sentence):
        return False  # ends in an initial ("Quoc V.")
    if _looks_like_name_list(sentence):
        return False
    if re.match(r"^In\s+[A-Z]", sentence):
        return False  # venue line, "In CoNLL"
    return True


# "In ICML, 2014" / "In Proceedings of the 5th ICLR, pages 1-9".
_VENUE_RE = re.compile(
    r"\bIn\s+(?:Proceedings of\s+(?:the\s+)?)?"
    r"([A-Z][\w&()\-\s.]{2,80}?)"
    r"(?=,\s*(?:19|20)\d{2}|,\s*(?:pages?|pp)\b|,\s*vol\b|\.\s|\.$|$)")
# "Neurocomputing, 9:243-269" / "Neural computation, 9(8):1735-1780".
_JOURNAL_RE = re.compile(
    r"([A-Z][\w.\-&\s]{2,60}?),\s*(\d{1,4})\s*(?:\((\d[\d\-\u2013]*)\))?:(\d+(?:[\-\u2013]\s?\d+)?)")


def _extract_venue(rest: str, csl: dict) -> None:
    """Fill container-title (and volume/page for journals) from the text
    that follows the title. Best-effort; absence is fine."""
    if m := _JOURNAL_RE.search(rest):
        csl["container-title"] = m.group(1).strip()
        csl["volume"] = m.group(2)
        if m.group(3):
            csl["issue"] = m.group(3)
        csl["page"] = m.group(4).replace(" ", "")
        return
    if m := _VENUE_RE.search(rest):
        venue = m.group(1).strip().rstrip(",.")
        if 2 < len(venue) <= 80:
            csl["container-title"] = venue
            csl["type"] = "paper-conference"


def parse_entry(raw: str, ref_id: str) -> Reference:
    text = _repair_wrapped_ids(_MARKER.sub("", raw).strip())
    csl: dict = {"id": ref_id, "type": "article-journal"}

    if m := _DOI_RE.search(text):
        csl["DOI"] = m.group(1).rstrip(".")
    if m := _URL_RE.search(text):
        csl["URL"] = m.group(0).rstrip(".")
    arxiv_id = _extract_arxiv_id(text)
    if arxiv_id:
        csl["number"] = f"arXiv:{arxiv_id}"
        csl["type"] = "article"
        # Canonical abs page beats explicit URLs, which are often truncated
        # by line wrapping in the PDF.
        csl["URL"] = f"https://arxiv.org/abs/{arxiv_id}"

    year = _extract_year(text)
    if not year and arxiv_id:
        year = _year_from_arxiv(arxiv_id)
    if year:
        csl["issued"] = {"date-parts": [[year]]}

    title = ""
    paren_year = re.search(r"\((19|20)\d{2}[a-z]?\)\.?\s*", text)
    acl_year = _ACL_YEAR_RE.search(text)
    if m := _QUOTED_TITLE_RE.search(text) or _DOUBLED_QUOTE_RE.search(text):
        # IEEE-ish: Authors, "Title," venue, year.
        title = m.group(1).strip().rstrip(",.")
        author_seg = text[:m.start()]
    elif paren_year:
        # APA-ish: Authors (year). Title. Venue.
        author_seg = text[:paren_year.start()]
        rest = text[paren_year.end():]
        title = re.split(r"(?<=[.?!])\s+", rest)[0].strip().rstrip(".")
    elif acl_year and acl_year.start() < 280:
        # ACL/CS: Authors. 2018. Title. Venue.
        author_seg = text[:acl_year.start()]
        rest = text[acl_year.end():]
        title = re.split(r"(?<=[.?!])\s+", rest)[0].strip().rstrip(".")
    else:
        # Fallback: Authors. Title. Venue, year.  Don't split after initials
        # ("Quoc V. Le") — only after a lowercase letter or digit.
        parts = re.split(r"(?<=[a-z0-9)])\.\s+(?=[A-Z\u201c\"])", text)
        author_seg = parts[0] if parts else ""
        for part in parts[1:]:
            candidate = re.sub(r"^\(?(19|20)\d{2}[a-z]?\)?\.?\s*", "", part.strip())
            first_sentence = re.split(r"(?<=[a-z0-9)])\.\s+", candidate)[0]
            if _looks_like_title(first_sentence):
                title = first_sentence.rstrip(".")
                break
            author_seg += " " + part
    if title:
        # Venue leaked into the title ("A clockwork RNN. In ICML, 2014").
        if m := re.search(r"\.\s+In\s+[A-Z]", title):
            title = title[:m.start()].rstrip(".")
        title = re.sub(r",?\s*\(?(19|20)\d{2}[a-z]?\)?$", "", title).rstrip(",.")
        csl["title"] = title
        idx = text.find(title)
        rest = text[idx + len(title):] if idx >= 0 else text
        _extract_venue(rest, csl)

    authors = _split_authors(re.sub(r"\(?(19|20)\d{2}[a-z]?\)?", "", author_seg))
    if authors:
        csl["author"] = authors

    # Only identifier URLs belong in CSL (citeproc prints them). Search
    # fallbacks are derived in the UI so the bibliography stays clean.
    if doi := csl.get("DOI"):
        csl["URL"] = f"https://doi.org/{doi}"
    elif arxiv_id:
        csl["URL"] = f"https://arxiv.org/abs/{arxiv_id}"
    elif (url := csl.get("URL", "")).startswith("http") and re.search(r"/abs/\d{4}$", url):
        csl.pop("URL", None)

    if title and year:
        status = "parsed"
    elif title or year or "DOI" in csl or authors:
        status = "partial"
    else:
        status = "failed"
    return Reference(id=ref_id, raw=raw, csl=csl, parse_status=status)
