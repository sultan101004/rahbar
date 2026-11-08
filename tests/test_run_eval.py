"""Unit tests for the evaluation metrics and the CI gate (eval/run_eval.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_eval", ROOT / "eval" / "run_eval.py")
assert spec and spec.loader
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)

RETRIEVED = [
    {"chunk_id": "a", "source": "rules.pdf", "section": "Attendance Requirements", "score": 0.8},
    {"chunk_id": "b", "source": "rules.pdf", "section": "Academic Warning/Probation", "score": 0.7},
    {"chunk_id": "c", "source": "fees.html", "section": "Miscellaneous Fees", "score": 0.6},
    {"chunk_id": "d", "source": "x.pdf", "section": "Other", "score": 0.5},
]


def test_recall_matches_section_substring_and_source_lists() -> None:
    rel = [{"source": ["other.pdf", "fees.html"], "section": "miscellaneous fees"}]
    assert run_eval.recall_at_k(rel, RETRIEVED, 3) == 1.0
    assert run_eval.recall_at_k(rel, RETRIEVED, 2) == 0.0
    assert run_eval.recall_at_k([], RETRIEVED, 5) is None


def test_recall_is_a_fraction_of_relevant_passages() -> None:
    rel = [{"source": "rules.pdf", "section": "Attendance"}, {"source": "rules.pdf", "section": "Nope"}]
    assert run_eval.recall_at_k(rel, RETRIEVED, 5) == 0.5


def test_citation_validity_counts_only_retrieved_passages() -> None:
    response = {"retrieved": RETRIEVED, "citations": [
        {"source": "rules.pdf", "section": "Attendance Requirements"},
        {"source": "hostel.pdf", "section": "Fees"}]}
    assert run_eval.citation_validity(response) == 0.5
    assert run_eval.citation_validity({"citations": []}) is None


def _row(qid: str, qtype: str, abstain: bool, answered: bool, relevant: list[dict]) -> dict:
    cites = [{"source": "rules.pdf", "section": "Attendance Requirements"}] if answered else []
    return {"id": qid, "type": qtype, "must_abstain": abstain, "relevant": relevant,
            "expect": "100%" if not abstain else None, "seconds": 1.0,
            "response": {"answer": "100% attendance", "answered_from_context": answered,
                         "citations": cites, "retrieved": RETRIEVED}}


def test_summarise_and_gate_pass_on_a_good_run() -> None:
    rel = [{"source": "rules.pdf", "section": "Attendance"}]
    rows = [_row("q1", "ordinary", False, True, rel), _row("q2", "abstain", True, False, [])]
    results = run_eval.summarise(rows)
    assert results["recall@5"] == 1.0 and results["recall@5_by_type"] == {"ordinary": 1.0}
    assert results["abstention_correctness"] == 1.0 and results["citation_validity"] == 1.0
    assert run_eval.gate(results, {"recall@5": 1.0}) == []


def test_gate_fails_on_recall_drop_abstention_and_citations() -> None:
    rows = [_row("q1", "ordinary", False, True, [{"source": "rules.pdf", "section": "Nope"}]),
            _row("q2", "abstain", True, True, [])]
    rows[0]["response"]["citations"].append({"source": "made-up.pdf", "section": "x"})
    results = run_eval.summarise(rows)
    failures = run_eval.gate(results, {"recall@5": 0.9})
    assert len(failures) == 3
    assert any("q2" in f for f in failures)


def test_gate_allows_a_drop_within_five_points() -> None:
    assert run_eval.gate({"recall@5": 0.86, "per_question": []}, {"recall@5": 0.9}) == []
