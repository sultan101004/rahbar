"""Stage 3: Chunk. Structure-aware, with overlap.

Token unit: whitespace-separated words. nomic-embed-text's tokenizer produces roughly
1.3 tokens per English word, so CHUNK_SIZE=300 words is about 400 model tokens, well
inside the model's 2048-token context.

Order of splitting, as section 3.1 asks: sections, then paragraphs, then sentences,
then (only for a single sentence longer than the target) words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Chunk, Document

_STOPWORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or",
              "the", "to", "with", "w.e.f.", "&", "-", "/", "vs"}
_ROMAN = r"(?:X{0,3})(?:IX|IV|V?I{0,3})"
_NUMBERED_HEADING = re.compile(rf"^(?:\d{{1,2}}|{_ROMAN})\.\s*(\S.*)$")
_CLAUSE_ONLY = re.compile(r"^\d{1,2}\.\d{1,2}(?:\.\d{1,2})?$")
_NUMBER_ONLY = re.compile(rf"^(?:\d{{1,2}}|{_ROMAN})\.$")
# a new paragraph starts at a clause number, a list marker or a bullet
_PARA_START = re.compile(r"^(?:\d{1,2}\.\d{1,2}\b|\(?[a-z]\)|\(?[ivx]{1,4}\)|\d{1,2}\)|[a-h]\.\s|•)")
_SENTENCE = re.compile(r"(?<=[.!?;])\s+(?=[A-Z(\"'0-9])")


@dataclass
class Block:
    section: str
    page: int
    text: str


def _title_case(words: list[str]) -> bool:
    content = [w for w in words if w.lower() not in _STOPWORDS and re.search(r"[A-Za-z]", w)]
    return bool(content) and all(w[0].isupper() or w[0].isdigit() or w[0] in "(\"'" for w in content)


def heading_of(line: str, after_break: bool = True) -> str | None:
    """Return the heading text if `line` is a heading, else None.

    - Markdown: '## 2. Academic warning'
    - numbered: '2. Grading and GPA Calculations', 'XII. Policy on Generative AI Based Tools'
    - unnumbered sub-headings: 'Attendance Requirements' (2-9 words, Title Case, no
      sentence punctuation)
    Numbered list items ('7. Students will show tolerance ...') are not headings: their
    words are not Title Case. A line that continues an unfinished sentence
    (`after_break=False`) is never a heading: in a multi-column PDF a wrapped line such
    as 'Average (SGPA) and the Cumulative Grade Point Average' is Title Case by accident.
    """
    s = line.strip()
    if not s or s.startswith("|"):
        return None
    if s.startswith("#"):
        return s.lstrip("#").strip() or None
    body = _NUMBERED_HEADING.sub(r"\1", s)          # the text after '2. ' or 'XII. '
    if not after_break or s[0] in "•·-*(" or "...." in s \
            or re.search(r"[=*]|\d\.\d\d", s) or re.search(r"\w\. \w", body):
        return None
    s = re.sub(r"\s+\d{1,3}$", "", s)               # trailing page number (TOC, column bleed)
    words = s.rstrip(":").split()
    if not words or not (words[0][0].isupper() or words[0][0].isdigit()):
        return None
    if len(words) > 10 or s.endswith((".", ",", ";")) or _CLAUSE_ONLY.match(s):
        return None
    m = _NUMBERED_HEADING.match(s)
    if m and m.group(0).split(".")[0]:
        rest = m.group(1).rstrip(":").split()
        return s.rstrip(":") if rest and _title_case(rest) and len(rest) <= 9 else None
    if 2 <= len(words) <= 9 and not s.endswith(":") and _title_case(words) \
            and not re.search(r"\d{3,}|Rs\.?|%", s):
        return s
    return None


def to_blocks(doc: Document) -> list[Block]:
    """Walk the pages, track the current heading, and cut paragraphs."""
    blocks: list[Block] = []
    major, minor = doc.source, ""
    buf: list[str] = []
    buf_page = 1
    pending_number = ""          # '3.' or '1.21' on its own line, joined to the next line
    after_break = True           # did the previous line finish a sentence (or a heading)?

    def section() -> str:
        return minor or major

    def flush() -> None:
        nonlocal buf
        text = " ".join(buf).strip()
        if text:
            blocks.append(Block(section(), buf_page, text))
        buf = []

    for page in doc.pages:
        in_table = False
        after_break = True
        for raw in page.text.splitlines():
            line = raw.strip()
            if pending_number and line:
                line, pending_number = f"{pending_number} {line}", ""
            if not line:
                flush()
                in_table = False
                after_break = True
                continue
            if _NUMBER_ONLY.match(line) or _CLAUSE_ONLY.match(line):
                pending_number = line
                continue
            heading = heading_of(line, after_break)
            after_break = bool(heading) or line.endswith((".", ":", ";", ")", "?", "!", "|"))
            if heading:
                flush()
                if raw.lstrip().startswith("#"):
                    major, minor = heading, ""
                elif _NUMBERED_HEADING.match(heading):
                    major, minor = heading, ""
                else:
                    minor = heading
                continue
            is_row = line.startswith("|")
            if is_row != in_table or (not is_row and _PARA_START.match(line)):
                flush()
            in_table = is_row
            if not buf:
                buf_page = page.page
            buf.append(line + ("\n" if is_row else ""))
        flush()
    return blocks


def _split_long(text: str, size: int) -> list[str]:
    """Paragraph -> sentence-sized pieces (rows for tables), then word windows."""
    units = [u for u in (text.split("\n") if "|" in text else _SENTENCE.split(text)) if u.strip()]
    out: list[str] = []
    for unit in units:
        words = unit.split()
        if len(words) <= size:
            out.append(unit.strip())
        else:
            out.extend(" ".join(words[i:i + size]) for i in range(0, len(words), size))
    return out


def chunk(doc: Document, size: int, overlap: int) -> list[Chunk]:
    """Split on sections, then paragraphs, then sentences, keeping each chunk under
    `size` words, with `overlap` words shared between neighbours in the same section.
    Every chunk keeps the section heading it sits under, its page, doc_version and
    superseded."""
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError(f"need 0 <= overlap < size, got size={size} overlap={overlap}")
    stem = re.sub(r"[^a-z0-9]+", "-", doc.source.lower().rsplit(".", 1)[0]).strip("-")
    chunks: list[Chunk] = []

    def emit(section: str, page: int, pieces: list[str]) -> None:
        body = " ".join(pieces).replace("\n ", "\n").strip()
        if not body:
            return
        chunks.append(Chunk(
            id=f"{stem}-{len(chunks):04d}",
            # the heading travels with the text: it is what makes "attendance" retrievable
            # from a chunk whose body only says "1.21 Students are required to ..."
            text=f"{section}\n{body}",
            source=doc.source, section=section[:200], page=page,
            doc_version=doc.doc_version, superseded=doc.superseded,
        ))

    blocks = to_blocks(doc)
    i = 0
    while i < len(blocks):
        section = blocks[i].section
        group = []
        while i < len(blocks) and blocks[i].section == section:
            group.append(blocks[i])
            i += 1
        pieces: list[str] = []
        count, page = 0, group[0].page
        for block in group:
            units = [block.text] if len(block.text.split()) <= size else _split_long(block.text, size)
            for unit in units:
                n = len(unit.split())
                if pieces and count + n > size:
                    emit(section, page, pieces)
                    tail = " ".join(pieces).split()[-overlap:] if overlap else []
                    pieces = [" ".join(tail)] if tail else []
                    count, page = len(tail), block.page
                pieces.append(unit)
                count += n
        emit(section, page, pieces)
    return chunks


def fixed_chunks(doc: Document, size: int, overlap: int) -> list[Chunk]:
    """The naive baseline, kept only for the Stage B failure demo (CHUNK_STRATEGY=fixed):
    fixed windows of `size` words over the whole document, blind to headings. A definition
    or a clause that straddles a window edge is cut in half."""
    stem = re.sub(r"[^a-z0-9]+", "-", doc.source.lower().rsplit(".", 1)[0]).strip("-")
    words: list[tuple[str, int]] = [(w, p.page) for p in doc.pages for w in p.text.split()]
    step = max(1, size - overlap)
    chunks = []
    for n, start in enumerate(range(0, len(words), step)):
        window = words[start:start + size]
        if not window:
            break
        chunks.append(Chunk(id=f"{stem}-{n:04d}", text=" ".join(w for w, _ in window),
                            source=doc.source, section=f"words {start}-{start + len(window)}",
                            page=window[0][1], doc_version=doc.doc_version,
                            superseded=doc.superseded))
    return chunks


def word_count(text: str) -> int:
    return len(text.split())
