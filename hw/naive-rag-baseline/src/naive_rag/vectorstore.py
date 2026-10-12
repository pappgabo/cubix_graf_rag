"""Qdrant vector store setup.

Local, on-disk Qdrant by default (no Docker needed). Set QDRANT_URL in
.env to use a Qdrant server instead. Switching to pgvector later only
requires replacing this module (e.g. with langchain-postgres).
"""

from __future__ import annotations

import atexit
import shutil

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from .config import PROJECT_ROOT, get_settings
from .models import get_embeddings


def _client(register_close: bool = True) -> QdrantClient:
    s = get_settings()
    if s.qdrant_url:
        client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key)
    else:
        s.qdrant_path.mkdir(parents=True, exist_ok=True)
        client = QdrantClient(path=str(s.qdrant_path))
    if register_close:
        # Close cleanly before interpreter shutdown (avoids noisy __del__).
        atexit.register(client.close)
    return client


def _drop_collection() -> None:
    """Remove any existing index so every ingest starts from scratch.

    langchain-qdrant's `force_recreate=True` did NOT wipe the old points in
    local (path) mode, and `delete_collection` there uses
    `shutil.rmtree(ignore_errors=True)`, which can silently fail on Windows
    while a file handle is open. So in local mode we delete the storage
    folder ourselves, while no client is open. Server mode uses the API.
    """
    s = get_settings()
    if s.qdrant_url:
        client = _client(register_close=False)
        try:
            if client.collection_exists(s.collection_name):
                client.delete_collection(s.collection_name)
        finally:
            client.close()
        return

    path = s.qdrant_path.resolve()
    if path == PROJECT_ROOT or PROJECT_ROOT not in path.parents:
        raise RuntimeError(
            f"Refusing to delete Qdrant path outside the project: {path}")
    if path.exists():
        shutil.rmtree(path)  # raises on failure instead of hiding it


def build_index(documents: list[Document]) -> QdrantVectorStore:
    """Recreate the collection from scratch and index the given chunks."""
    s = get_settings()
    _drop_collection()
    store = QdrantVectorStore.from_documents(
        documents,
        embedding=get_embeddings(),
        collection_name=s.collection_name,
        **({"url": s.qdrant_url, "api_key": s.qdrant_api_key}
           if s.qdrant_url else {"path": str(s.qdrant_path)}),
    )
    n = store.client.count(s.collection_name, exact=True).count
    if n != len(documents):
        raise RuntimeError(
            f"Index size mismatch: {n} points in Qdrant, "
            f"{len(documents)} chunks ingested.")
    return store


def get_vector_store() -> QdrantVectorStore:
    """Open the existing collection for querying."""
    s = get_settings()
    return QdrantVectorStore(
        client=_client(),
        collection_name=s.collection_name,
        embedding=get_embeddings(),
    )
