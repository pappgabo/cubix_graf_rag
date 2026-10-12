"""Central configuration for the Naive RAG pipeline.

All values can be overridden from a .env file in the project root
(see .env.example). Paths are derived from the project layout.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/naive_rag/config.py -> src/naive_rag -> src -> <project root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM / embeddings -------------------------------------------------
    # provider: "openai" (default) or "ollama"
    llm_provider: str = "openai"
    openai_api_key: str | None = None
    chat_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    # Only used when llm_provider == "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.1"
    ollama_embedding_model: str = "nomic-embed-text"

    # --- Vector store (Qdrant) -------------------------------------------
    # If qdrant_url is set, a Qdrant server is used; otherwise a local,
    # on-disk Qdrant (no Docker needed) is created at qdrant_path.
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    collection_name: str = "f1_naive_rag"

    # --- Chunking (deliberately NOT default) ------------------------------
    # Measured on this corpus: paragraphs are short (median 121 chars,
    # p90 721, 83% <= 500 chars). 500 chars therefore keeps most paragraphs
    # whole and merges a few short ones, giving focused embeddings. The
    # 75-char overlap (~15%) keeps a sentence that straddles a boundary
    # retrievable from either side. Trade-off (expected for a baseline):
    # small chunks fragment context, which hurts multi-hop/global questions.
    # These are starting values: compare other sizes with
    #   uv run naive-rag ingest --chunk-size N --chunk-overlap M
    chunk_size: int = 500
    chunk_overlap: int = 75

    # --- Retrieval --------------------------------------------------------
    # k=4: a typical naive-RAG setting; enough to cover a simple fact with
    # some redundancy, too few to gather evidence from many documents.
    top_k: int = 4

    # --- Paths (derived) --------------------------------------------------
    corpus_dir: Path = Field(default=PROJECT_ROOT / "corpus")
    questions_file: Path = Field(default=PROJECT_ROOT / "questions.md")
    baseline_dir: Path = Field(default=PROJECT_ROOT / "baseline")
    qdrant_path: Path = Field(default=PROJECT_ROOT / ".qdrant")
    index_info_file: Path = Field(default=PROJECT_ROOT / ".index_info.json")


@lru_cache
def get_settings() -> Settings:
    return Settings()
