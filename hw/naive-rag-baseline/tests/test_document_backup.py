"""Document-layer backup uses the existing merge and sweep statements."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from naive_rag.graph_ingest import (
    _MERGE_CHUNKS,
    _MERGE_CORPUS,
    _MERGE_DOCUMENTS,
    _MERGE_NEXT,
    _MERGE_SECTIONS,
    _SWEEP,
    DocumentLayerRejected,
    restore_document_backup,
    save_document_backup,
)


def _corpus_row():
    return {
        "name": "f1-wikipedia",
        "run_id": "20261017T081038Z",
        "chunk_size": 500,
        "chunk_overlap": 75,
    }


def _reader(cypher, **params):
    if "RETURN c.name" in cypher:
        return [_corpus_row()]
    if "properties(d)" in cypher:
        return [{"properties": {
            "doc_id": "driver-lewis-hamilton",
            "title": "Lewis Hamilton",
            "run_id": "20261017T081038Z",
        }}]
    if "properties(s)" in cypher:
        return [{"properties": {
            "section_id": "driver-lewis-hamilton::Career",
            "doc_id": "driver-lewis-hamilton",
            "path": "Career",
            "title": "Career",
            "run_id": "20261017T081038Z",
        }}]
    if "properties(c)" in cypher:
        return [{"properties": {
            "chunk_id": "driver-lewis-hamilton#0",
            "doc_id": "driver-lewis-hamilton",
            "section": "Career",
            "text": "old chunk text",
            "ordinal": 0,
            "run_id": "20261017T081038Z",
        }}]
    if "NEXT_CHUNK" in cypher:
        return []
    raise AssertionError(cypher)


class DocumentBackupTests(unittest.TestCase):
    def test_save_and_restore_use_existing_statements(self):
        calls = []

        def writer(cypher, **params):
            calls.append((cypher, params))
            return []

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "document-layer.json"
            saved = save_document_backup(
                path, corpus_name="f1-wikipedia", query_fn=_reader)
            self.assertEqual(saved["chunks"][0]["text"], "old chunk text")
            self.assertNotIn("Seed", path.read_text(encoding="utf-8"))
            self.assertNotIn("Extracted", path.read_text(encoding="utf-8"))
            with self.assertRaises(DocumentLayerRejected):
                save_document_backup(
                    path, corpus_name="f1-wikipedia", query_fn=_reader)
            restore_document_backup(
                path, corpus_name="f1-wikipedia", query_fn=writer)

        self.assertEqual(
            [call[0] for call in calls],
            [_MERGE_CORPUS, _MERGE_DOCUMENTS, _MERGE_SECTIONS,
             _MERGE_CHUNKS, _MERGE_NEXT, _SWEEP],
        )
        chunk_call = calls[3][1]
        self.assertEqual(chunk_call["rows"][0]["text"], "old chunk text")
        self.assertEqual(chunk_call["run_id"], "20261017T081038Z")
        self.assertEqual(calls[-1][1]["run_id"], "20261017T081038Z")
        self.assertNotIn(":Seed", _SWEEP)
        self.assertNotIn(":Extracted", _SWEEP)
        self.assertEqual(saved["documents"][0]["doc_id"], "driver-lewis-hamilton")

    def test_restore_rejects_a_chunk_without_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text(json.dumps({
                "format": "document-layer-backup-1",
                "name": "f1-wikipedia",
                "run_id": "run",
                "chunk_size": 500,
                "chunk_overlap": 75,
                "documents": [{"doc_id": "doc"}],
                "sections": [],
                "chunks": [{"chunk_id": "doc#0", "doc_id": "doc"}],
                "next_chunk": [],
            }), encoding="utf-8")
            with self.assertRaises(DocumentLayerRejected):
                restore_document_backup(
                    path, corpus_name="f1-wikipedia", query_fn=lambda *a, **k: [])


if __name__ == "__main__":
    unittest.main()
