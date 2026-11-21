"""Offline checks for the thin question -> router -> search dispatch
entry point (`naive_rag.answer_question`). No real API call."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from naive_rag import answer_question as aq


def _fake_response(content: str):
    return SimpleNamespace(
        content=content,
        response_metadata={"model_name": "gpt-4o-mini-test", "finish_reason": "stop",
                           "token_usage": {"prompt_tokens": 5, "completion_tokens": 5}},
        usage_metadata={},
    )


def _mode_fns(calls: list[str]) -> dict:
    def make(name):
        def fn(question_text):
            calls.append(name)
            return {"mode": name, "question": question_text}
        return fn
    return {name: make(name) for name in ("naiv", "lokalis", "globalis", "drift")}


class ExplicitModeTests(unittest.TestCase):
    def test_explicit_mode_bypasses_the_router_for_every_mode(self):
        for mode in ("naiv", "lokalis", "globalis", "drift"):
            calls: list[str] = []
            record = aq.answer_question(
                "Q01", "question text", mode_fns=_mode_fns(calls), mode=mode)
            self.assertEqual(record["mode"], mode)
            self.assertEqual(record["mode_source"], "explicit")
            self.assertEqual(calls, [mode])
            self.assertNotIn("route_record", record)

    def test_unregistered_explicit_mode_raises(self):
        with self.assertRaises(ValueError):
            aq.answer_question("Q01", "q?", mode_fns={}, mode="drift")


class RouterDispatchTests(unittest.TestCase):
    def test_router_decision_actually_invokes_the_chosen_branch(self):
        calls: list[str] = []

        def raw_caller(messages, params):
            return _fake_response(json.dumps({"mode": "drift", "reasoning": "global summary plus one local hop"}))

        record = aq.answer_question(
            "Q09", "Across all drivers, who tied on titles?",
            mode_fns=_mode_fns(calls), raw_caller=raw_caller)
        self.assertEqual(record["mode"], "drift")
        self.assertEqual(record["mode_source"], "router")
        self.assertEqual(calls, ["drift"])
        self.assertEqual(record["result"]["mode"], "drift")

    def test_the_three_pre_existing_branches_still_work_through_the_router(self):
        for mode in ("naiv", "lokalis", "globalis"):
            calls: list[str] = []

            def raw_caller(messages, params, mode=mode):
                return _fake_response(json.dumps({"mode": mode, "reasoning": "x"}))

            record = aq.answer_question(
                "Q01", "question text", mode_fns=_mode_fns(calls), raw_caller=raw_caller)
            self.assertEqual(record["mode"], mode)
            self.assertEqual(calls, [mode])

    def test_router_mode_without_a_registered_search_function_does_not_crash(self):
        def raw_caller(messages, params):
            return _fake_response(json.dumps({"mode": "drift", "reasoning": "x"}))

        record = aq.answer_question(
            "Q01", "q?", mode_fns={"naiv": lambda q: "n/a"}, raw_caller=raw_caller)
        self.assertIsNone(record["result"])
        self.assertIn("error", record)

    def test_missing_raw_caller_without_explicit_mode_raises(self):
        with self.assertRaises(ValueError):
            aq.answer_question("Q01", "q?", mode_fns={})


if __name__ == "__main__":
    unittest.main()
