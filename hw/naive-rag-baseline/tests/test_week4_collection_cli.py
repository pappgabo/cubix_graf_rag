"""Offline checks for the measured-collection build CLI. No Qdrant or API."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1] / "diagnostics" / "2026-11-10-phase5-run"
sys.path.insert(0, str(HERE))

import build_week4_collection as build_cli  # noqa: E402
import run_phase5  # noqa: E402


def _args(folder: Path, **extra):
    values = {
        "chunks": folder / "chunks.jsonl",
        "collection": build_cli.DEFAULT_COLLECTION,
        "qdrant_path": None,
        "embedding_model": build_cli.EXPECTED_MODEL,
        "overwrite": False,
        "ledger": folder / "ledger.json",
    }
    values.update(extra)
    return SimpleNamespace(**values)


def _write_frozen(folder: Path, body: bytes) -> None:
    (folder / "chunks.jsonl").write_bytes(body)


class Week4CollectionCliTest(unittest.TestCase):
    def test_missing_input_stops_before_index(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            called = []
            with self.assertRaises(build_cli.BuildStop):
                build_cli.build(
                    _args(Path(folder)),
                    index_fn=lambda *args, **kwargs: called.append(kwargs),
                )
        self.assertEqual(called, [])

    def test_existing_collection_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = b'{"chunk_id":"a#0","text":"a"}\n'
            _write_frozen(root, raw)
            called = []

            class Client:
                def collection_exists(self, name):
                    return True

                def delete_collection(self, name):
                    raise AssertionError("delete")

                def close(self):
                    return None

            with patch.object(build_cli, "FROZEN_CHUNK_COUNT", 1), \
                    patch.object(build_cli, "FROZEN_CHUNKS_SHA256", hashlib.sha256(raw).hexdigest()), \
                    patch("build_week4_collection.check_api_key", return_value=None):
                with self.assertRaises(build_cli.BuildStop) as caught:
                    build_cli.build(
                        _args(root),
                        client_factory=Client,
                        index_fn=lambda *args, **kwargs: called.append(kwargs),
                    )
        self.assertIn("refusing to overwrite", str(caught.exception))
        self.assertEqual(called, [])

    def test_passes_frozen_chunks_and_measured_collection(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = b'{"chunk_id":"a#0","text":"alpha"}\n'
            _write_frozen(root, raw)
            seen = {}

            class Client:
                def collection_exists(self, name):
                    return False

                def close(self):
                    return None

            def index_fn(budget, ledger, *, chunks_path, collection, client):
                seen["chunks"] = chunks_path.read_bytes()
                seen["collection"] = collection
                seen["model"] = run_phase5.EMBEDDING_MODEL
                return {"collection": collection, "points_indexed": 1}

            with patch.object(build_cli, "FROZEN_CHUNK_COUNT", 1), \
                    patch.object(build_cli, "FROZEN_CHUNKS_SHA256", hashlib.sha256(raw).hexdigest()), \
                    patch("build_week4_collection.check_api_key", return_value=None):
                result = build_cli.build(
                    _args(root), client_factory=Client, index_fn=index_fn)
        self.assertEqual(seen["chunks"], raw)
        self.assertEqual(seen["collection"], "week4_naive_baseline_1200_23")
        self.assertEqual(seen["model"], "text-embedding-3-small")
        self.assertEqual(result["collection"], "week4_naive_baseline_1200_23")

    def test_indexer_uses_given_chunks_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "chunks.jsonl"
            path.write_text(json.dumps({"chunk_id": "a#0", "text": "alpha"}) + "\n", encoding="utf-8")
            created = {}

            class Client:
                def create_collection(self, name, vectors_config):
                    created["name"] = name
                    created["size"] = vectors_config.size

                def upsert(self, name, points):
                    created["texts"] = [point.payload["text"] for point in points]

                def count(self, name, exact):
                    return SimpleNamespace(count=1)

                def close(self):
                    return None

            def embed(texts, ids, budget, ledger, *, label, openai_client=None):
                created["embed_label"] = label
                return [[0.0] * run_phase5.EMBEDDING_DIMENSIONS]

            ledger = run_phase5.Ledger("test", Path(folder) / "ledger.json")
            with patch.object(run_phase5, "embed_texts", embed):
                result = run_phase5.index_naive_baseline(
                    run_phase5.Budget(), ledger,
                    chunks_path=path, collection="week4_naive_baseline_1200_23",
                    client=Client())
        self.assertEqual(created["name"], "week4_naive_baseline_1200_23")
        self.assertEqual(created["size"], 1536)
        self.assertEqual(created["texts"], ["alpha"])
        self.assertEqual(result["points_indexed"], 1)
        self.assertNotIn("openai", created)


if __name__ == "__main__":
    unittest.main()
