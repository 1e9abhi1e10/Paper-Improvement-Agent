"""Step 6: detect the paper's citation style from the marker mix.

Numeric-dominant papers map to IEEE, author-year-dominant to APA. This
is a CSL *style id* used for rendering and export; the user can override
it in the UI.
"""
from __future__ import annotations

from ..models import InTextCitation


def detect_style(citations: list[InTextCitation]) -> tuple[str, bool]:
    numeric = sum(1 for c in citations if c.raw.startswith("["))
    author_year = len(citations) - numeric
    if numeric == 0 and author_year == 0:
        return "ieee", False
    return ("ieee", True) if numeric >= author_year else ("apa", True)


def style_consistency(citations: list[InTextCitation]) -> str | None:
    """Lint for mixed citation styles: a small minority of markers in the
    other style usually means inconsistent formatting worth fixing."""
    numeric = [c for c in citations if c.raw.startswith("[")]
    author_year = [c for c in citations if not c.raw.startswith("[")]
    if len(citations) < 5 or not numeric or not author_year:
        return None
    minority, min_name, maj_name = (
        (author_year, "author-year", "numeric")
        if len(numeric) >= len(author_year)
        else (numeric, "numeric", "author-year")
    )
    if len(minority) / len(citations) > 0.2:
        return None  # genuinely mixed usage, not a stray inconsistency
    examples = ", ".join(c.raw[:40] for c in minority[:3])
    return (f"Mixed citation styles: {len(citations) - len(minority)} {maj_name} "
            f"marker(s) but {len(minority)} stray {min_name} marker(s) "
            f"(e.g. {examples}). Consider normalizing them.")
