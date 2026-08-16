"""Peer review, on request.

Two passes, both grounded in real API results:

1. Missing work: per section, the LLM extracts claims and search queries;
   we run them against Semantic Scholar + OpenAlex; the LLM then judges
   which candidates the paper should plausibly cite. It can only pick
   from the candidate list we hand it (by key), so a suggestion can never
   be a hallucinated reference.

2. Claim-citation match: for each in-text citation, we take the sentence
   it sits in, fetch the cited work's abstract via the APIs, and ask the
   LLM whether the abstract supports the claim. No abstract -> honestly
   reported as unverifiable, never guessed.
"""
from __future__ import annotations

import re
import uuid

from ..models import Finding, Paper
from ..parsing.intext import TOKEN_RE, split_sentences
from ..parsing.structure import normalize_heading
from ..search import aggregate
from . import llm

MAX_SECTIONS = 6
MAX_QUERIES_PER_SECTION = 2
MAX_CITATION_CHECKS = 15
_SKIP_SECTIONS = {
    "acknowledgments", "acknowledgements", "appendix", "appendices",
    "references", "bibliography", "works cited",
}


def _fid() -> str:
    return uuid.uuid4().hex[:10]


def _cited_keys(paper: Paper) -> set[str]:
    keys: set[str] = set()
    for ref in paper.references:
        keys |= aggregate.csl_keys(ref.csl)
    return keys


def _review_sections(paper: Paper):
    return [
        s for s in paper.sections
        if len(s.text) > 300 and normalize_heading(s.title) not in _SKIP_SECTIONS
    ][:MAX_SECTIONS]


def find_missing_work(paper: Paper) -> list[Finding]:
    findings: list[Finding] = []
    already_cited = _cited_keys(paper)
    sections = _review_sections(paper)

    for section in sections:
        plain = TOKEN_RE.sub("[CITATION]", section.text)[:4000]
        try:
            resp = llm.chat_json(
                system=(
                    "You extract literature-search queries from a research paper section. "
                    "Identify the section's key claims or topics that would normally be "
                    "supported by citations. Return JSON: "
                    '{"queries": [{"claim": "<claim sentence from text>", '
                    '"query": "<short academic search query>"}]}. '
                    f"At most {MAX_QUERIES_PER_SECTION} queries."
                ),
                user=f"Section '{section.title}' of paper '{paper.title}':\n\n{plain}",
            )
        except llm.LLMUnavailable as exc:
            findings.append(Finding(id=_fid(), kind="info", section_id=section.id,
                                    rationale=f"Search-query extraction failed: {exc}"))
            continue

        for query_item in (resp.get("queries") or [])[:MAX_QUERIES_PER_SECTION]:
            query = str(query_item.get("query", "")).strip()
            claim = str(query_item.get("claim", "")).strip()
            if not query:
                continue
            results = aggregate.search_all(
                query, limit=6, exclude_titles=[paper.title])
            candidates = [r for r in results
                          if not (aggregate.result_keys(r) & already_cited) and r.get("abstract")]
            if not candidates:
                findings.append(Finding(
                    id=_fid(), kind="info", section_id=section.id, claim=claim,
                    rationale=f"Searched both APIs for '{query}' but found no uncited "
                              "works with abstracts. (Honest empty result.)",
                    confidence="low",
                ))
                continue

            catalog = "\n".join(
                f"[{i}] {c['title']} ({c.get('year')}, {c.get('venue') or 'n/a'}, "
                f"{c.get('cited_by', 0)} citations)\nAbstract: {c['abstract'][:600]}"
                for i, c in enumerate(candidates[:6])
            )
            try:
                judged = llm.chat_json(
                    system=(
                        "You are a peer reviewer judging whether search results are works "
                        "the paper should plausibly cite for a claim. Be selective: only "
                        "pick results whose abstract is clearly relevant. Return JSON: "
                        '{"picks": [{"index": <int>, "rationale": "<why>", '
                        '"confidence": "high|medium|low"}]}. At most 2 picks; picks may be empty.'
                    ),
                    user=f"Paper: {paper.title}\nSection: {section.title}\n"
                         f"Claim: {claim}\n\nCandidates:\n{catalog}",
                )
            except llm.LLMUnavailable:
                continue
            for pick in (judged.get("picks") or [])[:2]:
                idx = pick.get("index")
                if not isinstance(idx, int) or not (0 <= idx < len(candidates[:6])):
                    continue  # model picked outside the candidate list: discard
                cand = candidates[idx]
                findings.append(Finding(
                    id=_fid(), kind="missing_citation", section_id=section.id,
                    claim=claim,
                    rationale=str(pick.get("rationale", ""))[:600],
                    confidence=pick.get("confidence", "medium")
                    if pick.get("confidence") in ("high", "medium", "low") else "medium",
                    candidate_csl=aggregate.result_to_csl(cand, f"cand-{_fid()}"),
                    candidate_provenance=aggregate.result_provenance(cand),
                ))
    return findings


def _sentence_with_token(text: str, ref_id: str) -> str:
    for sentence in split_sentences(text):
        if re.search(rf"\[\[cite:[^\]]*\b{re.escape(ref_id)}\b[^\]]*\]\]", sentence):
            return TOKEN_RE.sub("[CITATION]", sentence).strip()
    return ""


def check_citations(paper: Paper) -> list[Finding]:
    findings: list[Finding] = []
    checked = 0
    for cit in paper.intext:
        if checked >= MAX_CITATION_CHECKS:
            findings.append(Finding(
                id=_fid(), kind="info",
                rationale=f"Citation check capped at {MAX_CITATION_CHECKS} citations "
                          "for this run; re-run review to continue.",
            ))
            break
        if not cit.resolved or not cit.ref_ids:
            continue
        section = paper.section_by_id(cit.section_id)
        if section is None:
            continue
        for ref_id in cit.ref_ids[:2]:
            ref = paper.ref_by_id(ref_id)
            if ref is None:
                continue
            claim = _sentence_with_token(section.text, ref_id)
            if not claim or len(claim) < 40:
                continue
            checked += 1

            if ref.provenance is None or not ref.provenance.abstract:
                result = aggregate.resolve_reference(ref)
                if result:
                    ref.provenance = aggregate.result_provenance(result)
            abstract = ref.provenance.abstract if ref.provenance else ""
            title = ref.csl.get("title", ref.raw[:100])

            if not abstract:
                findings.append(Finding(
                    id=_fid(), kind="unverifiable", section_id=section.id,
                    claim=claim, ref_id=ref_id, confidence="low",
                    rationale=f"Could not fetch an abstract for '{title}' from "
                              "Semantic Scholar or OpenAlex, so this claim-citation "
                              "pair cannot be verified.",
                ))
                continue

            try:
                verdict = llm.chat_json(
                    system=(
                        "You check whether a cited work's abstract actually supports a "
                        "claim in a paper. Judge only from the abstract. Return JSON: "
                        '{"verdict": "supports|partially_supports|does_not_support|cannot_tell", '
                        '"rationale": "<1-2 sentences>", "confidence": "high|medium|low"}'
                    ),
                    user=f"Claim (citation marked [CITATION]):\n{claim}\n\n"
                         f"Cited work: {title}\nAbstract:\n{abstract[:1500]}",
                )
            except llm.LLMUnavailable as exc:
                findings.append(Finding(id=_fid(), kind="info", ref_id=ref_id,
                                        rationale=f"Verdict call failed: {exc}"))
                continue
            v = verdict.get("verdict", "cannot_tell")
            kind = "citation_mismatch" if v == "does_not_support" else (
                "unverifiable" if v == "cannot_tell" else "info")
            findings.append(Finding(
                id=_fid(), kind=kind, section_id=section.id, claim=claim,
                ref_id=ref_id, verdict=v,
                rationale=str(verdict.get("rationale", ""))[:600],
                confidence=verdict.get("confidence", "medium")
                if verdict.get("confidence") in ("high", "medium", "low") else "medium",
            ))
    return findings


def find_uncited_claims(paper: Paper) -> list[Finding]:
    """Flag sentences that read like claims needing support but carry no
    citation. The LLM proposes candidates; we only keep ones we can verify
    verbatim in the text and that genuinely contain no citation token."""
    findings: list[Finding] = []
    sections = _review_sections(paper)
    for section in sections:
        plain = TOKEN_RE.sub("[CITATION]", section.text)[:4000]
        try:
            resp = llm.chat_json(
                system=(
                    "You are a peer reviewer. From the section text, list sentences "
                    "that assert prior work, empirical facts, or comparisons and would "
                    "normally require a citation, but have no [CITATION] marker. "
                    "Copy each sentence VERBATIM from the text. Skip the paper's own "
                    "contributions and definitions. Return JSON: "
                    '{"claims": [{"sentence": "<verbatim>", "why": "<short reason>", '
                    '"confidence": "high|medium|low"}]}. At most 3; may be empty.'
                ),
                user=f"Section '{section.title}':\n\n{plain}",
            )
        except llm.LLMUnavailable:
            continue
        plain_norm = " ".join(plain.split())
        for claim in (resp.get("claims") or [])[:3]:
            sentence = str(claim.get("sentence", "")).strip()
            norm = " ".join(sentence.split())
            # Verify: really in the text, and really uncited.
            if len(norm) < 40 or norm not in plain_norm or "[CITATION]" in norm:
                continue
            findings.append(Finding(
                id=_fid(), kind="uncited_claim", section_id=section.id,
                claim=sentence,
                rationale=str(claim.get("why", ""))[:400],
                confidence=claim.get("confidence", "medium")
                if claim.get("confidence") in ("high", "medium", "low") else "medium",
            ))
    return findings


def structural_checks(paper: Paper) -> list[Finding]:
    """Deterministic reviewer checks, no LLM involved."""
    findings: list[Finding] = []

    # Citation bundles: one marker citing 4+ works often pads rather than
    # supports; worth a look. Capped to the largest few bundles.
    bundles = sorted((c for c in paper.intext if c.resolved and len(c.ref_ids) >= 4),
                     key=lambda c: -len(c.ref_ids))[:4]
    for cit in bundles:
        section = paper.section_by_id(cit.section_id)
        claim = _sentence_with_token(section.text, cit.ref_ids[0]) if section else ""
        titles = [(paper.ref_by_id(r).csl.get("title") or r)
                  for r in cit.ref_ids if paper.ref_by_id(r)]
        findings.append(Finding(
            id=_fid(), kind="redundant_citation", section_id=cit.section_id,
            claim=claim, confidence="medium",
            rationale=f"{len(cit.ref_ids)} works are cited together for one "
                      f"claim ({'; '.join(t[:50] for t in titles[:4])}…). Check "
                      "whether each one is individually needed here.",
        ))

    # Citation diversity: heavy reliance on a single first author.
    by_family: dict[str, list[str]] = {}
    for ref in paper.references:
        authors = ref.csl.get("author") or []
        if authors and authors[0].get("family"):
            by_family.setdefault(authors[0]["family"].lower(), []).append(ref.id)
    total = max(len(paper.references), 1)
    for family, ref_ids in by_family.items():
        if len(ref_ids) >= 4 and len(ref_ids) / total >= 0.10:
            findings.append(Finding(
                id=_fid(), kind="info", confidence="low",
                rationale=f"Citation diversity: {len(ref_ids)} of {total} references "
                          f"share the first author '{family.title()}' "
                          f"({', '.join(ref_ids[:6])}). If these are self-citations "
                          "or one lab's work, reviewers may flag it.",
            ))
    return findings[:12]


def new_uncited_sentences(old_text: str, new_text: str) -> list[str]:
    """Sentences present in the new text but not the old, carrying no
    citation token -- the candidates for a post-edit citation check."""
    def norm(s: str) -> str:
        return " ".join(s.split()).lower()
    old_sentences = {norm(s) for s in split_sentences(old_text)}
    out = []
    for sentence in split_sentences(new_text):
        if (norm(sentence) not in old_sentences
                and not TOKEN_RE.search(sentence)
                and len(sentence.strip()) >= 40):
            out.append(sentence.strip())
    return out


def post_edit_check(paper: Paper, diffs) -> list[str]:
    """Self-review after an edit is applied: editing can create the very
    problem review detects (a claim without support), so re-run the
    uncited-claim judgment on sentences the edit introduced or reworded."""
    warnings: list[str] = []
    for diff in diffs:
        candidates = new_uncited_sentences(diff.old_text, diff.new_text)[:6]
        if not candidates:
            continue
        numbered = "\n".join(f"[{i}] {s[:300]}" for i, s in enumerate(candidates))
        try:
            resp = llm.chat_json(
                system=(
                    "These sentences were just added or reworded by an edit to a "
                    "research paper and carry no citation. Flag ONLY those that "
                    "assert prior work, empirical facts, or comparisons that would "
                    "normally require a citation. Rewordings of the author's own "
                    "contributions need nothing. Return JSON: "
                    '{"flags": [{"index": <int>, "why": "<short reason>"}]}. '
                    "May be empty."
                ),
                user=numbered,
            )
        except llm.LLMUnavailable:
            continue
        section = paper.section_by_id(diff.section_id)
        title = section.title if section else diff.section_id
        for flag in (resp.get("flags") or [])[:3]:
            idx = flag.get("index")
            if isinstance(idx, int) and 0 <= idx < len(candidates):
                warnings.append(
                    f"Post-edit check ({title}): the edited sentence "
                    f"\u201c{candidates[idx][:160]}\u201d may need a citation "
                    f"\u2014 {str(flag.get('why', ''))[:200]}"
                )
    return warnings


def run_review(paper: Paper) -> list[Finding]:
    return (find_missing_work(paper) + find_uncited_claims(paper)
            + structural_checks(paper) + check_citations(paper))
