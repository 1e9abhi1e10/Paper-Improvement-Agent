"""Persistence: papers, findings and proposals as JSON on disk.

Deliberately simple (single-user assessment app): one JSON file per
paper under backend/data/, loaded into memory on first access.
"""
from __future__ import annotations

import json
from typing import Optional

from .config import DATA_DIR
from .models import EditProposal, Finding, Paper
from .search import aggregate

_papers: dict[str, Paper] = {}
_findings: dict[str, list[Finding]] = {}
_proposals: dict[str, list[EditProposal]] = {}


def _path(paper_id: str):
    return DATA_DIR / f"paper_{paper_id}.json"


def save(paper: Paper) -> None:
    _papers[paper.id] = paper
    payload: dict = {
        "paper": paper.model_dump(),
        "proposals": [p.model_dump() for p in _proposals.get(paper.id, [])],
    }
    if paper.id in _findings:
        payload["findings"] = [f.model_dump() for f in _findings[paper.id]]
    _path(paper.id).write_text(json.dumps(payload, indent=1))


def load(paper_id: str) -> Optional[Paper]:
    if paper_id in _papers:
        return _papers[paper_id]
    path = _path(paper_id)
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    paper = Paper.model_validate(payload["paper"])
    if "findings" in payload:
        _findings[paper_id] = [Finding.model_validate(f) for f in payload["findings"]]
    _proposals[paper_id] = [EditProposal.model_validate(p) for p in payload.get("proposals", [])]
    if aggregate.repair_references(paper.references):
        save(paper)
    _papers[paper_id] = paper
    return paper


def set_findings(paper_id: str, findings: list[Finding]) -> None:
    _findings[paper_id] = findings
    if paper := load(paper_id):
        save(paper)


def get_findings(paper_id: str) -> list[Finding] | None:
    """None if review has never been run; a (possibly empty) list otherwise."""
    load(paper_id)
    return _findings.get(paper_id)


def get_proposals(paper_id: str) -> list[EditProposal]:
    load(paper_id)
    return _proposals.get(paper_id, [])


def add_proposal(paper_id: str, proposal: EditProposal) -> None:
    paper = load(paper_id)
    _proposals.setdefault(paper_id, []).append(proposal)
    if paper:
        save(paper)
