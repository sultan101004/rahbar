"""The real retriever (sections 3.2 and 4.4). Read-only: it never writes to Chroma.

Retrieval is hybrid in a small way: the embedding query always runs; when the question
contains an exact term (a clause number such as 1.21, a course code such as CS1004) a
second, lexical query asks Chroma for chunks that literally contain that term. Embeddings
blur exact terms ("1.21" and "1.22" embed almost identically); a substring match does not.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from ..config import Settings
from ..schemas import Passage
from .embedder import OllamaEmbedder

_CLAUSE = re.compile(r"\b\d{1,2}\.\d{1,2}(?:\.\d{1,2})?\b")
_COURSE_CODE = re.compile(r"\b[A-Z]{2,4}[- ]?\d{3,4}\b")
# The superseded filter is lifted only when the user explicitly asks about an older version.
_OLDER = re.compile(r"\b(old|older|previous|earlier|former|superseded|outdated|repealed|"
                    r"used to|before 20\d\d|in 20(?:1\d|2[0-5])|20(?:1\d|2[0-5]) (?:rules|"
                    r"handbook|version|edition|policy))\b", re.I)
INFO_TTL_S = 15.0


def exact_terms(question: str) -> list[str]:
    terms = _CLAUSE.findall(question) + _COURSE_CODE.findall(question)
    return list(dict.fromkeys(terms))[:3]


def wants_older_version(question: str) -> bool:
    return bool(_OLDER.search(question))


@dataclass
class IndexInfo:
    count: int
    embed_model: str | None
    dimension: int | None
    index_id: str


class ChromaRetriever:
    name = "chroma"

    def __init__(self, settings: Settings) -> None:
        import chromadb  # the thin client, from chromadb-client in requirements.txt
        from chromadb.config import Settings as ChromaSettings

        self.settings = settings
        self.client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                                          settings=ChromaSettings(anonymized_telemetry=False))
        self.embedder = OllamaEmbedder(settings)
        self._info: tuple[float, IndexInfo] | None = None

    # ---------------------------------------------------------------- index metadata
    def _collection(self) -> Any:
        # Looked up by name on every call: the indexer swaps in a new collection (new id)
        # on each run, so a handle cached at startup would point at a deleted collection.
        return self.client.get_collection(self.settings.collection)

    def index_info(self, fresh: bool = False) -> IndexInfo:
        """Count and pin metadata of the live collection. Raises if Chroma is unreachable
        or the collection does not exist."""
        now = time.monotonic()
        if not fresh and self._info and now - self._info[0] < INFO_TTL_S:
            return self._info[1]
        col = self._collection()
        meta = col.metadata or {}
        info = IndexInfo(count=int(col.count()), embed_model=meta.get("embed_model"),
                         dimension=meta.get("dimension"),
                         index_id=str(meta.get("index_id") or col.id))
        self._info = (now, info)
        return info

    def embed_query(self, question: str) -> list[float]:
        return self.embedder.embed_query(question)

    # ---------------------------------------------------------------- the query
    def retrieve(self, question: str, k: int) -> list[Passage]:
        vector = self.embed_query(question)
        info = self.index_info()
        if info.dimension and len(vector) != int(info.dimension):
            raise RuntimeError(f"query vector has dimension {len(vector)} but the index was "
                               f"built with {info.dimension}: embedding model mismatch")
        col = self._collection()
        where: dict[str, Any] | None = None if wants_older_version(question) \
            else {"superseded": False}

        lexical: list[Passage] = []
        for term in exact_terms(question):
            lexical += self._query(col, vector, k, where, {"$contains": term}, lexical=True)
        semantic = self._query(col, vector, k, where, None, lexical=False)

        merged: dict[str, Passage] = {}
        for p in lexical + semantic:        # exact-term hits first: they hold the term asked
            merged.setdefault(p.chunk_id, p)
        return list(merged.values())[:k]

    def _query(self, col: Any, vector: list[float], k: int, where: dict[str, Any] | None,
               where_document: dict[str, Any] | None, lexical: bool) -> list[Passage]:
        kwargs: dict[str, Any] = {"query_embeddings": [vector], "n_results": k,
                                  "include": ["documents", "metadatas", "distances"]}
        if where:
            kwargs["where"] = where
        if where_document:
            kwargs["where_document"] = where_document
        res = col.query(**kwargs)
        out = []
        for cid, doc, meta, dist in zip(res["ids"][0], res["documents"][0],
                                        res["metadatas"][0], res["distances"][0]):
            meta = meta or {}
            out.append(Passage(
                chunk_id=cid, text=doc or "", source=str(meta.get("source", "?")),
                section=str(meta.get("section", "?")), page=meta.get("page"),
                score=round(1.0 - float(dist), 4),          # cosine distance -> similarity
                doc_version=str(meta.get("doc_version", "")) or None,
                superseded=bool(meta.get("superseded", False)), lexical=lexical,
            ))
        return out
