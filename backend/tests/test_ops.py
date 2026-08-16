import pytest

from app.agent.ops import IntegrityError, apply_diffs, check_integrity, undo_proposal
from app.models import EditProposal, Paper, Provenance, Reference, Section, SectionDiff


def paper():
    return Paper(
        id="p1", title="T",
        sections=[Section(id="sec1", title="Intro",
                          text="Claim one [[cite:ref1]]. Claim two [[cite:ref2]].")],
        references=[
            Reference(id="ref1", raw="r1", csl={"id": "ref1", "title": "One"}, parse_status="parsed"),
            Reference(id="ref2", raw="r2", csl={"id": "ref2", "title": "Two"}, parse_status="parsed"),
        ],
    )


def test_dropping_a_citation_raises():
    with pytest.raises(IntegrityError):
        check_integrity("a [[cite:ref1]] b [[cite:ref2]]", "a b [[cite:ref2]]")


def test_integrity_error_reports_every_violation_with_counts():
    with pytest.raises(IntegrityError) as exc_info:
        check_integrity(
            "[[cite:ref1]] x [[cite:ref1]] y [[cite:ref2]] z [[cite:ref3]]",
            "x [[cite:ref1]] z [[cite:ref3]]",
        )
    err = exc_info.value
    assert ("ref1", 2, 1) in err.violations
    assert ("ref2", 1, 0) in err.violations
    assert "ref1" in str(err) and "2x before but 1x after" in str(err)
    assert "ref2" in str(err)


def test_reordering_and_adding_is_fine():
    removed = check_integrity(
        "a [[cite:ref1]] b", "b [[cite:ref1]] a [[cite:ref3]]")
    assert removed == []


def test_explicitly_allowed_removal():
    removed = check_integrity("a [[cite:ref1]] b", "a b", allowed_removals={"ref1"})
    assert removed == ["ref1"]


def test_duplicate_tokens_counted():
    with pytest.raises(IntegrityError):
        check_integrity("[[cite:ref1]] x [[cite:ref1]]", "[[cite:ref1]] x")


def test_apply_diffs_happy_path():
    p = paper()
    new_ref = Reference(
        id="ref3", csl={"id": "ref3", "title": "Three"}, parse_status="parsed",
        provenance=Provenance(source="openalex", external_id="W1", url="https://openalex.org/W1"),
        added_by_edit=True,
    )
    diff = SectionDiff(
        section_id="sec1",
        old_text=p.sections[0].text,
        new_text=p.sections[0].text + " New claim [[cite:ref3]].",
    )
    apply_diffs(p, [diff], [new_ref])
    assert "ref3" in p.sections[0].text
    assert any(r.id == "ref3" for r in p.references)


def test_apply_rejects_unprovenanced_reference():
    p = paper()
    bogus = Reference(id="ref3", csl={"id": "ref3", "title": "Made up"}, parse_status="parsed")
    diff = SectionDiff(section_id="sec1", old_text=p.sections[0].text,
                       new_text=p.sections[0].text + " [[cite:ref3]].")
    with pytest.raises(IntegrityError, match="provenance"):
        apply_diffs(p, [diff], [bogus])


def test_apply_rejects_unknown_token():
    p = paper()
    diff = SectionDiff(section_id="sec1", old_text=p.sections[0].text,
                       new_text=p.sections[0].text + " [[cite:ref99]].")
    with pytest.raises(IntegrityError, match="unknown"):
        apply_diffs(p, [diff], [])


def _applied_proposal(p):
    new_ref = Reference(
        id="ref3", csl={"id": "ref3", "title": "Three"}, parse_status="parsed",
        provenance=Provenance(source="openalex", external_id="W1", url="https://openalex.org/W1"),
        added_by_edit=True,
    )
    diff = SectionDiff(
        section_id="sec1", old_text=p.sections[0].text,
        new_text=p.sections[0].text + " New claim [[cite:ref3]].",
    )
    apply_diffs(p, [diff], [new_ref])
    return EditProposal(id="prop1", command="add", diffs=[diff],
                        new_references=[new_ref], status="applied")


def test_undo_restores_text_and_removes_added_ref():
    p = paper()
    original = p.sections[0].text
    proposal = _applied_proposal(p)
    assert "ref3" in p.sections[0].text
    undo_proposal(p, proposal)
    assert p.sections[0].text == original
    assert all(r.id != "ref3" for r in p.references)


def test_undo_refuses_if_section_changed_since():
    p = paper()
    proposal = _applied_proposal(p)
    p.sections[0].text += " A later manual edit."
    with pytest.raises(IntegrityError, match="modified"):
        undo_proposal(p, proposal)
    # And nothing was reverted.
    assert "ref3" in p.sections[0].text


def test_undo_never_drops_preexisting_citations():
    p = paper()
    proposal = _applied_proposal(p)
    # Corrupt the recorded old_text so the revert would drop ref1.
    proposal.diffs[0].old_text = "Text without the original citations."
    with pytest.raises(IntegrityError, match="drop"):
        undo_proposal(p, proposal)


def test_apply_rejects_silent_drop():
    p = paper()
    diff = SectionDiff(section_id="sec1", old_text=p.sections[0].text,
                       new_text="Everything rewritten with no citations.")
    with pytest.raises(IntegrityError, match="drop"):
        apply_diffs(p, [diff], [])
