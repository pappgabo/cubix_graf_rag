"""Database-free, model-free checks for the zero-shot LLM router. No real
API call anywhere in this file."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from naive_rag import router_eval, search_router as sr


def _fake_response(content, finish_reason="stop"):
    return SimpleNamespace(
        content=content,
        response_metadata={"model_name": "gpt-4o-mini-test", "finish_reason": finish_reason,
                           "token_usage": {"prompt_tokens": 20, "completion_tokens": 10}},
        usage_metadata={},
    )


class MessageContentTests(unittest.TestCase):
    def test_only_the_question_text_is_question_specific(self):
        messages = sr.router_messages("Who won the 2021 championship?")
        self.assertEqual(messages[-1], {"role": "user", "content": "Who won the 2021 championship?"})
        joined = " ".join(m["content"] for m in messages)
        for forbidden in ("Q01", "Q09", "simple", "multi-hop"):
            self.assertNotIn(forbidden, joined)
        # "globalis" (a mode name) legitimately contains "global" as a
        # substring; check the actual questions.md type LABEL as a whole
        # word instead, which the router must never see.
        import re
        self.assertNotRegex(joined, r"\bglobal\b")

    def test_system_prompt_has_no_few_shot_examples_or_tailored_keywords(self):
        # None of the repo's actual Q01-Q13 question texts appear verbatim
        # in the router's system prompt.
        questions_path = Path(__file__).resolve().parents[1] / "questions.md"
        text = questions_path.read_text(encoding="utf-8")
        import re
        for match in re.finditer(r"\*\*Kérdés:\*\* (.+)", text):
            question_text = match.group(1).strip()
            self.assertNotIn(question_text, sr.ROUTER_SYSTEM_PROMPT)


class ValidationTests(unittest.TestCase):
    def test_valid_response(self):
        v = sr.validate_router_response({"mode": "lokalis", "reasoning": "names two entities"})
        self.assertTrue(v.valid_structure)

    def test_invalid_mode_rejected(self):
        v = sr.validate_router_response({"mode": "hybrid", "reasoning": "x"})
        self.assertFalse(v.valid_structure)

    def test_missing_reasoning_rejected(self):
        v = sr.validate_router_response({"mode": "naiv", "reasoning": ""})
        self.assertFalse(v.valid_structure)

    def test_drift_mode_is_valid(self):
        v = sr.validate_router_response({"mode": "drift", "reasoning": "global summary plus one local hop"})
        self.assertTrue(v.valid_structure)


class RouteOneTests(unittest.TestCase):
    def test_successful_route_records_mode_and_logs_exact_messages(self):
        seen = []

        def raw_caller(messages, params):
            seen.append(messages)
            return _fake_response(json.dumps({"mode": "globalis", "reasoning": "corpus-wide aggregation"}))

        record = sr.route_one("Q09", "Across all drivers, who won the most titles?", raw_caller)
        self.assertEqual(record["mode"], "globalis")
        self.assertNotIn("error", record)
        # the question_id lives only in the record / local_metadata, never in what was sent
        self.assertNotIn("Q09", json.dumps(seen))

    def test_invalid_json_is_reported_not_raised(self):
        def raw_caller(messages, params):
            return _fake_response("not json")

        record = sr.route_one("Q01", "q?", raw_caller)
        self.assertFalse(record["valid_json"])
        self.assertNotIn("mode", record)

    def test_api_error_is_reported_not_raised(self):
        def raw_caller(messages, params):
            raise RuntimeError("simulated failure")

        record = sr.route_one("Q01", "q?", raw_caller)
        self.assertIn("simulated failure", record["error"])


class RouteManyAndLoggingTests(unittest.TestCase):
    def test_route_many_writes_one_log_per_question(self):
        import tempfile

        def raw_caller(messages, params):
            return _fake_response(json.dumps({"mode": "naiv", "reasoning": "single fact"}))

        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            records = sr.route_many([("Q01", "q1?"), ("Q02", "q2?")], raw_caller, log_dir=log_dir)
            self.assertEqual(len(records), 2)
            for qid in ("Q01", "Q02"):
                self.assertTrue((log_dir / f"router-log-{qid}.json").exists())
                saved = json.loads((log_dir / f"router-log-{qid}.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["local_metadata"], {"question_id": qid})


class RouterEvalTests(unittest.TestCase):
    def test_task_type_mapping(self):
        self.assertEqual(router_eval.TASK_TYPE_TO_MODE,
                         {"simple": "naiv", "multi-hop": "lokalis", "global": "globalis"})

    def test_compare_matches_and_mismatches(self):
        c1 = router_eval.compare_to_mapping("Q01", "simple", "naiv")
        c2 = router_eval.compare_to_mapping("Q04", "multi-hop", "globalis")
        self.assertTrue(c1.matches_mapping)
        self.assertFalse(c2.matches_mapping)
        self.assertEqual(router_eval.mismatches([c1, c2]), [c2])

    def test_unknown_outcome_is_not_counted_as_a_mismatch(self):
        c = router_eval.compare_to_mapping("Q05", "multi-hop", None)
        self.assertIsNone(c.matches_mapping)
        self.assertEqual(router_eval.mismatches([c]), [])


if __name__ == "__main__":
    unittest.main()
