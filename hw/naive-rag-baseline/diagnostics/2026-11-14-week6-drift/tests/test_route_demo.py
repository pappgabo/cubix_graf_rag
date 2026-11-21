"""Offline checks for route_demo.py's two answer_question calls -- fake
router raw_caller and fake drift mode_fn, no real API call."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import week6_bootstrap  # noqa: F401,E402
from naive_rag import answer_question as aq  # noqa: E402


def _fake_router_response(mode: str):
    return SimpleNamespace(
        content=json.dumps({"mode": mode, "reasoning": "test reasoning"}),
        response_metadata={"model_name": "gpt-4o-mini-test", "finish_reason": "stop",
                           "token_usage": {"prompt_tokens": 20, "completion_tokens": 10}},
        usage_metadata={},
    )


class RouteDemoDispatchTests(unittest.TestCase):
    def test_router_drift_decision_runs_the_drift_branch(self) -> None:
        calls: list[str] = []

        def drift_fn(question_text: str) -> dict:
            calls.append(question_text)
            return {"answer": "drift answer"}

        def raw_caller(messages, params):
            return _fake_router_response("drift")

        record = aq.answer_question(
            "route-demo-auto", "Who tied on titles?",
            mode_fns={"drift": drift_fn}, raw_caller=raw_caller)
        self.assertEqual(record["mode"], "drift")
        self.assertEqual(record["mode_source"], "router")
        self.assertEqual(calls, ["Who tied on titles?"])
        self.assertEqual(record["result"]["answer"], "drift answer")

    def test_router_other_decision_does_not_run_drift(self) -> None:
        calls: list[str] = []

        def drift_fn(question_text: str) -> dict:
            calls.append(question_text)
            return {"answer": "drift answer"}

        def raw_caller(messages, params):
            return _fake_router_response("globalis")

        record = aq.answer_question(
            "route-demo-auto", "Who tied on titles?",
            mode_fns={"drift": drift_fn}, raw_caller=raw_caller)
        self.assertEqual(record["mode"], "globalis")
        self.assertEqual(calls, [])  # drift never called
        self.assertIsNone(record["result"])
        self.assertIn("error", record)

    def test_explicit_drift_mode_never_calls_the_router(self) -> None:
        router_calls: list[str] = []
        drift_calls: list[str] = []

        def drift_fn(question_text: str) -> dict:
            drift_calls.append(question_text)
            return {"answer": "drift answer"}

        def raw_caller(messages, params):
            router_calls.append("called")
            return _fake_router_response("drift")

        record = aq.answer_question(
            "route-demo-explicit", "Who tied on titles?",
            mode_fns={"drift": drift_fn}, mode="drift", raw_caller=raw_caller)
        self.assertEqual(record["mode_source"], "explicit")
        self.assertEqual(router_calls, [])  # the router is never invoked
        self.assertEqual(drift_calls, ["Who tied on titles?"])
        self.assertNotIn("route_record", record)


if __name__ == "__main__":
    unittest.main()
