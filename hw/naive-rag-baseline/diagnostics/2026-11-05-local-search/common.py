"""Shared, read-only helpers for the local-search diagnostics.

Nothing here calls a model, an embedding endpoint, Neo4j or Qdrant, and
nothing writes inside the project except `cache/` and `results/` of this
directory. Settings are built with ``_env_file=None`` so ``.env`` is never
opened; the defaults (chunk 500/75) are what the saved extraction used,
which `01_identity.py` checks through `input_hash`.
"""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

DIAG = Path(__file__).resolve().parent
PROJECT = DIAG.parents[1]
CACHE = DIAG / "cache"
RESULTS = DIAG / "results"
sys.path.insert(0, str(PROJECT / "src"))
sys.dont_write_bytecode = True

from naive_rag import config  # noqa: E402

SETTINGS = config.Settings(_env_file=None)
config.get_settings = lambda: SETTINGS

from naive_rag import ingest, loaders  # noqa: E402

loaders.get_settings = lambda: SETTINGS
ingest.get_settings = lambda: SETTINGS

from naive_rag.graph_merge import merged_graph  # noqa: E402
from naive_rag.quality_report import load_records  # noqa: E402

EXTRACTION_DIR = PROJECT / "graph" / "corpus" / "extraction"
INDEX_PATH = PROJECT / "graph" / "corpus" / "entity-index.json"
RUN_PATH = PROJECT / "docs" / "osszehasonlitas-run.json"
QUESTIONS_PATH = PROJECT / "questions.md"
CORPUS_DIR = PROJECT / "corpus"
SOURCE_FILES = (
    "config.py", "ingest.py", "loaders.py", "dependencies.py",
    "extract_pilot.py", "extraction_models.py", "extraction_identity.py",
    "graph_merge.py", "quality_report.py", "entity_index.py",
    "local_search.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_tree(directory: Path, pattern: str = "*") -> tuple[str, int]:
    """Digest of sorted (name, file digest) pairs, and the file count."""
    digest = hashlib.sha256()
    files = sorted(p for p in directory.glob(pattern) if p.is_file())
    for path in files:
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(sha256_file(path).encode("ascii") + b"\n")
    return digest.hexdigest(), len(files)


def pandoc_version() -> str:
    exe = shutil.which("pandoc")
    if not exe:
        return "not found"
    out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                         encoding="utf-8", check=False)
    return out.stdout.splitlines()[0] if out.stdout else "unknown"


def input_manifest() -> dict:
    from importlib.metadata import version

    corpus_digest, corpus_files = sha256_tree(CORPUS_DIR)
    extraction_digest, extraction_files = sha256_tree(EXTRACTION_DIR, "*.json")
    packages = {}
    for name in ("langchain-text-splitters", "langchain-community", "pypdf",
                 "markdownify", "beautifulsoup4", "openpyxl", "pydantic"):
        try:
            packages[name] = version(name)
        except Exception:  # noqa: BLE001
            packages[name] = "unknown"
    return {
        "project": str(PROJECT),
        "python": platform.python_version(),
        "pandoc": pandoc_version(),
        "packages": packages,
        "settings_used": {
            "env_file": None,
            "chunk_size": SETTINGS.chunk_size,
            "chunk_overlap": SETTINGS.chunk_overlap,
        },
        "inputs": {
            "corpus_dir": {"sha256_tree": corpus_digest, "files": corpus_files},
            "extraction_dir": {"sha256_tree": extraction_digest,
                               "files": extraction_files},
            "entity_index": {"path": str(INDEX_PATH.relative_to(PROJECT)),
                             "sha256": sha256_file(INDEX_PATH)},
            "saved_run": {"path": str(RUN_PATH.relative_to(PROJECT)),
                          "sha256": sha256_file(RUN_PATH)},
            "questions": {"path": str(QUESTIONS_PATH.relative_to(PROJECT)),
                          "sha256": sha256_file(QUESTIONS_PATH)},
            "source": {
                name: sha256_file(PROJECT / "src" / "naive_rag" / name)
                for name in SOURCE_FILES
            },
        },
    }


def _cache_key() -> str:
    corpus_digest, _ = sha256_tree(CORPUS_DIR)
    parts = [corpus_digest, pandoc_version(),
             str(SETTINGS.chunk_size), str(SETTINGS.chunk_overlap)]
    for name in ("ingest.py", "loaders.py"):
        parts.append(sha256_file(PROJECT / "src" / "naive_rag" / name))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def load_chunks() -> tuple[dict[str, str], dict[str, dict]]:
    """Chunk texts and metadata. Rebuilt when the corpus or loader changes."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "chunks.json"
    key = _cache_key()
    if path.is_file():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("key") == key:
            return cached["texts"], cached["meta"]
    _sources, chunks = ingest.load_and_chunk()
    texts = {c.metadata["chunk_id"]: c.page_content for c in chunks}
    meta = {
        c.metadata["chunk_id"]: {
            "doc_id": c.metadata.get("doc_id"),
            "section": c.metadata.get("section"),
        }
        for c in chunks
    }
    path.write_text(json.dumps({"key": key, "texts": texts, "meta": meta},
                               ensure_ascii=False), encoding="utf-8")
    return texts, meta


def records() -> list[dict]:
    return load_records(EXTRACTION_DIR)


def graph(recs: list[dict] | None = None):
    return merged_graph(recs if recs is not None else records())


def saved_run() -> list[dict]:
    return json.loads(RUN_PATH.read_text(encoding="utf-8"))


def question_of(record: dict) -> str:
    return record["prompt"].split("Kérdés: ", 1)[1].split("\n\nKontextus:", 1)[0]


def anchors_of(record: dict) -> tuple[tuple[str, float], ...]:
    return tuple((a["entity_key"], a["score"]) for a in record["anchors"])


def write_result(name: str, payload: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path
