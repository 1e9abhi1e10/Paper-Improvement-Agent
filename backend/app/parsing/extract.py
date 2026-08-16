"""Step 1 of the pipeline: PDF -> layout-aware lines.

Uses PyMuPDF to extract each visual line with its dominant font size,
boldness and position. Downstream steps use font size and x-position
(hanging indents, columns) rather than ad-hoc text matching.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

import pymupdf


@dataclass
class Line:
    text: str
    size: float
    bold: bool
    x0: float
    y0: float
    page: int
    page_width: float


# The full sidebar banner ("arXiv:1706.03762v7 [cs.CL] 2 Aug 2023"), NOT a
# bare id: reference entries legitimately wrap onto lines that start with
# "arXiv:1607.06450, 2016." and those must be kept.
_ARXIV_BANNER = re.compile(r"^arXiv:\d{4}\.\d{4,5}(v\d+)?\s+\[[\w.\-]+\]\s+\d{1,2}\s+\w{3,9}\s+\d{4}")
_PAGE_NUMBER = re.compile(r"^\d{1,3}$")

# Older LaTeX fonts emit accents as separate spacing characters, so
# "Gülçehre" extracts as "G¨ulc¸ehre" and "Koutník" as "Koutn´ık".
# Map spacing accents to combining marks and re-compose.
_ACCENT_BEFORE = {
    "\u00a8": "\u0308",  # ¨ diaeresis
    "\u00b4": "\u0301",  # ´ acute
    "\u0060": "\u0300",  # ` grave
    "\u02c6": "\u0302",  # ˆ circumflex
    "\u02dc": "\u0303",  # ˜ tilde
    "\u02c7": "\u030c",  # ˇ caron
    "\u02da": "\u030a",  # ˚ ring
    "\u00af": "\u0304",  # ¯ macron
    "\u02dd": "\u030b",  # ˝ double acute
}
_ACCENT_RE = re.compile("([" + "".join(_ACCENT_BEFORE) + r"])\s?([A-Za-z\u0131])")
_CEDILLA_RE = re.compile(r"([cCsSgG])\s?\u00b8")


def fix_diacritics(text: str) -> str:
    def combine(m: re.Match) -> str:
        base = m.group(2).replace("\u0131", "i")  # dotless ı composes as i
        return unicodedata.normalize("NFC", base + _ACCENT_BEFORE[m.group(1)])

    text = _ACCENT_RE.sub(combine, text)
    text = _CEDILLA_RE.sub(
        lambda m: unicodedata.normalize("NFC", m.group(1) + "\u0327"), text)
    # "Ç ." left behind by the cedilla merge -> "Ç." (an author initial).
    text = re.sub(r"(?<![\w.])([A-Z\u00c0-\u00de])\s\.", r"\1.", text)
    return text


def extract_lines(pdf_bytes: bytes) -> list[Line]:
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    lines: list[Line] = []
    page_heights: dict[int, float] = {}
    for pno, page in enumerate(doc):
        data = page.get_text("dict")
        for block in data["blocks"]:
            if block.get("type") != 0:
                continue
            for raw_line in block["lines"]:
                # Skip vertical text (e.g. the rotated arXiv sidebar banner).
                if abs(raw_line.get("dir", (1, 0))[1]) > 0.5:
                    continue
                spans = [s for s in raw_line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = "".join(s["text"] for s in raw_line["spans"]).strip()
                text = fix_diacritics(text)
                if not text or _ARXIV_BANNER.match(text):
                    continue
                # Page numbers: numeric-only lines at the very bottom of the
                # page. (Numeric lines elsewhere may be detached heading
                # numbers and must be kept.)
                if _PAGE_NUMBER.match(text) and raw_line["bbox"][1] > page.rect.height * 0.92:
                    continue
                main = max(spans, key=lambda s: len(s["text"]))
                lines.append(Line(
                    text=text,
                    size=round(main["size"], 1),
                    bold=("bold" in main["font"].lower()) or bool(main["flags"] & 16),
                    x0=raw_line["bbox"][0],
                    y0=raw_line["bbox"][1],
                    page=pno,
                    page_width=page.rect.width,
                ))
        page_heights[pno] = page.rect.height
    doc.close()
    return _drop_page_furniture(lines, page_heights)


def _drop_page_furniture(lines: list[Line], page_heights: dict[int, float]) -> list[Line]:
    """Remove running headers/footers: identical text repeated near the top
    or bottom edge of 3+ pages (e.g. "Under review as a conference paper at
    ICLR 2017"), which otherwise pollutes sections and reference entries."""
    band_pages: dict[str, set[int]] = {}
    def in_band(line: Line) -> bool:
        height = page_heights.get(line.page, 792.0)
        return line.y0 < height * 0.08 or line.y0 > height * 0.92
    for line in lines:
        if in_band(line):
            band_pages.setdefault(line.text, set()).add(line.page)
    furniture = {t for t, pages in band_pages.items() if len(pages) >= 3}
    return [l for l in lines if not (l.text in furniture and in_band(l))]


def page_count(lines: list[Line]) -> int:
    return max((line.page for line in lines), default=-1) + 1


def detect_layout(lines: list[Line]) -> str:
    """Single column, two-column, or mixed — from x-position clusters."""
    by_page: dict[int, list[Line]] = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)

    two = one = 0
    for page_lines in by_page.values():
        if len(page_lines) < 10:
            continue
        if _page_is_two_column(page_lines):
            two += 1
        else:
            one += 1
    if two >= 2 and one >= 2:
        return "Mixed layout"
    if two > one:
        return "Two-column"
    return "Single column"


def _page_is_two_column(page_lines: list[Line]) -> bool:
    width = page_lines[0].page_width or 612.0
    threshold = width * 0.40
    left = [line for line in page_lines if line.x0 < threshold]
    right = [line for line in page_lines if line.x0 >= threshold]
    if len(left) < 8 or len(right) < 8:
        return False
    right_xs = sorted(line.x0 for line in right)
    return right_xs[len(right_xs) // 2] > width * 0.38


# arXiv ids are YYMM.NNNNN — 1503.08895 → 2015. Older 7-digit ids ignored.
_ARXIV_FILE = re.compile(r"(?:^|[^\d])(\d{2})\d{2}\.\d{4,5}")
_VENUE_YEAR = re.compile(
    r"(?:©|copyright|\b(?:ICLR|NeurIPS|NIPS|ICML|ACL|EMNLP|NAACL|EACL|"
    r"COLING|CVPR|ICCV|ECCV|AAAI|IJCAI|KDD|WWW|CHI)\b)\s+((?:19|20)\d{2})",
    re.I,
)


def infer_year(filename: str, lines: list[Line]) -> str:
    match = _ARXIV_FILE.search(filename)
    if match:
        yy = int(match.group(1))
        return str(2000 + yy if yy < 90 else 1900 + yy)
    page1 = " ".join(line.text for line in lines if line.page == 0)
    match = _VENUE_YEAR.search(page1)
    return match.group(1) if match else ""


def body_font_size(lines: list[Line]) -> float:
    """Most common font size weighted by text length = the body text size."""
    counter: Counter[float] = Counter()
    for line in lines:
        counter[line.size] += len(line.text)
    return counter.most_common(1)[0][0] if counter else 10.0


# arXiv / CoRR identifiers frequently wrap after the dot: "abs/1611.\n06194".
_SPLIT_ID = re.compile(r"(?:arxiv:|abs/|arxiv\.org/abs/)\d{4}\.$", re.I)


def join_hyphenated(parts: list[str]) -> str:
    """Join wrapped lines, repairing end-of-line hyphenation and split ids."""
    out = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if out.endswith("-") and part[:1].islower():
            # Compound words wrapped at an existing hyphen keep it
            # ("state-of-the-\nart"); plain wraps drop it ("trans-\nformers").
            last_word = out.rstrip("-").rsplit(" ", 1)[-1]
            out = (out + part) if "-" in last_word else (out[:-1] + part)
        elif _SPLIT_ID.search(out) and re.match(r"\d{4,5}\b", part):
            out += part
        elif out:
            out += " " + part
        else:
            out = part
    return out
