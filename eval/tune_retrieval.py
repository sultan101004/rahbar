#!/usr/bin/env python3
"""Measure retrieval alone, without generation, to tune three numbers with data:

1. chunk (size, overlap): recall@3/@5 on the golden set for each indexed collection;
2. RELEVANCE_FLOOR: the top-1 similarity of answerable vs must-abstain questions;
3. CACHE_THRESHOLD: similarity of paraphrase pairs (should hit) vs near-miss pairs that
   ask something different (must not hit).

It runs where the API's code and Chroma are reachable, e.g. inside the api image:

    docker run --rm --network <net> -v "$PWD:/repo" -e CHROMA_HOST=chroma \\
      -e OLLAMA_URL=http://host.docker.internal:11434 rahbar-api:<tag> \\
      python /repo/eval/tune_retrieval.py rahbar rahbar-c150 rahbar-c500

Output is printed and written to eval/tuning.json; docs/PIPELINE.md quotes it.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "api"))

from app.config import get_settings  # noqa: E402
from app.retrieval.chroma import ChromaRetriever  # noqa: E402
from app.services.cache import cosine  # noqa: E402

spec = importlib.util.spec_from_file_location("run_eval", HERE / "run_eval.py")
assert spec and spec.loader
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)

SAME = [  # paraphrases: a cache hit is correct
    ("What is the attendance requirement?", "What's the attendance requirement?"),
    ("How many semesters can I freeze?", "For how many semesters can a student freeze admission?"),
    ("What is the BS tuition fee per credit hour?", "How much is BS tuition per credit hour?"),
    ("What CGPA avoids academic warning?", "What CGPA do I need to avoid academic warning?"),
]
DIFFERENT = [  # near misses: a cache hit would serve the wrong answer
    ("What is the deadline to withdraw from a course?", "What is the deadline to drop a course?"),
    ("What CGPA avoids academic warning?", "What CGPA is required for graduation?"),
    ("What is the campus transfer fee?", "What is the degree correction fee?"),
    ("What is the minimum attendance for undergraduates?",
     "What is the minimum attendance for graduate students?"),
    ("What SGPA puts me on the Dean's List?", "What SGPA puts me on the Rector's List?"),
]


def evaluate(collection: str, questions: list[dict], ks: tuple[int, ...]) -> dict:
    settings = dataclasses.replace(get_settings(), collection=collection, retriever="chroma")
    retriever = ChromaRetriever(settings)
    info = retriever.index_info(fresh=True)
    out: dict = {"collection": collection, "chunks": info.count, "by_k": {}}
    top1: dict[str, list[tuple[float, str]]] = {"answerable": [], "abstain": []}
    for k in ks:
        rows = []
        for q in questions:
            passages = retriever.retrieve(q["question"], k)
            retrieved = [{"source": p.source, "section": p.section, "score": p.score}
                         for p in passages]
            rows.append({"id": q["id"], "type": q.get("type", "ordinary"),
                         "must_abstain": bool(q.get("must_abstain")),
                         "relevant": q.get("relevant") or [], "expect": None,
                         "response": {"retrieved": retrieved, "citations": [],
                                      "answered_from_context": False, "answer": ""}})
            if k == max(ks):
                best = max((p.score for p in passages if not p.lexical), default=0.0)
                lexical = any(p.lexical for p in passages)
                top1["abstain" if q.get("must_abstain") else "answerable"].append(
                    (round(best, 3), q["id"] + ("+lexical" if lexical else "")))
        s = run_eval.summarise(rows)
        out["by_k"][k] = {"recall@3": s["recall@3"], "recall@5": s["recall@5"],
                          "recall@5_by_type": s["recall@5_by_type"],
                          "misses@5": [p["id"] for p in s["per_question"]
                                       if p["recall@5"] is not None and p["recall@5"] < 1]}
    out["top1_similarity"] = {k: sorted(vals) for k, vals in top1.items()}
    return out


def cache_pairs(collection: str) -> dict:
    settings = dataclasses.replace(get_settings(), collection=collection, retriever="chroma")
    emb = ChromaRetriever(settings).embedder
    same = [round(cosine(emb.embed_query(a), emb.embed_query(b)), 4) for a, b in SAME]
    diff = [round(cosine(emb.embed_query(a), emb.embed_query(b)), 4) for a, b in DIFFERENT]
    table = {}
    for t in (0.90, 0.93, 0.95, 0.97):
        table[str(t)] = {"true_hits": sum(s >= t for s in same),
                         "false_hits": sum(d >= t for d in diff)}
    return {"paraphrase": same, "near_miss": diff, "thresholds": table,
            "pairs": {"paraphrase": SAME, "near_miss": DIFFERENT}}


def main() -> int:
    collections = sys.argv[1:] or ["rahbar"]
    golden = yaml.safe_load((HERE / "golden.yaml").read_text())["questions"]
    report = {"configs": [evaluate(c, golden, (1, 3, 5, 8)) for c in collections],
              "cache": cache_pairs(collections[0])}
    for cfg in report["configs"]:
        print(f"\n== {cfg['collection']} ({cfg['chunks']} chunks)")
        for k, v in cfg["by_k"].items():
            print(f"  top_k={k}: recall@3={v['recall@3']} recall@5={v['recall@5']} "
                  f"by_type={v['recall@5_by_type']} misses={v['misses@5']}")
        print(f"  top-1 similarity: {cfg['top1_similarity']}")
    print(f"\n== cache: {json.dumps(report['cache']['thresholds'])}")
    print(f"   paraphrase={report['cache']['paraphrase']} near_miss={report['cache']['near_miss']}")
    (HERE / "tuning.json").write_text(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
