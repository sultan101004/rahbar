# Indexing and retrieval pipeline

Indexing runs once, and again when the material changes (the `indexer` Job, the weekly `reindex`
CronJob, or `kubectl create job --from=cronjob/reindex ...`). Querying runs on every question
(the `api` Deployment). They share one ConfigMap and never share a process.

## How the corpus reaches the Job

The PDFs are not committed and not baked into the image (the image is public on Docker Hub). On the
cluster they live on the `rahbar-corpus` PVC: `make corpus-load` starts a short-lived busybox pod
(`k8s/tools/corpus-loader.yaml`) and streams `corpus/raw/` into the volume with `tar | kubectl exec`.
The Job mounts the PVC read-only at `/corpus`; its `wait-for-corpus` init container keeps it from
failing (and burning `backoffLimit`) if it is applied before the corpus is loaded. In CI the three
fixture documents arrive as a ConfigMap instead (`k8s/overlays/ci`).

## Extraction (`indexer/pipeline/extract.py`)

- **PDF:** pdfplumber, page by page. A page with fewer than 40 printable characters is treated as
  image-only, rendered at 200 dpi with pdf2image and OCR'd with Tesseract (`ocr=True` on the page).
- **Which documents needed OCR:** `undergraduate-academic-rules-aug-2023.pdf`, **23 of 26 pages**.
  Also the covers and back pages of both 2026 handbooks (2 pages each; images with a few words).
  OCR of the 23 pages takes about 75 s of the Job's ~3 minutes.
- **Two extraction bugs we found and fixed by reading the output, not by guessing:**
  1. The 2026 handbook is a 2-up imposition: every page also carries its neighbour's text at
     negative x, outside the visible page box. `extract_text()` interleaved the two pages line by
     line. Fix: `page.within_bbox(page.bbox)` before anything else.
  2. The Prospectus is three columns. Without a fix, lines from neighbouring columns interleave
     ("1. Attendance Requirement 4. Semester Course Load ..."). Fix: `column_splits()` finds vertical
     gutters (bands almost no character crosses) and extracts each column separately.
- **Tables:** pdfplumber's `find_tables()` returned false positives (a frame around the whole
  Prospectus page; a one-row footer). `_real_tables()` keeps only tables with ≥ 2 rows and ≥ 2
  columns, under 60% of the page area, with average cell length ≤ 80 characters. Real tables are cut
  out of the body text and re-emitted as pipe rows.

**Before / after: the letter-grade table, Academic Rules Handbook 2026 p. 11**

Before (plain `pdftotext`, cells on separate lines, columns lost):
```
Grade
Interpretation
A+
Outstanding
A, A-
Excellent
C-, D+, D
Pass, the student may repeat the course
```
After (`extract.py`):
```
| Grade | Interpretation |
| A+ | Outstanding |
| A, A- | Excellent |
| C-, D+, D | Pass, the student may repeat the course |
```

- **HTML:** a small `HTMLParser`: `<h1-6>` become `#` lines, `<tr>` become pipe rows, and
  `script/style/nav/header/footer/form` are skipped. Everything before the first heading is menu.
- **What we could not recover:**
  - The Prospectus is still imperfect. Section 1 ("Attendance Requirement") lands under the
    document-title section because its heading line carries column bleed. Several of its
    headings merge with neighbouring wrapped lines.
  - OCR misreads a few words ("Astudent", "Academic Homesty", "Warming" in the 2023 table of
    contents).
  - The 2023 OCR loses table structure entirely. Tesseract returns words, not cells.

## Cleaning (`indexer/pipeline/clean.py`)

Rules:
1. A line whose text, ignoring numbers at either end, repeats on ≥ 40% of a document's pages is a
   running header or footer and is removed ("NATIONAL UNIVERSITY OF COMPUTER AND EMERGING SCIENCES",
   "Undergraduate Academic Rules and Regulations 2026 5"). Only the *ends* are ignored: an earlier
   version ignored every digit and would have deleted clause lines such as "1.3 Rule number 3."
   that differ only by number. A unit test pins this.
2. Bare page numbers ("12", "iv", "Page 3 of 9") are removed.
3. Ligatures (ﬁ, ﬂ), curly quotes, and letter-spaced words ("c o u r s e") are normalised.
4. Words hyphenated across a line break are re-joined.
5. Runs of blank lines collapse to one. Blank lines are paragraph boundaries for the chunker.

**Deliberately not stripped:** clause numbers on their own line ("1.21"), list markers ("a)",
"1)") and table pipes. They look like noise, but an exact-term question ("what does clause 1.21
say?") has to match them. The chunker also uses them as paragraph boundaries.

## Chunking (`indexer/pipeline/chunk.py`)

Structure-aware with overlap: **sections, then paragraphs, then sentences**, and only for a
single sentence longer than the target, word windows. Section headings are detected as Markdown
`#` lines, numbered headings ("2. Grading and GPA Calculations", "XII. Policy on ...") and Title-Case
sub-headings ("Attendance Requirements"). A line that continues an unfinished sentence is never a
heading: in the multi-column Prospectus, wrapped lines are Title Case by accident. Overlap (in
words) is carried only between neighbouring chunks *of the same section*. The section heading is
prepended to every chunk's text, because it is what makes "attendance" retrievable from a chunk
whose body only says "1.21 Students are required to maintain 100% ...".

Unit: whitespace words (≈ 1.3 nomic tokens per word). Shipped: **CHUNK_SIZE=300, CHUNK_OVERLAP=40**.

Measured on the golden set (`eval/tune_retrieval.py`, retrieval only, top_k=5, same floor and
embedding model; raw numbers in `eval/tuning.json`):

| Strategy | Size (words) | Overlap (words) | Chunks stored | Amplification | recall@3 (k=5) | recall@5 (k=5) | recall@5 at top_k=1 (ordinary / version) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| structure | 150 | 20 | 338 | 1.101 | 0.941 | 1.000 | 0.765 (0.80 / 0.33) |
| **structure (shipped)** | **300** | **40** | **240** | **1.045** | **0.941** | **1.000** | **0.765 (0.80 / 0.33)** |
| structure | 500 | 60 | 213 | 1.009 | 0.941 | 1.000 | 0.765 (0.70 / 0.67) |
| fixed (Stage B baseline) | 100 | 0 | 300 | 1.0 | 0.000\* | 0.000\* | 0.000\* |

\* Fixed windows carry no section label (`words 1200-1300`), so our section-based metric cannot
match them: 0 here partly reflects the metric, not only retrieval. Its measurable harm shows up
elsewhere (FAILURE-ANALYSIS.md, Stage B).

**Storage amplification** = stored words / original words. For the shipped config it is
31,006 / 29,681 = **1.045**: the 40-word overlap only applies inside long sections, and most
sections fit in one chunk. The prepended headings add a little; header and footer removal takes
some away. For comparison, the lecture's example was 150 / 120 = 1.25.

**Why 300/40:** The three structure-aware settings tie at recall@5 = 1.0 at the shipped `top_k=5`; our 17
answerable golden questions are not hard enough to separate them there, and we say so rather
than claim a winner. At `top_k=1`, 500/60 loses an ordinary question (q05, the Generative AI
definition, diluted inside a 500-word chunk), while 150/20 needs 41% more chunks (338 vs 240) for
the same recall, which means more vectors, a slower index and more context per answer. 300/40 is
the smallest index at the best measured recall. The overlap (40 words, about two sentences) only
matters for the few sections longer than 300 words, such as the Generative AI policy and
Academic Dishonesty.

## Embedding (`indexer/pipeline/embed.py`, `api/app/retrieval/embedder.py`)

- Model **`nomic-embed-text`** through Ollama, **768 dimensions**, batched 32 texts per request.
- The pin lives in exactly one place: `EMBED_MODEL` in `k8s/base/configmap.yaml`, read by both the
  indexer and the api via `envFrom`.
- nomic is trained with task prefixes. The indexer embeds `search_document: <text>` and the API
  embeds `search_query: <question>`.
- The indexer writes `embed_model`, `dimension` and a fresh `index_id` into the collection
  metadata. The API compares `embed_model` with its own `EMBED_MODEL` at startup and on every
  `/readyz`, and refuses readiness on a mismatch (`api/app/services/readiness.py`). The retriever
  also refuses a query vector whose dimension differs from the index's.

## Store (`indexer/pipeline/store.py`)

Every chunk is written as id, text, vector and metadata. Chunk count for the shipped config:
**240**.

Metadata schema (every chunk):

| Field | Type | Example |
| --- | --- | --- |
| `source` | str | `academic-rules-handbook-jun-2026.pdf` |
| `section` | str | `Attendance Requirements` |
| `page` | int | `10` |
| `doc_version` | str | `2026-06` |
| `superseded` | bool | `false` |

Collection metadata: `hnsw:space=cosine`, `embed_model`, `dimension`, `index_id`, `chunk_size`,
`chunk_overlap`, `chunks`.

**Build-then-swap:** the Job writes to `rahbar-staging`, verifies the count, then deletes `rahbar`
and renames staging into place. A Job that dies halfway leaves the live index untouched (ADR 0001).

## Retrieval (`api/app/retrieval/chroma.py`)

- Embed the question with the pinned model.
- Query the top `TOP_K=5`, filtered by `where={"superseded": false}`. The filter is lifted only
  when the question explicitly asks about an older version ("older 2023 rules", "previous").
- Similarity = 1 − cosine distance.
- **Hybrid for exact terms:** if the question contains a clause number (`\d.\d`) or a course code,
  a second query adds `where_document={"$contains": term}`. Those hits go first and are marked
  `lexical`. Embeddings blur exact terms ("1.21" and "1.22" embed almost identically); a substring
  match does not.

## Relevance floor (abstention)

The floor is tuned on top-1 similarity, ignoring lexical hits (`eval/tuning.json`):

- must-abstain questions: **0.646, 0.648, 0.656, 0.690**
- answerable questions without a lexical hit: lowest is **0.720** (q09); most are 0.75–0.89

| Floor tried | Must-abstain that pass the floor | Answerable wrongly declined |
| --- | --- | --- |
| 0.55 (first guess) | 4 of 4 (all of them) | 0 |
| 0.65 | 3 (q18 0.690, q19 0.656, q21 0.648 > 0.65) | 0 |
| **0.70 (shipped)** | **0** | **0** |
| 0.75 | 0 | 1 (q09 at 0.720) |

The 0.55 guess failed in practice, not only on paper. On the fixture corpus the CI gate failed
with abstention correctness 0%: "How do I apply for a hostel room?" scored 0.559 and was
answered. nomic similarities run high, so 0.55 is not a floor at all.

## Semantic cache

Redis (ADR 0003). The cache key is `rahbar:cache:<index_id>`, so a re-index makes old answers
unreachable at once, and the first pod to see a new `index_id` deletes the stale keys.

Thresholds tried, on 4 paraphrase pairs (should hit) and 5 near-miss pairs (must not):

| Threshold | Paraphrases that hit (of 4) | False hits (of 5) |
| --- | --- | --- |
| 0.90 | 4 | **1**: "minimum attendance for undergraduates" vs "... for graduate students", 0.909 |
| **0.93 (shipped)** | 4 | 0 |
| 0.95 | 3 | 0 |
| 0.97 | 2 | 0 |

Following the lecture's rule, the lowest threshold with zero false hits is **0.93**. The 0.90
false hit is exactly the dangerous kind: a graduate student would be served the undergraduate
attendance rule.

Never cached: follow-ups ("And for MS?", short questions with a pronoun), abstentions, fallbacks,
and anything without a valid citation.

## Evaluation method

`eval/run_eval.py` matches by **(source, section)**, not chunk id. Chunk ids change whenever the
chunk size changes, and the golden set was written before tuning.

- A golden entry matches a retrieved passage when the source is equal (or is one of a listed
  set: the Generative AI policy is printed in two documents), and the golden section is a
  case-insensitive **substring** of the section the chunker recorded.
- recall@k = matched golden entries / golden entries, averaged over questions that have any.
- Citation validity = citations whose (source, section) equals a retrieved passage / all
  citations.
- Abstention correctness = must-abstain questions with `answered_from_context: false` / all
  must-abstain questions.

The gate thresholds are unchanged from the starter: recall@5 may drop at most 5 points below
`eval/baseline.json`, abstention must be 100%, and citation validity at least 95%.
