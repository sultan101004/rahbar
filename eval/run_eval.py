#!/usr/bin/env python3
"""Score a running RAHBAR against a golden set, and gate CI on the result (section 5).

    python eval/run_eval.py --api http://<ingress>                 # your corpus
    python eval/run_eval.py --api ... --golden eval/fixtures/golden.fixture.yaml
    python eval/run_eval.py --api ... --update-baseline            # after a deliberate improvement

Exit code 0 when every gate passes, 1 when any fails. CI relies on that exit code.

recall@k, citation validity, the summary and the gate are below; how sections are
matched is explained in docs/PIPELINE.md ("Evaluation method").
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent

# The gate from section 5.4. Change these only with a reason written in docs/PIPELINE.md.
MAX_RECALL5_DROP = 0.05        # recall@5 may fall at most 5 points below the baseline
MIN_CITATION_VALIDITY = 0.95   # at least 95% of citations must match retrieved passages
REQUIRED_ABSTENTION = 1.0      # every must-abstain question must be declined


def load_golden(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions = data.get("questions") or []
    if not questions:
        sys.exit(f"no questions in {path}")
    return questions


def ask(client: httpx.Client, api: str, question: str) -> dict:
    """POST one question and return the AskResponse as a dict (see api/app/schemas.py)."""
    response = client.post(f"{api.rstrip('/')}/api/ask", json={"question": question})
    response.raise_for_status()
    return response.json()


def _norm(text: object) -> str:
    return re.sub(r"[^a-z0-9.%]+", " ", str(text or "").lower()).strip()


def matches(relevant: dict, hit: dict) -> bool:
    """A retrieved passage satisfies a golden entry when its source is the golden source (or
    one of a list of sources carrying the same text) and the golden section is a substring of
    the section the chunker recorded. Substring, not equality: the chunker's labels can carry
    more than the heading (docs/PIPELINE.md, "Evaluation method")."""
    sources = relevant.get("source")
    sources = sources if isinstance(sources, list) else [sources]
    if _norm(hit.get("source")) not in {_norm(s) for s in sources}:
        return False
    want = _norm(relevant.get("section"))
    return bool(want) and want in _norm(hit.get("section"))


def recall_at_k(relevant: list[dict], retrieved: list[dict], k: int) -> float | None:
    """Fraction of the relevant (source, section) pairs found in the top k retrieved.
    Return None when the question has no relevant passages (must-abstain questions)."""
    if not relevant:
        return None
    top = retrieved[:k]
    found = sum(1 for rel in relevant if any(matches(rel, hit) for hit in top))
    return found / len(relevant)


def _valid(citation: dict, retrieved: list[dict]) -> bool:
    return any(_norm(citation.get("source")) == _norm(r.get("source"))
               and _norm(citation.get("section")) == _norm(r.get("section")) for r in retrieved)


def citation_validity(response: dict) -> float | None:
    """Fraction of the response's citations that match a passage in response['retrieved'].
    Return None when there are no citations."""
    citations = response.get("citations") or []
    if not citations:
        return None
    retrieved = response.get("retrieved") or []
    return sum(1 for c in citations if _valid(c, retrieved)) / len(citations)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarise(rows: list[dict]) -> dict:
    """Overall recall@3, recall@5, citation validity and abstention correctness, plus
    recall@5 broken down by question type. This dict becomes results.json."""
    per_question = []
    by_type: dict[str, list[float]] = {}
    r3: list[float] = []
    r5: list[float] = []
    cited = valid = 0
    abstain_total = abstain_ok = 0
    answerable = answered = expect_total = expect_hit = 0
    for row in rows:
        resp = row["response"]
        retrieved = resp.get("retrieved") or []
        rec3 = recall_at_k(row["relevant"], retrieved, 3)
        rec5 = recall_at_k(row["relevant"], retrieved, 5)
        if rec5 is not None and rec3 is not None:
            r3.append(rec3)
            r5.append(rec5)
            by_type.setdefault(row["type"], []).append(rec5)
        citations = resp.get("citations") or []
        cited += len(citations)
        valid += sum(1 for c in citations if _valid(c, retrieved))
        declined = not resp.get("answered_from_context")
        if row["must_abstain"]:
            abstain_total += 1
            abstain_ok += int(declined)
        else:
            answerable += 1
            answered += int(not declined)
            if row.get("expect"):
                expect_total += 1
                expect_hit += int(_norm(row["expect"]) in _norm(resp.get("answer")))
        per_question.append({
            "id": row["id"], "type": row["type"], "recall@3": rec3, "recall@5": rec5,
            "answered_from_context": not declined, "must_abstain": row["must_abstain"],
            "citations": len(citations), "citation_validity": citation_validity(resp),
            "expect_found": (_norm(row["expect"]) in _norm(resp.get("answer")))
            if row.get("expect") else None,
            "top_scores": [r.get("score") for r in retrieved[:5]],
            "seconds": row.get("seconds"),
        })
    seconds = sorted(r.get("seconds") or 0 for r in rows)
    return {
        "recall@3": _mean(r3),
        "recall@5": _mean(r5),
        "recall@5_by_type": {t: _mean(v) for t, v in sorted(by_type.items())},
        "citation_validity": round(valid / cited, 4) if cited else None,
        "citations_total": cited,
        "abstention_correctness": round(abstain_ok / abstain_total, 4) if abstain_total else None,
        "answer_rate_on_answerable": round(answered / answerable, 4) if answerable else None,
        "expect_hit_rate": round(expect_hit / expect_total, 4) if expect_total else None,
        "latency_p50_s": seconds[len(seconds) // 2] if seconds else None,
        "per_question": per_question,
    }


def gate(results: dict, baseline: dict | None) -> list[str]:
    """Return one message per failed gate (section 5.4); an empty list means pass."""
    failures: list[str] = []
    recall5 = results.get("recall@5")
    if baseline and baseline.get("recall@5") is not None and recall5 is not None:
        floor = baseline["recall@5"] - MAX_RECALL5_DROP
        if recall5 < floor - 1e-9:
            failures.append(f"recall@5 {recall5:.3f} is more than {MAX_RECALL5_DROP:.0%} "
                            f"below the baseline {baseline['recall@5']:.3f}")
    abstention = results.get("abstention_correctness")
    if abstention is not None and abstention < REQUIRED_ABSTENTION:
        wrong = [q["id"] for q in results.get("per_question", [])
                 if q["must_abstain"] and q["answered_from_context"]]
        failures.append(f"must-abstain questions answered from context: {wrong} "
                        f"(abstention correctness {abstention:.0%}, required 100%)")
    validity = results.get("citation_validity")
    if validity is not None and validity < MIN_CITATION_VALIDITY:
        failures.append(f"citation validity {validity:.1%} is below "
                        f"{MIN_CITATION_VALIDITY:.0%}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate RAHBAR against a golden set.")
    parser.add_argument("--api", required=True, help="base URL, e.g. http://192.168.49.2")
    parser.add_argument("--host", help="Host header, when your Ingress rule names a host")
    parser.add_argument("--golden", type=Path, default=HERE / "golden.yaml")
    parser.add_argument("--baseline", type=Path, default=HERE / "baseline.json")
    parser.add_argument("--out", type=Path, default=HERE / "results.json")
    parser.add_argument("--pace", type=float, default=0.0,
                        help="seconds to wait between questions (hosted free-tier rate limits)")
    parser.add_argument("--update-baseline", action="store_true",
                        help="write these results as the new baseline")
    args = parser.parse_args()

    questions = load_golden(args.golden)
    rows = []
    headers = {"Host": args.host} if args.host else {}
    with httpx.Client(timeout=120.0, headers=headers) as client:
        for q in questions:
            started = time.perf_counter()
            response = ask(client, args.api, q["question"])
            rows.append({
                "id": q["id"], "type": q.get("type", "ordinary"),
                "must_abstain": bool(q.get("must_abstain", False)),
                "relevant": q.get("relevant") or [],
                "expect": q.get("expect"),
                "response": response,
                "seconds": round(time.perf_counter() - started, 2),
            })
            print(f"  {q['id']:<5} {rows[-1]['seconds']:>6.2f}s  {q['question'][:60]}")
            if args.pace:
                time.sleep(args.pace)

    try:
        results = summarise(rows)
        baseline = json.loads(args.baseline.read_text()) if args.baseline.exists() else None
        failures = gate(results, baseline)
    except NotImplementedError as exc:
        print(f"\nnot implemented yet: {exc}")
        return 2

    results["golden"] = str(args.golden)
    results["questions"] = len(rows)
    for key in ("recall@3", "recall@5", "recall@5_by_type", "citation_validity",
                "abstention_correctness", "answer_rate_on_answerable", "expect_hit_rate"):
        print(f"  {key:<26} {results[key]}")
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nresults written to {args.out}")
    if args.update_baseline:
        args.baseline.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"baseline updated: {args.baseline}")

    if failures:
        print("\nGATE FAILED")
        for message in failures:
            print(f"  - {message}")
        return 1
    print("\ngate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
