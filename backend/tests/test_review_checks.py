"""Tests for the deterministic (LLM-free) review checks."""
from app.agent.review import new_uncited_sentences, structural_checks
from app.models import InTextCitation, Paper, Reference, Section
from app.parsing.style import style_consistency


def make_ref(i, family="Smith"):
    return Reference(id=f"ref{i}", parse_status="parsed", csl={
        "id": f"ref{i}", "title": f"Work {i}",
        "author": [{"family": family, "given": "A"}],
        "issued": {"date-parts": [[2020]]},
    })


def test_citation_bundle_flagged():
    paper = Paper(
        id="p", title="T",
        sections=[Section(id="sec1", title="Intro",
                          text="Many prior works exist in this crowded field today "
                               "[[cite:ref1,ref2,ref3,ref4]].")],
        references=[make_ref(i, family=f"Fam{i}") for i in range(1, 5)],
        intext=[InTextCitation(id="c1", raw="[1-4]", section_id="sec1",
                               ref_ids=["ref1", "ref2", "ref3", "ref4"], resolved=True)],
    )
    findings = structural_checks(paper)
    bundles = [f for f in findings if f.kind == "redundant_citation"]
    assert len(bundles) == 1
    assert "4 works are cited together" in bundles[0].rationale


def test_small_bundles_not_flagged():
    paper = Paper(
        id="p", title="T",
        sections=[Section(id="sec1", title="Intro", text="Known [[cite:ref1,ref2]].")],
        references=[make_ref(1, "A"), make_ref(2, "B")],
        intext=[InTextCitation(id="c1", raw="[1,2]", section_id="sec1",
                               ref_ids=["ref1", "ref2"], resolved=True)],
    )
    assert [f for f in structural_checks(paper) if f.kind == "redundant_citation"] == []


def test_author_concentration_flagged():
    refs = [make_ref(i, family="Repeated") for i in range(1, 6)]
    refs += [make_ref(i, family=f"Other{i}") for i in range(6, 12)]
    paper = Paper(id="p", title="T", references=refs)
    findings = structural_checks(paper)
    diversity = [f for f in findings if "Citation diversity" in f.rationale]
    assert len(diversity) == 1
    assert "5 of 11" in diversity[0].rationale
    assert "Repeated" in diversity[0].rationale


def test_diverse_authors_not_flagged():
    refs = [make_ref(i, family=f"Fam{i}") for i in range(1, 12)]
    paper = Paper(id="p", title="T", references=refs)
    assert [f for f in structural_checks(paper) if "diversity" in f.rationale] == []


def _cit(i, raw):
    return InTextCitation(id=f"c{i}", raw=raw, section_id="sec1",
                          ref_ids=[f"ref{i}"], resolved=True)


def test_style_consistency_flags_stray_minority():
    cits = [_cit(i, f"[{i}]") for i in range(1, 10)] + [_cit(10, "(Smith, 2020)")]
    msg = style_consistency(cits)
    assert msg is not None
    assert "9 numeric" in msg and "1 stray author-year" in msg
    assert "(Smith, 2020)" in msg


def test_style_consistency_silent_when_pure_or_genuinely_mixed():
    pure = [_cit(i, f"[{i}]") for i in range(1, 8)]
    assert style_consistency(pure) is None
    mixed = [_cit(i, f"[{i}]") for i in range(1, 5)] + \
            [_cit(i, f"(Author{i}, 2020)") for i in range(5, 9)]
    assert style_consistency(mixed) is None


def test_new_uncited_sentences_detects_additions_only():
    old = "The old claim stands here with support [[cite:ref1]]. Another old sentence remains."
    new = ("The old claim stands here with support [[cite:ref1]]. "
           "Another old sentence remains. "
           "A brand new empirical assertion appears without any support at all. "
           "New but cited claim right here, properly supported [[cite:ref2]].")
    result = new_uncited_sentences(old, new)
    assert result == ["A brand new empirical assertion appears without any support at all."]
