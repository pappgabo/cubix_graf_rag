"""Offline provenance counts for a tiny extracted-layer backup."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from naive_rag.config import PROJECT_ROOT


def _checker():
    import importlib.util
    path = PROJECT_ROOT / "scripts" / "check_extracted_provenance.py"
    spec = importlib.util.spec_from_file_location("check_extracted_provenance", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.check


def _edge(rel_type: str, *, chunks: list[str] | None = None,
          mention: str | None = None) -> dict:
    if mention is not None:
        return {
            "type": "MENTIONS",
            "properties": {},
            "source": {"kind": "chunk", "chunk_id": mention},
            "target": {"kind": "extracted", "label": "Driver", "entity_key": "Driver:a"},
        }
    return {
        "type": rel_type,
        "properties": {"source_chunk_ids": chunks or []},
        "source": {"kind": "extracted", "label": "Driver", "entity_key": "Driver:a"},
        "target": {"kind": "extracted", "label": "Team", "entity_key": "Team:b"},
    }


class ExtractedProvenanceTest(unittest.TestCase):
    def test_counts_resolved_and_missing_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            backup = root / "backup.json"
            chunks = root / "chunks.jsonl"
            backup.write_text(json.dumps({
                "format": "extracted-layer-backup-1",
                "nodes": [],
                "edges": [
                    _edge("WON", chunks=["doc#1"]),
                    _edge("DROVE_FOR", chunks=[]),
                    _edge("MENTIONS", mention="doc#1"),
                    _edge("WON", chunks=["missing#9"]),
                ],
            }), encoding="utf-8")
            chunks.write_text(
                json.dumps({"chunk_id": "doc#1", "doc_id": "doc"}) + "\n",
                encoding="utf-8",
            )
            result = _checker()(backup, chunks)
        self.assertEqual(result["edges_checked"], 4)
        self.assertEqual(result["edges_with_provenance"], 3)
        self.assertEqual(result["edges_missing_provenance"], 1)
        self.assertEqual(result["source_chunk_refs"], 3)
        self.assertEqual(result["resolved_source_chunk_refs"], 2)
        self.assertEqual(result["missing_source_chunk_refs"], 1)


if __name__ == "__main__":
    unittest.main()
