"""Stage 2: Clean. Remove artefacts without destroying structure.

Rules (also in docs/PIPELINE.md):
1. Lines that repeat on at least 40% of a document's pages (running headers and footers
   such as "NATIONAL UNIVERSITY OF COMPUTER AND EMERGING SCIENCES") are removed.
2. Bare page numbers ("12", "iv", "Page 3 of 9") are removed.
3. Ligatures (fi, fl) and non-breaking spaces are normalised; letter-spaced words that
   pdf extraction produces ("c o u r s e") are re-joined.
4. Words hyphenated across a line break are re-joined ("regis-\\ntration").
5. Runs of blank lines collapse to one blank line: blank lines are paragraph boundaries,
   and the chunker needs them.

Deliberately NOT stripped: clause numbers on their own line ("1.21"), list markers
("a)", "1)") and table pipes. They look like noise, but they are exactly what an
exact-term question ("what does clause 1.21 say?") has to match, and they are how the
chunker finds section boundaries.
"""

from __future__ import annotations

import re
from collections import Counter

from .models import Document, Page

REPEAT_FRACTION = 0.4
_PAGE_NUMBER = re.compile(r"^\s*(?:page\s+)?(\d{1,3}|[ivxlcdm]{1,6})(\s+of\s+\d{1,3})?\s*$", re.I)
_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
              " ": " ", "’": "'", "‘": "'", "“": '"', "”": '"',
              "–": "-", "—": "-", "": "•"}
# five or more single letters separated by single spaces: "c o u r s e"
_LETTER_SPACED = re.compile(r"\b(?:[A-Za-z] ){4,}[A-Za-z]\b")


def _normalise(line: str) -> str:
    """Comparison key for header/footer detection. Numbers at either END of the line are
    dropped, so a footer whose page number changes ("... Regulations 2026 5", "... 6")
    still repeats; numbers inside the line are kept, so "1.3 Rule ... 3." never collides."""
    key = re.sub(r"^[\d\s]+|[\d\s]+$", "", line)
    return re.sub(r"\s+", " ", key).strip().lower()


def repeating_lines(pages: list[Page]) -> set[str]:
    """Normalised lines that appear on at least REPEAT_FRACTION of the pages."""
    if len(pages) < 3:
        return set()
    counts: Counter[str] = Counter()
    for page in pages:
        counts.update({_normalise(ln) for ln in page.text.splitlines() if ln.strip()})
    threshold = max(2, int(len(pages) * REPEAT_FRACTION))
    # short keys ("a)", "b)") are list markers, not headers; table rows are content
    return {ln for ln, n in counts.items()
            if n >= threshold and len(ln) >= 12 and not ln.startswith("|")}


def clean_text(text: str, drop: set[str] | None = None) -> str:
    drop = drop or set()
    for bad, good in _LIGATURES.items():
        text = text.replace(bad, good)
    text = _LETTER_SPACED.sub(lambda m: m.group(0).replace(" ", ""), text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # hyphenation across lines
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if (stripped and _normalise(stripped) in drop) or _PAGE_NUMBER.fullmatch(stripped):
            continue
        out.append(re.sub(r"[ \t]+", " ", stripped))
    cleaned = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def clean(doc: Document) -> Document:
    """Strip headers and footers that repeat on every page; keep headings and
    section boundaries, because chunking and citations depend on them."""
    drop = repeating_lines(doc.pages)
    pages = [Page(source=p.source, page=p.page, text=clean_text(p.text, drop), ocr=p.ocr)
             for p in doc.pages]
    return Document(source=doc.source, doc_version=doc.doc_version,
                    superseded=doc.superseded, pages=[p for p in pages if p.text])
