# AI usage

We used AI heavily and say so specifically. Everything listed was read, run and checked by us;
we can explain every line in a viva.

| Tool | What it wrote or shaped | What we changed afterwards, and why |
| --- | --- | --- |
| Claude Code (Claude Opus 5.5), in the Claude desktop app | First drafts of the indexer stages (`extract`, `clean`, `chunk`, `embed`, `store`), the API's retriever, providers, grounding, cache and readiness modules, the unit tests, `eval/run_eval.py` metrics and `eval/tune_retrieval.py`, the Dockerfiles, all Kubernetes manifests, both workflows and first drafts of these docs | We ran every stage on the real corpus and fixed what the output showed. The 2-up PDF page bug (ENGINEERING-NOTES Q7), the Prospectus column gutter, false-positive tables, and a header-removal rule that would have deleted clause lines were all found by reading extraction output. |
| Claude Code | Proposed starting values: relevance floor 0.55, cache threshold 0.95 | Both replaced by measurement. The 0.55 floor let the hostel question through and failed the CI gate; we measured 0.70. The cache threshold became 0.93, the lowest with zero false hits (PIPELINE.md). |
| Claude Code | Dependency pins | Trivy found HIGH CVEs in Starlette 0.46 (via FastAPI 0.115) and Debian packages. We moved to FastAPI 0.160.0 + Starlette 1.8.0 and `python:3.12.15-slim-trixie` with an OS upgrade, and bumped pydantic to 2.12.3 so the stack also installs on the Python 3.14 we develop on. |
| Claude Code | The golden set (`eval/golden.yaml`) | Questions and expected answers were checked against the PDFs by hand before any tuning. The version-sensitive questions came from comparing the OCR'd 2023 rules with the 2026 handbook. |

What AI did **not** decide: the corpus choice and the deliberately absent topic (hostels and
transport), the measured thresholds, and which failure stages to break.

Nothing AI-generated is presented as unaided work. Commits made with the tool carry a
`Co-Authored-By` trailer.
