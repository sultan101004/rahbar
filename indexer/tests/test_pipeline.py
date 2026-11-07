"""Unit tests for the five pipeline stages. No Chroma, no Ollama: fakes stand in."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from pipeline import embed as embed_mod
from pipeline.chunk import chunk, heading_of, to_blocks
from pipeline.clean import clean, clean_text, repeating_lines
from pipeline.config import get_settings
from pipeline.extract import column_splits, extract, html_to_text, table_to_rows
from pipeline.models import Document, Page
from pipeline.run import discover, run_pipeline
from pipeline.store import store
from tests.test_starter_dummy import FakeClient

FIXTURES = Path(__file__).resolve().parents[2] / "eval" / "fixtures"


# --------------------------------------------------------------------------- extract
def test_extract_markdown_strips_front_matter() -> None:
    doc = extract(str(FIXTURES / "academic-rules-2026.md"), "2026", False)
    assert doc.source == "academic-rules-2026.md"
    assert not doc.pages[0].text.startswith("---")
    assert "## 1. Attendance" in doc.pages[0].text


def test_html_tables_become_pipe_rows_and_menus_are_dropped() -> None:
    markup = """<html><nav><a>Home</a><a>Admissions</a></nav><body>
      <h2>Tuition Fee</h2><p>Per credit hour:</p>
      <table><tr><th>Program</th><th>Fee</th></tr><tr><td>BS</td><td>Rs. 12,000</td></tr></table>
      <script>var x = 1;</script></body></html>"""
    text = html_to_text(markup)
    assert text.startswith("## Tuition Fee")
    assert "| BS | Rs. 12,000 |" in text
    assert "Home" not in text and "var x" not in text


def test_table_rows_are_dewrapped() -> None:
    assert table_to_rows([["Late\nRegistration", "Rs. 5,000"], [None, None]]) == \
        "| Late Registration | Rs. 5,000 |"


def test_column_splits_finds_the_gutter_of_a_two_column_page() -> None:
    left = [(50.0 + i % 150, 55.0 + i % 150) for i in range(300)]
    right = [(320.0 + i % 150, 325.0 + i % 150) for i in range(300)]
    splits = column_splits(left + right, 520.0)
    assert len(splits) == 1 and 205 < splits[0] < 320


def test_single_column_page_is_not_split() -> None:
    xs = [(float(x), float(x) + 5) for x in range(40, 480, 2)] * 3
    assert column_splits(xs, 520.0) == []


# --------------------------------------------------------------------------- clean
def test_repeating_headers_and_page_numbers_are_removed_but_clauses_kept() -> None:
    pages = [Page("h.pdf", n, f"NATIONAL UNIVERSITY OF SCIENCES\n1.{n} Rule number {n}.\n"
                              f"Student Handbook 2026 {n}\n{n}") for n in range(1, 6)]
    drop = repeating_lines(pages)
    cleaned = clean_text(pages[2].text, drop)
    assert "NATIONAL UNIVERSITY" not in cleaned
    assert "Student Handbook" not in cleaned
    assert "1.3 Rule number 3." in cleaned
    assert not cleaned.endswith("\n3")


def test_clean_fixes_ligatures_hyphenation_and_letter_spacing() -> None:
    assert clean_text("the ﬁnal regis-\ntration of c o u r s e") == \
        "the final registration of course"


def test_clean_keeps_metadata() -> None:
    doc = Document("a.md", "2023", True, [Page("a.md", 1, "text")])
    out = clean(doc)
    assert (out.doc_version, out.superseded) == ("2023", True)


# --------------------------------------------------------------------------- chunk
@pytest.mark.parametrize("line,expected", [
    ("## 2. Academic warning", "2. Academic warning"),
    ("2. Grading and GPA Calculations", "2. Grading and GPA Calculations"),
    ("XII. Policy on Generative AI Based Tools", "XII. Policy on Generative AI Based Tools"),
    ("Attendance Requirements", "Attendance Requirements"),
    ("New Admissions 8", "New Admissions"),
    ("7. Students will show tolerance, understanding, and respect for", None),
    ("1.21 Students are required to maintain 100% attendance.", None),
    ("| Grade | Points |", None),
    ("the Head of Department to", None),
    ("• FAST Music Society", None),
])
def test_heading_detection(line: str, expected: str | None) -> None:
    assert heading_of(line) == expected


def test_wrapped_line_is_not_a_heading() -> None:
    assert heading_of("Average (SGPA) and the Cumulative Grade", after_break=False) is None


def _fixture_doc(name: str) -> Document:
    path = FIXTURES / name
    found = {p.name: (v, s) for p, v, s in discover(str(FIXTURES))}
    version, superseded = found[name]
    return clean(extract(str(path), version, superseded))


def test_chunks_follow_sections_and_carry_metadata() -> None:
    chunks = chunk(_fixture_doc("academic-rules-2023.md"), 300, 40)
    sections = [c.section for c in chunks]
    assert "2. Academic warning" in sections
    for c in chunks:
        assert c.metadata().keys() == {"source", "section", "page", "doc_version", "superseded"}
        assert c.superseded is True and c.doc_version == "2023"
        assert c.text.startswith(c.section)


def test_a_definition_is_not_cut_in_half_when_it_fits() -> None:
    definition = "Plagiarism means " + " ".join(f"word{i}" for i in range(120)) + "."
    doc = Document("d.md", "1", False, [Page("d.md", 1, f"## Definitions\n\n{definition}")])
    chunks = chunk(doc, 300, 40)
    assert len(chunks) == 1 and definition in chunks[0].text


def test_long_sections_split_with_overlap() -> None:
    sentences = " ".join(f"Sentence {i} has exactly six words." for i in range(60))
    doc = Document("d.md", "1", False, [Page("d.md", 1, f"## Long\n\n{sentences}")])
    chunks = chunk(doc, 100, 20)
    assert len(chunks) > 3
    for c in chunks:
        assert len(c.text.split()) <= 100 + 20 + 2      # size + overlap + heading
    first_tail = chunks[0].text.split()[-20:]
    assert " ".join(first_tail) in chunks[1].text      # the overlap is really shared


def test_chunk_ids_are_stable() -> None:
    doc = _fixture_doc("fees-2026.md")
    assert [c.id for c in chunk(doc, 300, 40)] == [c.id for c in chunk(doc, 300, 40)]


def test_chunk_rejects_bad_settings() -> None:
    with pytest.raises(ValueError):
        chunk(Document("x", "1", False, []), 50, 50)


def test_clause_number_on_its_own_line_is_joined_to_its_text() -> None:
    doc = Document("h.pdf", "1", False, [Page("h.pdf", 1, "Attendance Requirements\n1.21\n"
                                                          "Students must attend.")])
    blocks = to_blocks(doc)
    assert blocks[0].section == "Attendance Requirements"
    assert blocks[0].text.startswith("1.21 Students")


# --------------------------------------------------------------------------- embed
def test_embed_batches_and_uses_the_pinned_model(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]] * len(body["input"])})

    real_client = httpx.Client
    monkeypatch.setattr(embed_mod.httpx, "Client",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text")
    vectors = embed_mod.embed([f"t{i}" for i in range(40)], get_settings())
    assert len(vectors) == 40
    assert [len(b["input"]) for b in seen] == [32, 8]
    assert all(b["model"] == "nomic-embed-text" for b in seen)
    assert seen[0]["input"][0].startswith("search_document: ")


# --------------------------------------------------------------------------- store
class RenamableCollection:
    def __init__(self, client: "SwapClient", name: str, metadata: dict) -> None:
        self.client, self.name, self.metadata, self.rows = client, name, metadata, {}

    def add(self, ids, documents, embeddings, metadatas) -> None:
        for i, d, e, m in zip(ids, documents, embeddings, metadatas):
            self.rows[i] = (d, e, m)

    def count(self) -> int:
        return len(self.rows)

    def modify(self, name: str) -> None:
        self.client.collections[name] = self.client.collections.pop(self.name)
        self.name = name


class SwapClient(FakeClient):
    def create_collection(self, name: str, metadata: dict) -> RenamableCollection:  # type: ignore[override]
        self.collections[name] = RenamableCollection(self, name, metadata)  # type: ignore[assignment]
        return self.collections[name]  # type: ignore[return-value]


def test_store_builds_in_staging_then_swaps_and_records_the_pin() -> None:
    client = SwapClient()
    settings = get_settings()
    chunks = chunk(_fixture_doc("fees-2026.md"), 300, 40)
    vectors = [[0.0, 1.0, 0.0, 0.0]] * len(chunks)
    assert store(chunks, vectors, settings, client=client) == len(chunks)
    assert set(client.collections) == {settings.collection}
    meta = client.collections[settings.collection].metadata
    assert meta["embed_model"] == settings.embed_model
    assert meta["dimension"] == 4
    assert meta["hnsw:space"] == "cosine" and meta["index_id"]


def test_store_refuses_mismatched_or_empty_input() -> None:
    with pytest.raises(ValueError):
        store([], [], get_settings(), client=SwapClient())


def test_full_pipeline_on_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    import pipeline.embed
    import pipeline.store

    client = SwapClient()
    monkeypatch.setenv("CORPUS_DIR", str(FIXTURES))
    monkeypatch.setattr(pipeline.embed, "embed",
                        lambda texts, settings: [[1.0, 0.0]] * len(texts))
    monkeypatch.setattr(pipeline.store, "get_client", lambda settings: client)
    assert run_pipeline(get_settings()) >= 9
    rows = client.collections["rahbar"].rows.values()
    assert any(m["superseded"] for _d, _e, m in rows)
    assert any(not m["superseded"] for _d, _e, m in rows)
