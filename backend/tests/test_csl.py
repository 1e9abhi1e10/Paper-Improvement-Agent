from app.citations import csl
from app.models import Paper, Reference, Section


def refs():
    return [
        Reference(id="ref1", raw="raw1", parse_status="parsed", csl={
            "id": "ref1", "type": "paper-conference",
            "title": "Attention is all you need",
            "author": [{"family": "Vaswani", "given": "Ashish"}],
            "issued": {"date-parts": [[2017]]},
            "container-title": "NeurIPS",
        }),
        Reference(id="ref2", raw="raw2", parse_status="parsed", csl={
            "id": "ref2", "type": "article-journal",
            "title": "BERT: Pre-training of deep bidirectional transformers",
            "author": [{"family": "Devlin", "given": "Jacob"}],
            "issued": {"date-parts": [[2019]]},
            "container-title": "NAACL",
        }),
        Reference(id="ref3", raw="Totally ~ unparseable ~ entry", parse_status="failed"),
    ]


def test_ieee_rendering_has_entries_and_inline_labels():
    out = csl.render(refs(), "ieee")
    assert "Vaswani" in out["ref1"]["entry"]
    assert "2017" in out["ref1"]["entry"]
    assert "Devlin" in out["ref2"]["entry"]
    # IEEE labels are list position, including unparsed entries.
    assert out["ref1"]["inline"] == "[1]"
    assert out["ref2"]["inline"] == "[2]"
    assert out["ref3"]["inline"] == "[3]"
    # Failed reference falls back to raw text, never dropped.
    assert out["ref3"]["entry"] == "Totally ~ unparseable ~ entry"


def test_apa_rendering_differs_from_ieee():
    ieee = csl.render(refs(), "ieee")
    apa = csl.render(refs(), "apa")
    assert ieee["ref1"]["entry"] != apa["ref1"]["entry"]
    assert "Vaswani" in apa["ref1"]["entry"]


def test_entry_mapping_correct_when_style_sorts_alphabetically():
    # APA sorts by author; ref2 (Devlin) sorts before ref1 (Vaswani).
    # The mapping must still attach each entry to the right reference.
    out = csl.render(refs(), "apa")
    assert "Vaswani" in out["ref1"]["entry"] and "Devlin" not in out["ref1"]["entry"]
    assert "Devlin" in out["ref2"]["entry"] and "Vaswani" not in out["ref2"]["entry"]


def test_bibliography_payload_covers_every_reference():
    paper = Paper(
        id="p", title="T", style="ieee",
        sections=[Section(id="sec1", title="Intro",
                          text="Known result [[cite:ref1]] and more [[cite:ref1,ref2]].")],
        references=refs(),
    )
    payload = csl.bibliography_payload(paper)
    assert [b["ref_id"] for b in payload] == ["ref1", "ref2", "ref3"]
    assert [b["inline"] for b in payload] == ["[1]", "[2]", "[3]"]
    # Failed reference is surfaced with its raw text and status, never dropped.
    assert payload[2]["parse_status"] == "failed"
    assert payload[2]["entry"] == "Totally ~ unparseable ~ entry"
