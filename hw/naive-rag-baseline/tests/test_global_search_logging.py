"""Offline checks for the global-search (map/reduce) logging adapter. No
real OpenAI call: the ChatOpenAI client is injected as a fake via
``client_factory``."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from naive_rag import global_search_logging as gsl


class _FakeClient:
    def __init__(self, reply='{"ok": true}'):
        self.reply = reply
        self.received = []

    def invoke(self, lc_messages):
        self.received.append(lc_messages)
        return AIMessage(
            content=self.reply,
            response_metadata={"model_name": "gpt-4o-mini-fake", "finish_reason": "stop",
                               "token_usage": {"prompt_tokens": 30, "completion_tokens": 6}},
        )


class LoggedCallFnTests(unittest.TestCase):
    def _factory(self, client):
        return lambda call_params: client

    def test_returns_a_global_search_model_response(self):
        client = _FakeClient(reply='{"partial_answer": "x", "usefulness_score": 10, "cited_statement_ids": ["5#1"]}')
        call_fn = gsl.make_logged_call_fn(SimpleNamespace(openai_api_key="fake"), client_factory=self._factory(client))

        response = call_fn("system prompt", "user payload", 400)

        self.assertEqual(response.content, client.reply)
        self.assertEqual(response.usage_prompt_tokens, 30)
        self.assertEqual(response.usage_completion_tokens, 6)
        self.assertEqual(response.finish_reason, "stop")
        self.assertEqual(response.returned_model, "gpt-4o-mini-fake")

    def test_client_receives_exactly_the_given_system_and_user_text(self):
        client = _FakeClient()
        call_fn = gsl.make_logged_call_fn(SimpleNamespace(openai_api_key="fake"), client_factory=self._factory(client))
        call_fn("SYS", "USER", 100)
        sent = client.received[0]
        self.assertEqual([m.content for m in sent], ["SYS", "USER"])

    def test_saves_sequential_log_files_with_full_messages(self):
        client = _FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            call_fn = gsl.make_logged_call_fn(
                SimpleNamespace(openai_api_key="fake"), log_dir=log_dir, prefix="map",
                client_factory=self._factory(client),
            )
            call_fn("sys1", "user1", 100)
            call_fn("sys2", "user2", 100)
            first = json.loads((log_dir / "map-log-0001.json").read_text(encoding="utf-8"))
            second = json.loads((log_dir / "map-log-0002.json").read_text(encoding="utf-8"))
        self.assertEqual(first["messages"], [{"role": "system", "content": "sys1"},
                                             {"role": "user", "content": "user1"}])
        self.assertEqual(second["messages"][1]["content"], "user2")
        self.assertEqual(first["local_metadata"], {"call_index": 1})
        self.assertEqual(second["local_metadata"], {"call_index": 2})

    def test_api_error_is_raised_after_logging(self):
        class _FailingClient(_FakeClient):
            def invoke(self, lc_messages):
                raise RuntimeError("simulated failure")

        call_fn = gsl.make_logged_call_fn(
            SimpleNamespace(openai_api_key="fake"), client_factory=self._factory(_FailingClient())
        )
        with self.assertRaises(RuntimeError):
            call_fn("sys", "user", 100)

    def test_compatible_with_global_search_process_one_map(self):
        """The wrapped call_fn must be a drop-in replacement for
        global_search.ModelCall, so process_one_map can use it unchanged."""
        import tempfile as _tmp

        from naive_rag import global_search as gs

        client = _FakeClient(reply='{"partial_answer": "p", "usefulness_score": 40, "cited_statement_ids": ["5#1"]}')
        call_fn = gsl.make_logged_call_fn(SimpleNamespace(openai_api_key="fake"), client_factory=self._factory(client))

        report = gs.CommunityReport("5", "run:5", "run", 0, "s",
                                    (gs.ReportStatement("5#1", "stmt", (), ()),))
        question = gs.Question("Q01", "simple", "q?")
        with _tmp.TemporaryDirectory() as tmp:
            paths = gs.RunPaths(Path(tmp))
            ledger: dict = {}
            record = gs.process_one_map(question, report, call_fn, paths, ledger, Path(tmp) / "ledger.json")
        self.assertEqual(record["usefulness_score"], 40)
        self.assertEqual(ledger["map:Q01:5"]["status"], "success")


if __name__ == "__main__":
    unittest.main()
