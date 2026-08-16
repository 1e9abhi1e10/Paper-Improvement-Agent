from app.export.latex import export_latex
from app.models import Paper, Provenance, Reference, Section


def paper() -> Paper:
    return Paper(
        id="p",
        title="Test Paper",
        style="ieee",
        abstract="We cite prior work [[cite:ref1]].",
        sections=[
            Section(id="sec1", title="1 Introduction", level=1,
                    text="Hello [[cite:ref1]] world."),
            Section(id="sec2", title="2.1 Setup", level=2,
                    text="Details follow."),
        ],
        references=[
            Reference(id="ref1", raw="r1", parse_status="parsed", csl={
                "id": "ref1", "type": "article-journal",
                "title": "Attention is all you need",
                "author": [{"family": "Vaswani", "given": "Ashish"}],
                "issued": {"date-parts": [[2017]]},
            }),
            Reference(id="ref2", raw="Totally unparseable {entry}", parse_status="failed"),
            Reference(id="ref3", parse_status="parsed", added_by_edit=True,
                      csl={"id": "ref3", "title": "New work", "type": "article"},
                      provenance=Provenance(source="openalex", external_id="W9",
                                            url="https://openalex.org/W9")),
        ],
    )


def test_latex_keeps_citation_tokens_and_failed_refs():
    tex = export_latex(paper())
    assert r"\cite{ref1}" in tex
    assert r"\section{Introduction}" in tex
    assert r"\subsection{Setup}" in tex
    assert r"\bibitem{ref1}" in tex
    assert r"\bibitem{ref2}" in tex
    assert "could not be parsed" in tex
    assert "Totally unparseable" in tex
    assert "added by edit" in tex
    assert "openalex" in tex
