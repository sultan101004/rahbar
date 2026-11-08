# ADR 0002: Structure-aware chunking at 300/40 words, with version metadata

## Status
Accepted · 8 November 2026

## Context
The corpus is rule books: numbered clauses under Title-Case sub-headings, long multi-paragraph
definitions (Generative AI policy), and tables. It holds two versions of the same rules (2023,
superseded, and 2026). A fixed-size chunker cuts clauses and definitions in half and loses the
heading that says what a clause is about. Without version metadata, the retriever faithfully
returns the 2023 rule.

## Decision
- Chunk by section, then paragraph, then sentence, under 300 words, with a 40-word overlap only
  between neighbours in the same section. The section heading is prepended to the chunk text.
- Every chunk carries `source, section, page, doc_version, superseded`. The API filters
  `superseded: false` unless the question explicitly asks about an older version.
- The numbers were chosen by measurement, not guessed: three structure-aware configurations
  (150/20, 300/40, 500/60) plus the fixed-size 100/0 baseline, scored by recall@3/@5 on the golden
  set. The table is in docs/PIPELINE.md.
- Contract change: `Passage` (internal, retriever to generator) gained `doc_version`,
  `superseded` and `lexical`. The evidence block tells the model when a passage is superseded,
  and the floor exempts exact-term hits. `AskResponse` is unchanged; the cache state travels in
  an `X-Cache` header the UI already understands.

## Options considered
- **Fixed-size windows:** the naive baseline. Kept as `CHUNK_STRATEGY=fixed`, only for the Stage B
  failure demonstration.
- **One chunk per clause:** most clauses are 20–60 words, too short to carry context, and it
  triples the chunk count.
- **Prompting the model to "prefer the newest version":** a prompt cannot fix retrieval that only
  returned the old version. Metadata filtering can.

## Consequences
- Section names become the unit of evaluation (golden set matches on source + section), which
  survives chunk-size changes.
- Heading detection is heuristic. It is imperfect on the three-column Prospectus
  (PIPELINE.md, "What we could not recover").
