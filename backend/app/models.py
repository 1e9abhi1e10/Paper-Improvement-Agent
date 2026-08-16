"""Core data models.

The canonical citation model is CSL-JSON (stored as plain dicts in
``Reference.csl``). Section text is stored *tokenized*: every in-text
citation marker found in the PDF is replaced by a token of the form
``[[cite:refId1,refId2]]``. All edits operate on tokenized text, which
lets us enforce citation integrity mechanically (compare token multisets
before/after an edit) and render/export via citeproc.
"""
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, model_validator

ParseStatus = Literal["parsed", "partial", "failed"]
ResolutionStatus = Literal["verified", "low-confidence", "unverified"]


class Provenance(BaseModel):
    """Where an external work came from. Only real, linkable sources."""
    source: Literal["openalex", "semanticscholar", "pdf"]
    external_id: str = ""
    url: str = ""
    abstract: str = ""


class Reference(BaseModel):
    id: str
    raw: str = ""                      # raw entry text as found in the PDF
    csl: dict[str, Any] = Field(default_factory=dict)  # CSL-JSON item
    parse_status: ParseStatus = "failed"
    provenance: Optional[Provenance] = None  # set when enriched/looked up
    added_by_edit: bool = False
    # Identifier hit or corroborated title match → verified. Title-only
    # similarity without year/author agreement → low-confidence. No API
    # match (or rate-limit) → unverified, never fabricated.
    resolution_status: ResolutionStatus = "unverified"
    resolution_note: str = ""

    @model_validator(mode="after")
    def _legacy_provenance_is_verified(self) -> "Reference":
        # Papers parsed before resolution_status existed treated a real
        # provenance record as verified. Don't demote them on reload.
        if (self.provenance is not None and self.resolution_status == "unverified"
                and not self.resolution_note):
            self.resolution_status = "verified"
        return self


class InTextCitation(BaseModel):
    id: str
    raw: str                            # marker as it appeared, e.g. "[3]" or "(Smith et al., 2020)"
    section_id: str
    ref_ids: list[str] = Field(default_factory=list)
    resolved: bool = False              # false => surfaced as unresolved, kept verbatim


class Section(BaseModel):
    id: str
    title: str
    level: int = 1
    text: str = ""                      # tokenized body text


class Diagnostic(BaseModel):
    stage: str
    severity: Literal["info", "warning", "error"] = "warning"
    message: str


class Paper(BaseModel):
    id: str
    filename: str = ""
    title: str = ""
    abstract: str = ""
    page_count: int = 0
    layout: str = ""                    # "Single column" / "Two-column" / "Mixed layout"
    year: str = ""                      # publication year if we can infer it
    sections: list[Section] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    intext: list[InTextCitation] = Field(default_factory=list)
    style: str = "ieee"                 # detected CSL style id; user-overridable
    style_detected: bool = False
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    def ref_by_id(self, ref_id: str) -> Optional[Reference]:
        return next((r for r in self.references if r.id == ref_id), None)

    def section_by_id(self, section_id: str) -> Optional[Section]:
        return next((s for s in self.sections if s.id == section_id), None)


class Finding(BaseModel):
    """A single reviewer-style finding, always grounded in a real source."""
    id: str
    kind: Literal["missing_citation", "citation_mismatch", "unverifiable",
                  "uncited_claim", "redundant_citation", "info"]
    section_id: str = ""
    claim: str = ""                     # the sentence/claim in the paper
    verdict: str = ""                   # e.g. supports / partial / does_not_support
    rationale: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"
    ref_id: str = ""                    # existing reference under review, if any
    candidate_csl: dict[str, Any] = Field(default_factory=dict)  # suggested work (CSL-JSON)
    candidate_provenance: Optional[Provenance] = None


class SectionDiff(BaseModel):
    section_id: str
    old_text: str
    new_text: str
    notes: list[str] = Field(default_factory=list)  # one line per change, why


class EditProposal(BaseModel):
    id: str
    command: str
    summary: str = ""
    diffs: list[SectionDiff] = Field(default_factory=list)
    new_references: list[Reference] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: Literal["pending", "applied", "rejected", "failed", "undone"] = "pending"
    created_at: str = ""
    applied_at: str = ""
