from app.export.bibtex import export_bibtex
from app.models import Paper, Provenance, Reference


def paper():
    return Paper(id="p", title="Test Paper", references=[
        Reference(id="ref1", raw="r1", parse_status="parsed", csl={
            "id": "ref1", "type": "article-journal",
            "title": "Attention is all you need",
            "author": [{"family": "Vaswani", "given": "Ashish"},
                       {"family": "Shazeer", "given": "Noam"}],
            "issued": {"date-parts": [[2017]]},
            "container-title": "NeurIPS", "DOI": "10.5555/329",
        }),
        Reference(id="ref2", raw="r2", parse_status="parsed", csl={
            "id": "ref2", "type": "paper-conference",
            "title": "BERT", "container-title": "NAACL",
            "issued": {"date-parts": [[2019]]},
            "number": "arXiv:1810.04805",
        }),
        Reference(id="ref3", raw="Totally unparseable {entry}", parse_status="failed"),
        Reference(id="ref4", parse_status="parsed", added_by_edit=True,
                  csl={"id": "ref4", "title": "New work", "type": "article"},
                  provenance=Provenance(source="openalex", external_id="W9",
                                        url="https://openalex.org/W9")),
    ])


def test_bibtex_types_and_fields():
    bib = export_bibtex(paper())
    assert "@article{ref1," in bib
    assert "author = {Vaswani, Ashish and Shazeer, Noam}" in bib
    assert "journal = {NeurIPS}" in bib
    assert "doi = {10.5555/329}" in bib
    assert "@inproceedings{ref2," in bib
    assert "booktitle = {NAACL}" in bib
    assert "eprint = {1810.04805}" in bib


def test_bibtex_failed_ref_kept_as_misc_note():
    bib = export_bibtex(paper())
    assert "@misc{ref3," in bib
    assert "Unparsed reference" in bib
    assert "Totally unparseable \\{entry\\}" in bib


def test_bibtex_added_by_edit_notes_provenance():
    bib = export_bibtex(paper())
    assert "@misc{ref4," in bib
    assert "openalex https://openalex.org/W9" in bib
