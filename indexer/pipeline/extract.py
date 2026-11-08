"""Stage 1: Extract. PDF (or HTML, or Markdown) to text, page by page.

Every page comes back as plain text in which structure is still visible:
- Markdown headings stay as `#` lines (the CI fixtures, the HTML pages);
- PDF tables are pulled out separately by pdfplumber and re-emitted as `| a | b |` rows,
  so their columns stay aligned instead of interleaving with body text;
- pages with no text layer are rendered to an image and OCR'd with Tesseract (ocr=True).
"""

from __future__ import annotations

import html
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .models import Document, Page

# A page with fewer printable characters than this is treated as image-only.
MIN_TEXT_CHARS = 40
OCR_DPI = 200


def _log(msg: str, **fields: object) -> None:
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "logger": "rahbar.indexer.extract", "msg": msg, **fields}), flush=True)


def extract(path: str, doc_version: str, superseded: bool) -> Document:
    """Return the document's text page by page.

    Detect pages with no text layer and OCR them; mark those pages ocr=True.
    The OCR libraries need system packages in the Dockerfile (tesseract-ocr,
    poppler-utils), not only pip packages.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    doc = Document(source=p.name, doc_version=doc_version, superseded=superseded)
    if suffix == ".pdf":
        doc.pages = _extract_pdf(p)
    elif suffix in {".html", ".htm"}:
        doc.pages = [Page(source=p.name, page=1, text=html_to_text(p.read_text("utf-8", "replace")))]
    elif suffix in {".md", ".txt"}:
        doc.pages = [Page(source=p.name, page=1, text=strip_front_matter(p.read_text("utf-8")))]
    else:
        raise ValueError(f"unsupported document type: {p.name}")
    ocr_pages = [pg.page for pg in doc.pages if pg.ocr]
    _log("extracted", source=p.name, pages=len(doc.pages), ocr_pages=len(ocr_pages),
         chars=sum(len(pg.text) for pg in doc.pages))
    return doc


# ----------------------------------------------------------------------------- Markdown
def strip_front_matter(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return "\n".join(lines[i + 1:]).lstrip("\n")
    return text


# ----------------------------------------------------------------------------- PDF
def _extract_pdf(path: Path) -> list[Page]:
    import pdfplumber

    pages: list[Page] = []
    with pdfplumber.open(str(path)) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            text = _pdf_page_text(page)
            if len(re.sub(r"\s", "", text)) >= MIN_TEXT_CHARS:
                pages.append(Page(source=path.name, page=number, text=text))
                continue
            ocr_text = _ocr_page(path, number)
            # keep whichever is longer: a cover page may have a few real characters
            if len(ocr_text.strip()) > len(text.strip()):
                pages.append(Page(source=path.name, page=number, text=ocr_text, ocr=True))
            else:
                pages.append(Page(source=path.name, page=number, text=text))
    return pages


def _real_tables(page: Any) -> list[Any]:
    """pdfplumber's tables, minus false positives: a layout frame around a whole page,
    a one-row footer, or 'cells' that are really paragraphs of a multi-column page."""
    try:
        found = page.find_tables()
    except Exception:  # pdfplumber can fail on malformed pages; fall back to plain text
        return []
    keep = []
    page_area = float(page.width * page.height) or 1.0
    for table in found:
        x0, top, x1, bottom = table.bbox
        rows = [r for r in (table.extract() or []) if any(c and c.strip() for c in r)]
        cells = [c for r in rows for c in r if c and c.strip()]
        if len(rows) < 2 or max((len(r) for r in rows), default=0) < 2:
            continue
        if (x1 - x0) * (bottom - top) > 0.6 * page_area:
            continue
        if cells and sum(len(c) for c in cells) / len(cells) > 80:
            continue
        keep.append(table)
    return keep


def column_splits(xs: list[tuple[float, float]], width: float, bins: int = 120) -> list[float]:
    """x positions of vertical gutters: bands in the middle 60% of the page that almost no
    character crosses. Two-column handbooks and the three-column prospectus need this,
    or extract_text() interleaves lines from neighbouring columns."""
    if len(xs) < 200 or width <= 0:
        return []
    counts = [0] * bins
    for x0, x1 in xs:
        for b in range(max(0, int(x0 / width * bins)), min(bins, int(x1 / width * bins) + 1)):
            counts[b] += 1
    limit = max(1, int(len(xs) * 0.004))
    splits: list[float] = []
    b = int(bins * 0.2)
    while b < int(bins * 0.8):
        if counts[b] <= limit:
            start = b
            while b < bins and counts[b] <= limit:
                b += 1
            if b - start >= 2:                          # at least ~1.6% of the width
                splits.append((start + b) / 2 / bins * width)
        b += 1
    return splits


def _pdf_page_text(page: Any) -> str:
    """Body text column by column, tables removed, then each table as pipe-delimited rows."""
    # Some PDFs here are 2-up impositions: each page also carries its neighbour's text at
    # negative x, outside the visible box. Crop to the box or that text leaks in.
    page = page.within_bbox(page.bbox)
    tables = _real_tables(page)
    boxes = [t.bbox for t in tables]

    def outside(obj: dict[str, Any]) -> bool:
        cx = (obj["x0"] + obj["x1"]) / 2
        cy = (obj["top"] + obj["bottom"]) / 2
        return not any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in boxes)

    body_page = page.filter(outside) if boxes else page
    chars = [(c["x0"], c["x1"]) for c in body_page.chars if c.get("text", "").strip()]
    edges = [0.0] + column_splits(chars, float(page.width)) + [float(page.width)]
    parts = []
    for left, right in zip(edges, edges[1:]):
        column = body_page.crop((left, 0, right, page.height), strict=False)
        parts.append(str(column.extract_text() or ""))
    rendered = [table_to_rows(t.extract()) for t in tables]
    return "\n\n".join([p for p in parts if p.strip()] + [r for r in rendered if r])


def table_to_rows(rows: list[list[str | None]]) -> str:
    """Render a table as `| a | b |` lines, one row per line, cells de-wrapped."""
    out = []
    for row in rows:
        cells = [re.sub(r"\s+", " ", c or "").strip() for c in row]
        if any(cells):
            out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def _ocr_page(path: Path, number: int) -> str:
    """OCR one page. If Tesseract is not installed, record the loss and return ''."""
    try:
        import pytesseract
        from pdf2image import convert_from_path

        images = convert_from_path(str(path), dpi=OCR_DPI, first_page=number, last_page=number)
        if not images:
            return ""
        return str(pytesseract.image_to_string(images[0], lang="eng"))
    except Exception as exc:  # missing binary, corrupt image: report it, do not crash the Job
        _log("ocr failed", source=path.name, page=number, error=type(exc).__name__)
        return ""


# ----------------------------------------------------------------------------- HTML
_SKIP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "form", "select",
              "button", "svg", "iframe", "head"}
_BLOCK_TAGS = {"p", "div", "li", "br", "section", "article", "ul", "ol", "tr", "table",
               "h1", "h2", "h3", "h4", "h5", "h6", "dd", "dt"}


class _HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.buf: list[str] = []
        self.skip = 0
        self.heading: int | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if not text:
            return
        if self.heading:
            self.lines.extend(["", "#" * self.heading + " " + text, ""])
        else:
            self.lines.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "tr":
            self._flush()
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag in _BLOCK_TAGS:
            self._flush()
            if tag[0] == "h" and tag[1:].isdigit():
                self.heading = int(tag[1:])

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in ("td", "th") and self.row is not None and self.cell is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if any(self.row):
                self.lines.append("| " + " | ".join(self.row) + " |")
            self.row = None
        elif tag in _BLOCK_TAGS:
            self._flush()
            if tag[0] == "h" and tag[1:].isdigit():
                self.heading = None
            if tag == "table":
                self.lines.append("")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self.cell is not None:
            self.cell.append(data)
        else:
            self.buf.append(data)


def html_to_text(markup: str) -> str:
    """Visible text of an HTML page, headings as `#` lines and tables as pipe rows.

    Everything before the first heading (menus, banners) is dropped: on the
    FAST-NUCES pages it is navigation, not content."""
    parser = _HtmlText()
    parser.feed(markup)
    parser._flush()
    lines = [html.unescape(ln) for ln in parser.lines]
    first = next((i for i, ln in enumerate(lines) if ln.startswith("#")), 0)
    text = "\n".join(lines[first:])
    return re.sub(r"\n{3,}", "\n\n", text).strip()
