"""Edit operations and the citation-integrity invariant.

All text edits go through ``check_integrity``: the multiset of citation
tokens after an edit must contain every token that existed before it.
Tokens may be *added* freely (new citations from real sources) but a
token can only disappear if it is listed in ``allowed_removals`` -- which
the UI surfaces to the user before approval. This is what guarantees
"existing citations survive; nothing is dropped silently".
"""
from __future__ import annotations

from collections import Counter

from ..models import EditProposal, Paper, Reference, SectionDiff
from ..parsing.intext import extract_tokens


class IntegrityError(Exception):
    """Carries the full multiset diff so failures can be shown precisely."""

    def __init__(self, message: str, violations: list[tuple[str, int, int]] | None = None):
        super().__init__(message)
        # (ref_id, occurrences before, occurrences after)
        self.violations = violations or []


def check_integrity(old_text: str, new_text: str,
                    allowed_removals: set[str] | None = None) -> list[str]:
    """Raises IntegrityError (listing every mismatched token) if citations
    were dropped without permission. Returns the ref ids that were
    permittedly removed."""
    allowed_removals = allowed_removals or set()
    old_counts = Counter(extract_tokens(old_text))
    new_counts = Counter(extract_tokens(new_text))
    removed: list[str] = []
    violations: list[tuple[str, int, int]] = []
    for ref_id, count in old_counts.items():
        after = new_counts.get(ref_id, 0)
        if after < count:
            if ref_id in allowed_removals:
                removed.extend([ref_id] * (count - after))
            else:
                violations.append((ref_id, count, after))
    if violations:
        detail = "; ".join(
            f"'{r}' appears {before}x before but {after}x after"
            for r, before, after in violations
        )
        raise IntegrityError(
            f"Edit would drop citation(s) without explicit approval: {detail}.",
            violations,
        )
    return removed


def apply_diffs(paper: Paper, diffs: list[SectionDiff],
                new_references: list[Reference],
                allowed_removals: set[str] | None = None) -> None:
    """Apply an approved proposal to the paper, re-checking integrity at
    apply time (the paper may have changed since the proposal was made)."""
    for diff in diffs:
        section = paper.section_by_id(diff.section_id)
        if section is None:
            raise IntegrityError(f"Section '{diff.section_id}' no longer exists.")
        check_integrity(section.text, diff.new_text, allowed_removals)

    existing_ids = {r.id for r in paper.references}
    for ref in new_references:
        if ref.id in existing_ids:
            continue
        if ref.provenance is None or ref.provenance.source == "pdf":
            raise IntegrityError(
                f"New reference '{ref.id}' has no API provenance; refusing to add "
                "a citation that is not grounded in a real source."
            )
        paper.references.append(ref)
        existing_ids.add(ref.id)

    known_ids = {r.id for r in paper.references}
    for diff in diffs:
        for token_ref in extract_tokens(diff.new_text):
            if token_ref not in known_ids:
                raise IntegrityError(
                    f"Edited text cites unknown reference '{token_ref}'.")

    for diff in diffs:
        section = paper.section_by_id(diff.section_id)
        assert section is not None
        section.text = diff.new_text


def undo_proposal(paper: Paper, proposal: EditProposal) -> None:
    """Revert an applied proposal. Only safe if the affected sections are
    still exactly as this proposal left them (no later edit on top).
    Citations the proposal *added* may be removed by the revert; everything
    that predated it is protected by the same integrity check as always."""
    for diff in proposal.diffs:
        section = paper.section_by_id(diff.section_id)
        if section is None or section.text != diff.new_text:
            raise IntegrityError(
                f"Cannot undo: section '{diff.section_id}' has been modified "
                "since this edit was applied. Undo edits newest-first."
            )
    # Only citations this proposal itself introduced may disappear in the
    # revert; everything pre-existing stays protected by the invariant.
    added_tokens = {r.id for r in proposal.new_references}
    for diff in proposal.diffs:
        check_integrity(diff.new_text, diff.old_text, allowed_removals=added_tokens)

    for diff in proposal.diffs:
        section = paper.section_by_id(diff.section_id)
        assert section is not None
        section.text = diff.old_text

    # Drop references this proposal introduced if nothing cites them anymore.
    proposal_refs = {r.id for r in proposal.new_references}
    still_cited = {t for s in paper.sections for t in extract_tokens(s.text)}
    paper.references = [r for r in paper.references
                        if r.id not in proposal_refs or r.id in still_cited]
