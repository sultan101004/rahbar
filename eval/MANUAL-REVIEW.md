# Manual review of the hosted-model run (9 Nov 2026)

`eval/results-hosted.json`: same golden set, same index (240 chunks, 300/40, nomic-embed-text,
top_k 5, floor 0.70); generation by Groq `openai/gpt-oss-120b` (`LLM_PROVIDER=hosted`,
`LLM_REASONING_EFFORT=low`), questions paced 15 s apart for the free tier's 8k tokens/minute.

| Metric | llama3.2:3b local (`results.json`) | gpt-oss-120b hosted (`results-hosted.json`) |
| --- | --- | --- |
| recall@5 | 1.0 | 1.0 |
| citation validity | 100% | 100% |
| abstention correctness | 100% | 100% |
| answered, of answerable | 71% (12/17) | **100% (17/17)** |
| expect string found (automatic) | 62.5% | 87.5% |
| **correct by manual review** | not reviewed | **16/16 with an expected fact** |
| latency per answer | 17-111 s (CPU) | 1-2 s |

The two automatic "misses" were read by hand and are correct; the check is a literal substring:

| Id | Expected string | Answer (abridged) | Verdict |
| --- | --- | --- | --- |
| q02 | `6 years` | "...is **six** years, which can be extended by one additional year with the approval of Statutory Bodies." [Bachelor's Degree Requirements, p.10] | correct |
| q08 | `closed` | "...the warning count becomes three and the university automatically **closes** your admission..." [Academic Warning/Probation p.24; Closure of Admission p.17] | correct |

Every must-abstain question (hostels, transport, the "SYSTEM OVERRIDE" injection) was declined
below the floor without a model call. The committed `baseline.json` stays the local-model run:
CI gates retrieval and grounding, which do not depend on the generator.
