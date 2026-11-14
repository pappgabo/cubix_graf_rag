import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import correctness_judge as cj
import golden_set as gs

ROW = {
    "id": "X01", "type": "simple", "status": "frozen_w4", "question": "Q?",
    "expected_answer": "A.",
    "criteria": [
        {"id": "X01-c1", "text": "t1", "expected_content": ["a"], "required": True},
        {"id": "X01-c2", "text": "t2 optional", "expected_content": ["b"], "required": False},
    ],
    "evidence_groups": [{"id": "X01-e1", "criterion": "X01-c1", "any_of_chunk_ids": ["doc-a#0"]}],
    "gold_docs": ["doc-a"], "notes": "n", "golden_set_version": "test",
    "corpus": {"chunks_file": "x", "chunks_sha256": "abc", "chunk_count": 2},
}


def _question() -> gs.GoldenQuestion:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "g.jsonl"
        path.write_text(json.dumps(ROW) + "\n", encoding="utf-8")
        return gs.load_golden_set(path)[0]


@dataclass(frozen=True)
class FakeResponse:
    content: str
    returned_model: str = "gpt-4o-mini-fake"
    usage_prompt_tokens: Any = 10
    usage_completion_tokens: Any = 5
    finish_reason: str = "stop"


def _fake_call(payload: dict) -> cj.ModelCall:
    def call(system: str, user: str, max_tokens: int) -> FakeResponse:
        return FakeResponse(content=json.dumps(payload))
    return call


def _full_judgement(**overrides) -> dict:
    base = {
        "criteria": [
            {"criterion_id": "X01-c1", "verdict": "met", "explanation": "ok"},
            {"criterion_id": "X01-c2", "verdict": "not_met", "explanation": "ok"},
        ],
        "refused": False, "rubric_conflicts": [], "reasoning": "ok",
    }
    base.update(overrides)
    return base


class ValidationTests(unittest.TestCase):
    def test_unknown_criterion_id_rejected(self) -> None:
        q = _question()
        parsed = _full_judgement(criteria=[{"criterion_id": "nope", "verdict": "met", "explanation": "x"}])
        result = cj.validate_judge_response(parsed, q)
        self.assertFalse(result.valid_structure)

    def test_missing_criterion_rejected(self) -> None:
        q = _question()
        parsed = _full_judgement(criteria=[{"criterion_id": "X01-c1", "verdict": "met", "explanation": "x"}])
        result = cj.validate_judge_response(parsed, q)
        self.assertFalse(result.valid_structure)

    def test_valid_response_accepted(self) -> None:
        q = _question()
        result = cj.validate_judge_response(_full_judgement(), q)
        self.assertTrue(result.valid_structure)


class LabelingTests(unittest.TestCase):
    def test_all_required_met_is_helyes(self) -> None:
        q = _question()
        label = cj.label_from_judgement(_full_judgement(), q)
        self.assertEqual(label, "helyes")

    def test_required_not_met_is_hianyos(self) -> None:
        q = _question()
        parsed = _full_judgement(criteria=[
            {"criterion_id": "X01-c1", "verdict": "not_met", "explanation": "x"},
            {"criterion_id": "X01-c2", "verdict": "not_met", "explanation": "x"},
        ])
        self.assertEqual(cj.label_from_judgement(parsed, q), "hiányos")

    def test_partial_answer_is_not_elutasitott(self) -> None:
        q = _question()
        parsed = _full_judgement(criteria=[
            {"criterion_id": "X01-c1", "verdict": "not_met", "explanation": "x"},
            {"criterion_id": "X01-c2", "verdict": "met", "explanation": "x"},
        ], refused=False)
        self.assertEqual(cj.label_from_judgement(parsed, q), "hiányos")

    def test_full_refusal_is_elutasitott(self) -> None:
        q = _question()
        parsed = _full_judgement(refused=True, criteria=[
            {"criterion_id": "X01-c1", "verdict": "not_met", "explanation": "x"},
            {"criterion_id": "X01-c2", "verdict": "not_met", "explanation": "x"},
        ])
        self.assertEqual(cj.label_from_judgement(parsed, q), "elutasított")

    def test_rubric_conflict_is_tevess_even_if_refused(self) -> None:
        q = _question()
        parsed = _full_judgement(refused=True, rubric_conflicts=["reversed identity"])
        self.assertEqual(cj.label_from_judgement(parsed, q), "téves")


class JudgeOneTests(unittest.TestCase):
    def test_technical_error_is_not_mapped_to_hianyos(self) -> None:
        q = _question()

        def failing_call(system, user, max_tokens):
            raise RuntimeError("network down")

        record = cj.judge_one(q, "some answer", failing_call)
        self.assertEqual(record["status"], "error")
        self.assertNotIn("label", record)

    def test_invalid_json_is_error_not_hianyos(self) -> None:
        q = _question()

        def bad_json_call(system, user, max_tokens):
            return FakeResponse(content="not json")

        record = cj.judge_one(q, "some answer", bad_json_call)
        self.assertEqual(record["status"], "error")

    def test_valid_response_produces_label(self) -> None:
        q = _question()
        call = _fake_call(_full_judgement())
        record = cj.judge_one(q, "some answer", call)
        self.assertEqual(record["status"], "scored")
        self.assertEqual(record["label"], "helyes")

    def test_finish_reason_length_is_error(self) -> None:
        q = _question()

        def truncated_call(system, user, max_tokens):
            return FakeResponse(content=json.dumps(_full_judgement()), finish_reason="length")

        record = cj.judge_one(q, "some answer", truncated_call)
        self.assertEqual(record["status"], "error")


if __name__ == "__main__":
    unittest.main()
