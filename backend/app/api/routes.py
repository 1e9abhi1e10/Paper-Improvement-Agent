from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .. import store
from ..agent import editor, llm, ops, qa, review
from ..citations import csl
from ..export import bibtex, latex
from ..models import Paper
from ..parsing import extract, pipeline

router = APIRouter(prefix="/api")


def _get_paper(paper_id: str) -> Paper:
    paper = store.load(paper_id)
    if paper is None:
        raise HTTPException(404, "Paper not found")
    return paper


def paper_payload(paper: Paper) -> dict:
    payload = paper.model_dump()
    if not payload.get("year"):
        payload["year"] = extract.infer_year(paper.filename, [])
    payload["rendered"] = {"bibliography": csl.bibliography_payload(paper)}
    findings = store.get_findings(paper.id)
    payload["findings"] = [f.model_dump() for f in findings] if findings is not None else None
    payload["proposals"] = [p.model_dump() for p in store.get_proposals(paper.id)]
    return payload


@router.post("/papers")
async def upload_paper(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF file.")
    data = await file.read()
    paper = pipeline.parse_pdf(data, filename=file.filename or "paper.pdf")
    store.save(paper)
    return paper_payload(paper)


@router.get("/papers/{paper_id}")
def get_paper(paper_id: str):
    return paper_payload(_get_paper(paper_id))


class StyleBody(BaseModel):
    style: str


@router.post("/papers/{paper_id}/style")
def set_style(paper_id: str, body: StyleBody):
    if body.style not in csl.AVAILABLE_STYLES:
        raise HTTPException(400, f"Unknown style. Available: {csl.AVAILABLE_STYLES}")
    paper = _get_paper(paper_id)
    paper.style = body.style
    paper.style_detected = False
    store.save(paper)
    return paper_payload(paper)


@router.post("/papers/{paper_id}/verify")
def retry_verify(paper_id: str):
    """Re-resolve unverified / low-confidence references in place.

    Verified entries, approved edits and history are left untouched.
    """
    from ..search import aggregate
    paper = _get_paper(paper_id)
    aggregate.retry_unverified(paper.references)
    store.save(paper)
    return paper_payload(paper)


@router.post("/papers/{paper_id}/review")
def run_review(paper_id: str):
    paper = _get_paper(paper_id)
    try:
        findings = review.run_review(paper)
    except llm.LLMUnavailable as exc:
        raise HTTPException(503, str(exc))
    store.set_findings(paper_id, findings)
    return {"findings": [f.model_dump() for f in findings]}


class EditBody(BaseModel):
    command: str


@router.post("/papers/{paper_id}/edit")
def propose(paper_id: str, body: EditBody):
    paper = _get_paper(paper_id)
    if not body.command.strip():
        raise HTTPException(400, "Empty command.")
    try:
        proposal = editor.propose_edit(paper, body.command.strip())
    except llm.LLMUnavailable as exc:
        raise HTTPException(503, str(exc))
    proposal.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    store.add_proposal(paper_id, proposal)
    return proposal.model_dump()


class DecisionBody(BaseModel):
    decision: str  # "approve" | "reject" | "undo"


@router.post("/papers/{paper_id}/proposals/{proposal_id}")
def decide(paper_id: str, proposal_id: str, body: DecisionBody):
    paper = _get_paper(paper_id)
    proposal = next((p for p in store.get_proposals(paper_id) if p.id == proposal_id), None)
    if proposal is None:
        raise HTTPException(404, "Proposal not found")

    if body.decision == "undo":
        if proposal.status != "applied":
            raise HTTPException(409, f"Only applied proposals can be undone (status: {proposal.status})")
        try:
            ops.undo_proposal(paper, proposal)
        except ops.IntegrityError as exc:
            raise HTTPException(409, str(exc))
        proposal.status = "undone"
        store.save(paper)
        return proposal.model_dump()

    if proposal.status != "pending":
        raise HTTPException(409, f"Proposal already {proposal.status}")
    if body.decision == "reject":
        proposal.status = "rejected"
    elif body.decision == "approve":
        try:
            ops.apply_diffs(paper, proposal.diffs, proposal.new_references)
        except ops.IntegrityError as exc:
            proposal.status = "failed"
            proposal.warnings.append(f"Apply blocked: {exc}")
            store.save(paper)
            raise HTTPException(409, f"Citation integrity check failed: {exc}")
        proposal.status = "applied"
        proposal.applied_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            proposal.warnings += review.post_edit_check(paper, proposal.diffs)
        except Exception as exc:
            # Self-check must never block an approved edit, but the
            # failure is surfaced so the author can see it.
            proposal.warnings.append(f"Post-edit citation check could not run: {exc}")
    else:
        raise HTTPException(400, "decision must be 'approve', 'reject' or 'undo'")
    store.save(paper)
    return proposal.model_dump()


class ChatBody(BaseModel):
    question: str
    history: list[dict] = []


@router.post("/papers/{paper_id}/chat")
def chat(paper_id: str, body: ChatBody):
    paper = _get_paper(paper_id)
    if not body.question.strip():
        raise HTTPException(400, "Empty question.")
    try:
        return qa.answer_question(paper, body.question.strip(), body.history)
    except llm.LLMUnavailable as exc:
        raise HTTPException(503, str(exc))


@router.get("/papers/{paper_id}/export", response_class=PlainTextResponse)
def export(paper_id: str, export_format: str = Query("latex", alias="format")):
    paper = _get_paper(paper_id)
    if export_format == "bib":
        return bibtex.export_bibtex(paper)
    if export_format == "latex":
        return latex.export_latex(paper)
    raise HTTPException(400, "format must be 'latex' or 'bib'")
