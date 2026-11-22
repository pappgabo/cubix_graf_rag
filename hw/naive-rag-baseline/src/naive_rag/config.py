"""Central configuration for the Naive RAG pipeline.

All values can be overridden from a .env file in the project root
(see .env.example). Paths are derived from the project layout.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
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

    # --- Graph store (Neo4j, week 2) --------------------------------------
    # Same variable names are consumed by compose.yaml. There is no usable
    # password default: a blank NEO4J_PASSWORD is a configuration error
    # when a graph command runs.
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str | None = None
    neo4j_database: str = "neo4j"
    # Root node that every real document hangs off (handy for global queries).
    corpus_name: str = "f1-wikipedia"

    # --- Chunking (characters, not tokens) --------------------------------
    # Measured on the current local corpus after heading splits: a section
    # median is 992 characters, while 500-character chunks stop at the cap
    # (median chunk 387, p95 492, max 500) and cut sentences. 1200 keeps a
    # typical section together and still splits the long tail (section p90
    # is about 4700). Overlap is 100 characters, under 10 percent, and must
    # stay strictly below chunk_size. There is no configured extraction
    # input window; this size is not a claim about model capacity.
    # Override with CHUNK_SIZE / CHUNK_OVERLAP or the ingest CLI.
    chunk_size: int = 1200
    chunk_overlap: int = 100

    # --- Retrieval --------------------------------------------------------
    # k=4: a typical naive-RAG setting; enough to cover a simple fact with
    # some redundancy, too few to gather evidence from many documents.
    top_k: int = 4

    # --- Local-search context window --------------------------------------
    # These are explicit application limits. They are not read from the
    # chat model and are not a measured model capacity. The prompt estimate
    # is ceil(characters / 3), an overestimate, not an exact token count.
    # Input tokens plus the reserved answer must stay within the window.
    # Graph statements and source excerpts split the variable body; unused
    # room on either side can be used by the other.
    context_model_window: int = 8192
    context_answer_reserve: int = 1024
    context_graph_share: float = 0.5
    # Rendered description lines per node and per edge. The stored text is
    # unchanged. Lines that best match the question come first; the rest are
    # counted, not copied. A single line is never cut in half.
    context_description_lines: int = 8
    context_description_chars: int = 480

    # Extraction call window for the configured gpt-4o-mini chat model.
    # extraction_input_window is the whole context window. The allowed
    # prompt estimate is this value minus extraction_output_reserve, and
    # the reserve is passed as max_tokens. 128000 and 16384 are the
    # published context window and max output, not a measured call.
    # The answer-context window is separate. Both must be set together.
    extraction_input_window: int | None = 128000
    extraction_output_reserve: int | None = 16384

    # --- Paths (derived) --------------------------------------------------
    corpus_dir: Path = Field(default=PROJECT_ROOT / "corpus")
    questions_file: Path = Field(default=PROJECT_ROOT / "questions.md")
    baseline_dir: Path = Field(default=PROJECT_ROOT / "baseline")
    qdrant_path: Path = Field(default=PROJECT_ROOT / ".qdrant")
    index_info_file: Path = Field(default=PROJECT_ROOT / ".index_info.json")
    graph_dir: Path = Field(default=PROJECT_ROOT / "graph")

    @model_validator(mode="after")
    def _chunk_bounds(self) -> "Settings":
        if (not isinstance(self.chunk_size, int) or isinstance(self.chunk_size, bool)
                or self.chunk_size <= 0):
            raise ValueError(
                f"chunk_size must be a positive integer, got {self.chunk_size!r}")
        if (not isinstance(self.chunk_overlap, int)
                or isinstance(self.chunk_overlap, bool)
                or self.chunk_overlap < 0
                or self.chunk_overlap >= self.chunk_size):
            raise ValueError(
                "chunk_overlap must be an integer >= 0 and < chunk_size, "
                f"got {self.chunk_overlap!r} for size {self.chunk_size!r}")
        window = self.extraction_input_window
        reserve = self.extraction_output_reserve
        if (window is None) != (reserve is None):
            raise ValueError(
                "extraction_input_window and extraction_output_reserve "
                "must be set together")
        if window is not None and reserve is not None:
            if (not isinstance(window, int) or isinstance(window, bool)
                    or window <= 0):
                raise ValueError(
                    "extraction_input_window must be a positive integer, "
                    f"got {window!r}")
            if (not isinstance(reserve, int) or isinstance(reserve, bool)
                    or reserve <= 0 or reserve >= window):
                raise ValueError(
                    "extraction_output_reserve must be a positive integer "
                    f"below the input window, got {reserve!r} "
                    f"for window {window!r}")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
