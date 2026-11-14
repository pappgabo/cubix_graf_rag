import json
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import faithfulness_judge as fj


@dataclass(frozen=True)
class FakeResponse:
    content: str
    returned_model: str = "gpt-4o-mini-fake"
    usage_prompt_tokens: Any = 10
    usage_completion_tokens: Any = 5
    finish_reason: str = "stop"


class ScoringTests(unittest.TestCase):
    def test_score_is_ratio_of_supported(self) -> None:
        parsed = {"claims": [
            {"claim": "a", "verdict": "supported"},
            {"claim": "b", "verdict": "supported"},
            {"claim": "c", "verdict": "unsupported"},
        ], "reasoning": "x"}
        scoring = fj.score_from_judgement(parsed)
        self.assertAlmostEqual(scoring["score"], 2 / 3)
        self.assertEqual(scoring["supported_count"], 2)
        self.assertEqual(scoring["unsupported_count"], 1)

    def test_unclear_counts_as_not_supported_but_recorded(self) -> None:
        parsed = {"claims": [
            {"claim": "a", "verdict": "supported"},
            {"claim": "b", "verdict": "unclear"},
        ], "reasoning": "x"}
        scoring = fj.score_from_judgement(parsed)
        self.assertEqual(scoring["score"], 0.5)
        self.assertEqual(scoring["unclear_count"], 1)

    def test_no_claims_is_n_a_not_zero_or_one(self) -> None:
        parsed = {"claims": [], "reasoning": "refusal"}
        scoring = fj.score_from_judgement(parsed)
        self.assertEqual(scoring["score"], "n/a")
        self.assertEqual(scoring["scored_count"], 0)


class ValidationTests(unittest.TestCase):
    def test_invalid_verdict_rejected(self) -> None:
        parsed = {"claims": [{"claim": "a", "verdict": "maybe"}], "reasoning": "x"}
        result = fj.validate_judge_response(parsed)
        self.assertFalse(result.valid_structure)

    def test_valid_response_accepted(self) -> None:
        parsed = {"claims": [{"claim": "a", "verdict": "supported"}], "reasoning": "x"}
        result = fj.validate_judge_response(parsed)
        self.assertTrue(result.valid_structure)


class JudgeOneTests(unittest.TestCase):
    def test_technical_error_is_distinct_status(self) -> None:
        def failing_call(system, user, max_tokens):
            raise RuntimeError("down")

        record = fj.judge_one("Q01", "question", "answer", "context", failing_call)
        self.assertEqual(record["status"], "error")

    def test_valid_response_scored(self) -> None:
        def call(system, user, max_tokens):
            return FakeResponse(content=json.dumps(
                {"claims": [{"claim": "a", "verdict": "supported"}], "reasoning": "x"}))

        record = fj.judge_one("Q01", "question", "answer", "context", call)
        self.assertEqual(record["status"], "scored")
        self.assertEqual(record["scoring"]["score"], 1.0)

    def test_context_is_the_literal_passed_context(self) -> None:
        captured = {}

        def call(system, user, max_tokens):
            captured["user"] = user
            return FakeResponse(content=json.dumps({"claims": [], "reasoning": "x"}))

        fj.judge_one("Q01", "question", "answer", "LITERAL CONTEXT TEXT", call)
        self.assertIn("LITERAL CONTEXT TEXT", captured["user"])


if __name__ == "__main__":
    unittest.main()
