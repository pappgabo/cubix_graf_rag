import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import golden_set as gs
import retrieval_eval as re_


ROW = {
    "id": "X01", "type": "multi-hop", "status": "frozen_w4", "question": "Q?",
    "expected_answer": "A.",
    "criteria": [
        {"id": "X01-c1", "text": "t1", "expected_content": ["a"], "required": True},
        {"id": "X01-c2", "text": "t2", "expected_content": ["b"], "required": True},
        {"id": "X01-c3", "text": "t3 optional", "expected_content": ["c"], "required": False},
    ],
    "evidence_groups": [
        {"id": "X01-e1", "criterion": "X01-c1", "any_of_chunk_ids": ["doc-a#0", "doc-a#1"]},
        {"id": "X01-e2", "criterion": "X01-c2", "any_of_chunk_ids": ["doc-b#0"]},
        {"id": "X01-e3", "criterion": "X01-c3", "any_of_chunk_ids": ["doc-c#0"]},
        {"id": "X01-bridge", "criterion": None, "role": "retrieval_bridge", "any_of_chunk_ids": ["doc-d#0"]},
    ],
    "gold_docs": ["doc-a"], "notes": "n", "golden_set_version": "test",
    "corpus": {"chunks_file": "x", "chunks_sha256": "abc", "chunk_count": 2},
}


def _question() -> gs.GoldenQuestion:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "g.jsonl"
        path.write_text(json.dumps(ROW) + "\n", encoding="utf-8")
        return gs.load_golden_set(path)[0]


class RetrievalEvalTests(unittest.TestCase):
    def test_required_denominator_excludes_optional_group(self) -> None:
        q = _question()
        result = re_.evaluate_retrieval(q, frozenset())
        # 3 required groups: e1, e2, bridge -- e3 (optional) excluded
        self.assertEqual(result.group_count, 3)

    def test_any_of_within_group_is_sufficient(self) -> None:
        q = _question()
        result = re_.evaluate_retrieval(q, frozenset({"doc-a#1"}))  # only one of the two alternatives
        group_e1 = next(g for g in result.groups if g.group_id == "X01-e1")
        self.assertTrue(group_e1.hit)
        self.assertEqual(result.hit_count, 1)

    def test_and_between_required_groups(self) -> None:
        q = _question()
        # only e1 covered -> not strict_all, ratio < 1
        result = re_.evaluate_retrieval(q, frozenset({"doc-a#0"}))
        self.assertFalse(result.strict_all_hit)
        self.assertAlmostEqual(result.ratio, 1 / 3)

    def test_bridge_group_counts_toward_denominator(self) -> None:
        q = _question()
        result = re_.evaluate_retrieval(q, frozenset({"doc-a#0", "doc-b#0", "doc-d#0"}))
        self.assertTrue(result.strict_all_hit)
        self.assertEqual(result.ratio, 1.0)

    def test_missing_chunk_ids_is_untraceable_not_zero(self) -> None:
        q = _question()
        result = re_.evaluate_retrieval(q, None, untraceable_reason="naiv context had no chunk_id")
        self.assertEqual(result.status, "untraceable")
        self.assertIsNone(result.ratio)
        self.assertIsNone(result.hit_count)

    def test_proxy_flag_is_recorded(self) -> None:
        q = _question()
        result = re_.evaluate_retrieval(
            q, frozenset({"doc-a#0", "doc-b#0", "doc-d#0"}), is_proxy=True, proxy_note="reduce basis proxy")
        self.assertTrue(result.is_proxy)
        self.assertEqual(result.proxy_note, "reduce basis proxy")

    def test_result_to_dict_round_trips_key_fields(self) -> None:
        q = _question()
        result = re_.evaluate_retrieval(q, frozenset({"doc-a#0"}))
        payload = re_.result_to_dict(result)
        self.assertEqual(payload["question_id"], "X01")
        self.assertEqual(payload["group_count"], 3)
        self.assertIsInstance(payload["groups"], list)


if __name__ == "__main__":
    unittest.main()
