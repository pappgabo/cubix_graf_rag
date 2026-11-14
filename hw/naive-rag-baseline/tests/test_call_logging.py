"""Database-free, model-free checks for the mandatory call-logging wrapper.
No real API call anywhere in this file."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from naive_rag import call_logging as cl


def _fake_response(content, model_name="gpt-4o-mini-test", prompt_tokens=10,
                   completion_tokens=5, finish_reason="stop"):
    return SimpleNamespace(
        content=content,
        response_metadata={"model_name": model_name, "finish_reason": finish_reason,
                           "token_usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}},
        usage_metadata={},
    )


class HashTests(unittest.TestCase):
    def test_hash_is_deterministic(self):
        messages = [{"role": "system", "content": "a"}, {"role": "user", "content": "b"}]
        self.assertEqual(cl.hash_messages(messages), cl.hash_messages(messages))

    def test_hash_changes_with_content(self):
        m1 = [{"role": "user", "content": "a"}]
        m2 = [{"role": "user", "content": "b"}]
        self.assertNotEqual(cl.hash_messages(m1), cl.hash_messages(m2))


class LoggedCallTests(unittest.TestCase):
    def _params(self):
        return cl.CallParams(model="gpt-4o-mini", temperature=0, max_tokens=100,
                             response_format={"type": "json_object"})

    def test_logged_messages_equal_exactly_what_the_client_received(self):
        """The core audit requirement: the logged 'messages' field must be
        the same object/content the fake client actually saw, not a
        reconstruction built from something else."""
        received = []

        def raw_caller(messages, params):
            received.append(messages)
            return _fake_response('{"ok": true}')

        sent = [{"role": "system", "content": "sys"}, {"role": "user", "content": "q?"}]
        entry = cl.logged_call(sent, self._params(), raw_caller, local_metadata={"question_id": "Q01"})

        self.assertEqual(received, [sent])
        self.assertEqual(entry.messages, sent)
        self.assertEqual(entry.messages_sha256, cl.hash_messages(sent))

    def test_local_metadata_never_reaches_the_raw_caller(self):
        received_params = []

        def raw_caller(messages, params):
            received_params.append((messages, params))
            return _fake_response('{"ok": true}')

        cl.logged_call([{"role": "user", "content": "q?"}], self._params(), raw_caller,
                       local_metadata={"question_id": "Q09", "label": "global", "gold": "secret"})

        messages, params = received_params[0]
        for m in messages:
            self.assertNotIn("Q09", m["content"])
            self.assertNotIn("global", m["content"])
            self.assertNotIn("secret", m["content"])

    def test_captures_usage_finish_reason_and_duration(self):
        def raw_caller(messages, params):
            return _fake_response('{"ok": true}', prompt_tokens=42, completion_tokens=7, finish_reason="stop")

        entry = cl.logged_call([{"role": "user", "content": "q"}], self._params(), raw_caller)
        self.assertEqual(entry.usage_prompt_tokens, 42)
        self.assertEqual(entry.usage_completion_tokens, 7)
        self.assertEqual(entry.finish_reason, "stop")
        self.assertIsNone(entry.error)
        self.assertGreaterEqual(entry.duration_seconds, 0)

    def test_api_error_is_logged_not_raised_and_usage_marked_unknown(self):
        def raw_caller(messages, params):
            raise RuntimeError("boom")

        entry = cl.logged_call([{"role": "user", "content": "q"}], self._params(), raw_caller)
        self.assertIn("boom", entry.error)
        self.assertEqual(entry.usage_prompt_tokens, "unknown")
        self.assertEqual(entry.usage_completion_tokens, "unknown")
        self.assertIsNone(entry.raw_response)

    def test_save_log_entry_round_trips_as_json(self):
        def raw_caller(messages, params):
            return _fake_response('{"ok": true}')

        entry = cl.logged_call([{"role": "user", "content": "q"}], self._params(), raw_caller,
                               local_metadata={"question_id": "Q01"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.json"
            cl.save_log_entry(path, entry)
            loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["messages_sha256"], entry.messages_sha256)
        self.assertEqual(loaded["local_metadata"], {"question_id": "Q01"})
        self.assertEqual(loaded["hash_algorithm"], "sha256")


if __name__ == "__main__":
    unittest.main()
