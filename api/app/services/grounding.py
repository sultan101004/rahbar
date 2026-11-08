"""Grounding and honesty (section 3.4): the relevance floor, abstention, the citation
check, and the canned fallback. Pure functions, unit-tested in tests/test_grounding.py."""

from __future__ import annotations

import re

from ..schemas import Answer, Citation, Passage

ABSTAIN_TEXT = ("I could not find this in the FAST-NUCES documents I have indexed, so I "
                "cannot answer it reliably. Please check with the Academic Office.")
UNVERIFIED_TEXT = ("I found related passages, but I could not produce an answer whose sources "
                   "I can verify, so I will not guess. Please check with the Academic Office.")
FALLBACK_TEXT = ("Sorry, I could not produce a verified answer right now. Please try again "
                 "in a moment.")


def above_floor(passages: list[Passage], floor: float) -> list[Passage]:
    """Evidence = passages at or above the cosine floor, plus exact-term (lexical) hits,
    which contain the literal clause or code the user asked about."""
    return [p for p in passages if p.score >= floor or p.lexical]


def abstention(reasoning: str, text: str = ABSTAIN_TEXT) -> Answer:
    return Answer(reasoning=reasoning, answer=text, citations=[],
                  answered_from_context=False, confidence="low")


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9.]+", " ", (s or "").lower()).strip()


def match_citation(c: Citation, passages: list[Passage]) -> Passage | None:
    """The retrieved passage a citation refers to, or None if it was never retrieved.
    Source must match exactly (case-insensitive); section must match exactly or one must
    contain the other (models sometimes shorten '1. Attendance' to 'Attendance')."""
    for p in passages:
        if _norm(c.source) != _norm(p.source):
            continue
        cs, ps = _norm(c.section), _norm(p.section)
        if cs and (cs == ps or cs in ps or ps in cs):
            return p
    return None


def enforce_citations(answer: Answer, passages: list[Passage]) -> tuple[Answer, int]:
    """Keep only citations that match a passage retrieved for THIS request, rewritten to
    that passage's exact source/section/page. Returns (answer, citations dropped).

    - answered_from_context=false  -> citations are cleared;
    - answered_from_context=true but nothing valid is left -> the claim cannot be
      verified, so the answer is withdrawn rather than served uncited."""
    if not answer.answered_from_context:
        return answer.model_copy(update={"citations": []}), len(answer.citations)
    valid: list[Citation] = []
    seen: set[tuple[str, str]] = set()
    for c in answer.citations:
        p = match_citation(c, passages)
        if p and (p.source, p.section) not in seen:
            seen.add((p.source, p.section))
            valid.append(Citation(source=p.source, section=p.section, page=p.page))
    dropped = len(answer.citations) - len(valid)
    if not valid:
        return abstention("no citation matched a retrieved passage", UNVERIFIED_TEXT), dropped
    return answer.model_copy(update={"citations": valid}), dropped


def fallback() -> Answer:
    return abstention("fallback: the model call failed or returned invalid output twice",
                      FALLBACK_TEXT)
