import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import golden_set as gs

ROW = {
    "id": "X01", "type": "simple", "status": "frozen_w4", "question": "Q?",
    "expected_answer": "A.",
    "criteria": [{"id": "X01-c1", "text": "t", "expected_content": ["a"], "required": True},
                {"id": "X01-c2", "text": "t2", "expected_content": ["b"], "required": False}],
    "evidence_groups": [
        {"id": "X01-e1", "criterion": "X01-c1", "any_of_chunk_ids": ["doc-a#0"]},
        {"id": "X01-e2", "criterion": "X01-c2", "any_of_chunk_ids": ["doc-a#1"]},
        {"id": "X01-bridge", "criterion": None, "role": "retrieval_bridge", "any_of_chunk_ids": ["doc-b#0"]},
    ],
    "gold_docs": ["doc-a"], "notes": "n", "golden_set_version": "test",
    "corpus": {"chunks_file": "graph/corpus/x/chunks.jsonl", "chunks_sha256": "abc", "chunk_count": 2},
}


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


class GoldenSetTests(unittest.TestCase):
    def test_load_and_required_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.jsonl"
            _write(path, [ROW])
            qs = gs.load_golden_set(path)
            self.assertEqual(len(qs), 1)
            q = qs[0]
            self.assertEqual(len(q.required_criteria()), 1)
            self.assertEqual(len(q.optional_criteria()), 1)
            required_groups = q.required_evidence_groups()
            ids = {g.id for g in required_groups}
            self.assertIn("X01-e1", ids)
            self.assertIn("X01-bridge", ids)
            self.assertNotIn("X01-e2", ids)  # tied to the optional criterion

    def test_missing_corpus_fields_rejected(self) -> None:
        bad = dict(ROW)
        bad["corpus"] = {"chunks_file": "x", "chunks_sha256": None, "chunk_count": 1}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.jsonl"
            _write(path, [bad])
            with self.assertRaises(gs.GoldenSetError):
                gs.load_golden_set(path)

    def test_duplicate_ids_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.jsonl"
            _write(path, [ROW, ROW])
            with self.assertRaises(gs.GoldenSetError):
                gs.load_golden_set(path)

    def test_mixed_corpus_snapshot_rejected(self) -> None:
        other = json.loads(json.dumps(ROW))
        other["id"] = "X02"
        other["corpus"]["chunks_sha256"] = "different"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.jsonl"
            _write(path, [ROW, other])
            qs = gs.load_golden_set(path)
            with self.assertRaises(gs.GoldenSetError):
                gs.verify_single_corpus_snapshot(qs)

    def test_corpus_hash_mismatch_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            chunks = tmp_path / "chunks.jsonl"
            chunks.write_text("different content\n", encoding="utf-8")
            with self.assertRaises(gs.GoldenSetError):
                gs.verify_corpus_matches_disk("abc", chunks)

    def test_golden_set_sha256_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.jsonl"
            _write(path, [ROW])
            first = gs.golden_set_sha256(path)
            second = gs.golden_set_sha256(path)
            self.assertEqual(first, second)
            self.assertEqual(len(first), 64)

    def test_by_status(self) -> None:
        held = json.loads(json.dumps(ROW))
        held["id"] = "X02"
        held["status"] = "held_out"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.jsonl"
            _write(path, [ROW, held])
            qs = gs.load_golden_set(path)
            self.assertEqual(len(gs.by_status(qs, "frozen_w4")), 1)
            self.assertEqual(len(gs.by_status(qs, "held_out")), 1)


if __name__ == "__main__":
    unittest.main()
