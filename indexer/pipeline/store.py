"""Stage 5: Store. The only code in the whole system that writes to Chroma.

Build-then-swap (ADR 0001): the new index is written to a staging collection while the
API keeps serving the old one. Only when the staging collection is complete is the old
collection dropped and the staging one renamed into place. A Job that dies halfway
leaves the live index untouched; the API never sees a half-built index.
"""

from __future__ import annotations

import json
import time
from typing import Any

from .config import IndexerSettings
from .models import Chunk

WRITE_BATCH = 128


def get_client(settings: IndexerSettings) -> Any:
    import chromadb  # the thin client, from chromadb-client in requirements.txt
    from chromadb.config import Settings as ChromaSettings

    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                               settings=ChromaSettings(anonymized_telemetry=False))


def index_metadata(settings: IndexerSettings, dimension: int, count: int) -> dict[str, Any]:
    """Collection metadata. embed_model + dimension are the pin the API checks (4.4);
    index_id changes on every build and namespaces the API's semantic cache (3.3)."""
    return {
        "hnsw:space": "cosine",
        "embed_model": settings.embed_model,
        "dimension": dimension,
        "index_id": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "chunks": count,
    }


def store(chunks: list[Chunk], vectors: list[list[float]], settings: IndexerSettings,
          client: Any | None = None) -> int:
    """Write every chunk with its vector and metadata, and record the embedding model
    and vector dimension in the collection metadata (section 4.4). Return the count."""
    if len(chunks) != len(vectors):
        raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
    if not chunks:
        raise ValueError("refusing to publish an empty index")
    ids = [c.id for c in chunks]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate chunk ids: two documents share a file name")

    client = client or get_client(settings)
    staging = f"{settings.collection}-staging"
    try:
        client.delete_collection(staging)        # leftovers of a Job that died halfway
    except Exception:
        pass
    meta = index_metadata(settings, len(vectors[0]), len(chunks))
    collection = client.create_collection(name=staging, metadata=meta)
    for start in range(0, len(chunks), WRITE_BATCH):
        part = chunks[start:start + WRITE_BATCH]
        collection.add(
            ids=[c.id for c in part],
            documents=[c.text for c in part],
            embeddings=vectors[start:start + WRITE_BATCH],
            metadatas=[c.metadata() for c in part],
        )
    count = int(collection.count())
    if count != len(chunks):
        raise RuntimeError(f"staging collection holds {count} chunks, expected {len(chunks)}")

    # swap: the only window where the API can see no collection is between these two
    # calls (milliseconds); /readyz reports not-ready for that instant, nothing breaks.
    try:
        client.delete_collection(settings.collection)
    except Exception:
        pass
    collection.modify(name=settings.collection)
    print(json.dumps({"logger": "rahbar.indexer.store", "msg": "index published",
                      "collection": settings.collection, "chunks": count,
                      "index_id": meta["index_id"], "embed_model": settings.embed_model,
                      "dimension": meta["dimension"]}), flush=True)
    return count
