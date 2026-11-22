"""Build the measured naive Qdrant collection. Does not touch f1_naive_rag.

Calls ``run_phase5.index_naive_baseline``. An existing target collection
is left unchanged unless ``--overwrite`` is passed. This script does not
print credential values.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import run_phase5  # noqa: E402

DEFAULT_CHUNKS = ROOT / "graph" / "corpus" / "chunks-section-1200-23" / "chunks.jsonl"
DEFAULT_COLLECTION = "week4_naive_baseline_1200_23"
FROZEN_CHUNK_COUNT = 1651
# SHA-256 of the file after newlines are normalized to LF.
# The historical Windows CRLF raw hash is
# 79d46d6291bc07924ddc13703f9b4804f8cf9c86de9de3ebaf435248f04e012e.
FROZEN_CHUNKS_SHA256 = "7ea361e60c2a9c06e2628f7d008d25c35ebb58ebcbebc31902ab2380dbebee27"
EXPECTED_MODEL = "text-embedding-3-small"


class BuildStop(RuntimeError):
    """The build did not start. No embedding call was made."""


def normalized_chunk_bytes(raw: bytes) -> bytes:
    """LF bytes. CRLF and CR-only newlines compare as the same corpus."""
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def check_chunks(path: Path) -> None:
    if not path.is_file():
        raise BuildStop(f"chunks file not found: {path}")
    normalized = normalized_chunk_bytes(path.read_bytes())
    rows = [line for line in normalized.decode("utf-8").splitlines() if line.strip()]
    digest = hashlib.sha256(normalized).hexdigest()
    if len(rows) != FROZEN_CHUNK_COUNT or digest != FROZEN_CHUNKS_SHA256:
        raise BuildStop(
            f"chunks are not the frozen 1651-line file "
            f"(count={len(rows)}, sha256={digest})")


def check_model(model: str) -> None:
    if model != EXPECTED_MODEL or run_phase5.EMBEDDING_MODEL != EXPECTED_MODEL:
        raise BuildStop(
            f"embedding model must be {EXPECTED_MODEL}; "
            f"indexer uses {run_phase5.EMBEDDING_MODEL}")


def check_api_key() -> None:
    from naive_rag.config import get_settings

    key = get_settings().openai_api_key
    if not str(key or "").strip():
        raise BuildStop("OPENAI_API_KEY is not configured")


def build(args: argparse.Namespace, *, client_factory=None, index_fn=None) -> dict:
    chunks = Path(args.chunks)
    check_chunks(chunks)
    check_model(args.embedding_model)
    check_api_key()
    if args.collection == "f1_naive_rag":
        raise BuildStop("refusing to build the f1_naive_rag collection")
    factory = client_factory
    if factory is None:
        from qdrant_client import QdrantClient

        def factory():
            if args.qdrant_path:
                Path(args.qdrant_path).mkdir(parents=True, exist_ok=True)
                return QdrantClient(path=str(args.qdrant_path))
            from naive_rag.vectorstore import _client
            return _client()

    client = factory()
    try:
        exists = client.collection_exists(args.collection)
        if exists and not args.overwrite:
            raise BuildStop(
                f"{args.collection} already exists -- refusing to overwrite")
        if exists and args.overwrite:
            client.delete_collection(args.collection)
    finally:
        client.close()
    indexer = index_fn or run_phase5.index_naive_baseline
    budget = run_phase5.Budget()
    ledger_path = Path(args.ledger)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger = run_phase5.Ledger(run_id="week4-collection-build", path=ledger_path)
    storage = factory() if args.qdrant_path else None
    return indexer(
        budget, ledger, chunks_path=chunks, collection=args.collection, client=storage)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python build_week4_collection.py",
        description=(
            "Build the measured naive collection "
            "week4_naive_baseline_1200_23 from the frozen 1651-chunk jsonl. "
            "Uses run_phase5.index_naive_baseline. Does not use f1_naive_rag. "
            "An existing collection is not overwritten unless --overwrite is set."
        ),
    )
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--qdrant-path", type=Path, default=None,
                        help="local Qdrant directory; default is the project .qdrant")
    parser.add_argument("--embedding-model", default=EXPECTED_MODEL)
    parser.add_argument("--overwrite", action="store_true",
                        help="delete the target collection first; default is STOP")
    parser.add_argument(
        "--ledger", type=Path,
        default=HERE / "results" / "week4-collection-build-ledger.json")
    args = parser.parse_args(argv)
    try:
        result = build(args)
    except BuildStop as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2
    print(f"collection: {result['collection']}")
    print(f"points: {result['points_indexed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
