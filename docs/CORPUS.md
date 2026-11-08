# Corpus

Source: **FAST-NUCES public website (nu.edu.pk)**, public pages only (no SLATE, Flex or anything
behind a login). Documents: **6**. Pages: **153 PDF pages** (58 + 64 + 26 + 5) plus two HTML pages.
Fetched on 8 November 2026 with `corpus/fetch.py`, one file at a time with a pause between
requests. We commit `corpus/MANIFEST.md` (URL + SHA-256 per file), `corpus/sources.yaml` and the
fetch script, never the PDFs (`corpus/raw/` is gitignored). Rebuild the corpus with:

```bash
# corpus/sources.yaml is committed: it lists the six documents and their versions
python corpus/fetch.py            # downloads to corpus/raw/, writes MANIFEST.md + _index.json
python corpus/fetch.py --verify   # re-hash local files against MANIFEST.md
```

| File (as the indexer stores it) | Pages | doc_version | superseded |
| --- | --- | --- | --- |
| `academic-rules-handbook-jun-2026.pdf` | 58 | 2026-06 | false |
| `undergraduate-academic-rules-aug-2023.pdf` | 26 (23 image-only) | 2023-08 | **true** |
| `prospectus-2026-academic-rules-and-regulations.pdf` | 5 (three columns) | 2026 | false |
| `student-handbook-jun-2026.pdf` | 64 | 2026-06 | false |
| `fee-structure-page.html` | 1 (HTML, 3 tables) | 2026-27 | false |
| `grading-page.html` | 1 (HTML, 5 tables) | 2026 | false |

## The seven required properties

| # | Required property | Document(s) that provide it | Evidence or notes |
| --- | --- | --- | --- |
| 1 | At least 6 documents, 40 pages | All six above | 153 PDF pages + 2 HTML pages; 29,672 words after cleaning (indexer log `chunking summary`). |
| 2 | Two versions of one policy | Undergraduate Academic Rules **Aug 2023** (old) and Academic Rules Handbook **Jun 2026** (current); the 2026 Prospectus restates the same rules with different clause numbers | `corpus/sources.yaml` marks the 2023 file `superseded: true`; `fetch.py` writes that into `_index.json`, the indexer copies it into every chunk's metadata, and the API filters `superseded: false` unless the question explicitly asks about an older version (`api/app/retrieval/chroma.py`, `wants_older_version`). Real differences we found by reading both: the course-withdrawal deadline (2023: "last day of classes"; 2026: "last day of the makeup week"), the summer semester (2023: "8 to 9 weeks"; 2026: "an 8-week semester", no new courses), and repeating a failed course (2023 clause 5.8: "whenever that course is offered again"; 2026 5.8: mandatory "in the subsequent semester"). |
| 3 | Scanned, image-only PDF | `undergraduate-academic-rules-aug-2023.pdf` | `pdffonts` lists only 3 fonts, all used on the cover; `pdftotext -f 2 -l 26` returns 1 byte per page. 23 of 26 pages have no text layer. Our extract stage OCRs them with Tesseract (indexer log: `"ocr_pages": 23`). The scanned document is also the superseded half of the version pair, so a pipeline without OCR silently loses the old version entirely, which is exactly failure mode A. |
| 4 | A table with real information | `fee-structure-page.html` (tuition per credit hour, miscellaneous fees, refund timeline), `grading-page.html` (grade points), the 2026 handbook's letter-grade table (p. 11) | HTML tables become `| a | b |` rows; PDF tables are pulled out with pdfplumber and re-emitted row by row (docs/PIPELINE.md shows a before/after). |
| 5 | Long definitions | Student Handbook 2026, section XII "Policy on Generative AI Based Tools" (numbered sub-sections 1-12, multi-paragraph definitions of acceptable and unacceptable use); also printed in the 2026 Academic Rules Handbook, section 10 | A fixed 100-word window cuts these in half; the structure-aware chunker keeps each numbered sub-section together (see the Stage B failure in FAILURE-ANALYSIS.md). |
| 6 | A deliberately absent topic | **Hostels and transport.** We left out "Transport and Hostel Facilities" from the prospectus on purpose. | A student plausibly asks "how do I get a hostel room?" and the Student Handbook only says hostels *exist* at some campuses, which is the worst case: the retriever finds a vaguely related passage and a model is tempted to answer. Golden questions q17, q18, q19 and q21 must abstain. |
| 7 | Exact-term content | Clause numbers (1.21 attendance, 4.18 freezing, 5.4 academic warning), CGPA thresholds (2.00, 3.50), fees (Rs. 12,000 per credit hour, Rs. 5,000 campus transfer), refund percentages | Golden questions q14, q15, q16 are exact-term questions. Embeddings blur "1.21" and "1.22"; the API adds a lexical `$contains` query for clause numbers and course codes (hybrid retrieval, PIPELINE.md). |

## Traps we noticed but did not add

The Prospectus page says 2026 while the Downloads page lists "Prospectus 2025"; the Academic
Calendar mixes a 2026-27 schedule with a 2023-24 holiday table. These are more outdated-source
cases; we kept the corpus to one clean version pair so the golden set can say exactly which answer
is right.
