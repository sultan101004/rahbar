# Failure analysis

Each stage was broken on purpose, one at a time, then restored. Numbers come from
`eval/tune_retrieval.py` (retrieval only, golden set) and the eval runs; `eval/tuning.json` has
the raw output. The diagnosis column says how we would have found it *without* knowing.
Following the RAG lecture: only F is the model's fault, so check A to E first.

## Stage A · Extraction
- **What we broke:** indexed the scanned 2023 rules without OCR. With Tesseract absent from the
  image, `_ocr_page` logs `ocr failed ... TesseractNotFoundError` and returns '' for each of the 23
  image-only pages.
- **Symptom:** the 2023 document contributes only its cover. "What did the older 2023 rules say
  was the deadline to withdraw from a course?" (q13) retrieves nothing from the 2023 file.
  recall@5 for q13 drops from 1.0 to 0, and the model either declines or answers with the 2026
  rule, which is wrong for that question. Nothing errors: the Job still exits 0.
- **Diagnosis, as if we had not caused it:** the indexer's per-document log line
  `{"msg": "chunked", "source": "undergraduate-academic-rules-aug-2023.pdf", "chunks": 1,
  "ocr_pages": 0}` for a 26-page PDF. Chunks per page far below the other documents (the 2026
  handbook gives 64 chunks for 58 pages) is the tell. `pdffonts` on the file confirms there is no
  text layer.
- **Remedy:** OCR fallback in `extract.py` (pages under 40 characters, rendered at 200 dpi), with
  `tesseract-ocr` and `poppler-utils` in the indexer Dockerfile. With OCR: `"ocr_pages": 23`, 52
  chunks, q13 recall@5 = 1.0.

## Stage B · Chunking
- **What we broke:** `CHUNK_STRATEGY=fixed CHUNK_SIZE=100 CHUNK_OVERLAP=0`: fixed 100-word windows
  over the whole document, blind to headings.
- **Symptom:** 300 chunks with section labels like `words 1200-1300`. Measured with
  `eval/tune_retrieval.py` (collection `rahbar-fixed100`):
  - The must-abstain hostel-and-transport question q18 now has top-1 similarity **0.703**,
    above the 0.70 floor, so the system would answer it. With structure-aware chunks it is 0.690
    and declines. Without headings, a window that happens to mix "transport facility" with fee
    text scores higher.
  - Citations become meaningless (`[file / words 1200-1300]`), and section-based recall falls to
    0.0 for every question type. That number partly reflects the metric, since fixed windows
    have no section to match.
  - Reading the windows shows clauses cut mid-sentence: the "20%" of clause 1.21 sits in a
    different window from "attendance".
- **Diagnosis, as if we had not caused it:** recall@5 by question type falls in the CI gate
  (more than 5 points below baseline, so the build fails). The per-request log line shows the
  retrieved `chunk_ids` and `scores`. Reading the retrieved chunks for a missed question shows a
  clause cut mid-sentence, with the half that holds the number in a neighbouring chunk.
- **Remedy:** structure-aware chunking (sections, then paragraphs, then sentences), heading
  prepended, 300/40 (ADR 0002).

## Stage C · Retrieval
- **What we broke:** `TOP_K: "1"` in the ConfigMap, and separately the relevance floor at our
  first guess, 0.55.
- **Symptom (top_k=1):** recall@5 falls from 1.00 to 0.76. Version-sensitive questions fall to
  0.33 (q12 and q13 miss), and q04 and q09 miss. The model sees one passage and answers from the
  wrong current document, or declines.
- **Symptom (floor 0.55):** the CI e2e gate failed on the fixture corpus with
  `must-abstain questions answered from context: ['f05'] (abstention correctness 0%, required
  100%)`. "How do I apply for a hostel room?" scored 0.559 against a fees table and was answered.
- **Diagnosis, as if we had not caused it:** the per-request log line shows `"top_k": 1` and a
  single chunk id. For the floor case, `"scores": [0.5594, ...]` and `"evidence": 1` on a
  must-abstain question, plus `rahbar_abstentions_total{reason="below_floor"}` staying flat while
  questions about absent topics arrive.
- **Remedy:** `TOP_K=5`, where recall@5 reaches 1.0 and 8 adds nothing. `RELEVANCE_FLOOR=0.70`,
  measured as the lowest floor that abstains on every must-abstain question while keeping every
  answerable one (PIPELINE.md).

## Stage E · Source
- **What we broke:** removed the `superseded` filter (`where` set to `None` for every question in
  `api/app/retrieval/chroma.py`).
- **Symptom:** "What is the deadline to withdraw from a course?" (q11) retrieves the OCR'd 2023
  clause 4.25 ("the last day of classes") alongside the 2026 clause 4.25 ("the last day of the
  makeup week of every semester"). Both are on-topic with high similarity, so the floor cannot
  help. The 2023 chunk can rank first, and the model then confidently quotes a repealed deadline
  with a valid-looking citation. Citation validity stays at 100%, because the citation *was*
  retrieved. Only `expect` ("makeup week") catches it.
- **Diagnosis, as if we had not caused it:** the response's `retrieved` list contains
  `source: undergraduate-academic-rules-aug-2023.pdf` for a question that did not ask about 2023,
  and the cited source is the superseded file. Our metadata makes this visible in one glance at
  the log line. A prompt cannot fix it, because the model cannot know the 2023 file was
  repealed unless retrieval tells it.
- **Remedy:** metadata filter `superseded: false` by default, lifted only by explicit wording
  ("older", "2023 rules", "previous"). q13 shows the lifted case working. The evidence block also
  marks any superseded passage as an older version.

## Not broken here: D (prompt) and F (generation)
We kept to four stages. Our injection tests cover part of D: a poisoned chunk is fenced as data,
and a "gullible model" that obeys it cannot cite its way out (`api/tests/test_rag.py`). For F,
temperature 1.2 would mostly show up as JSON validation failures and fallbacks
(`rahbar_fallbacks_total`), because the schema constrains the output.
