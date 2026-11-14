"""Offline checks for the local-search logging adapter. No real OpenAI
call: the chat client is a fake object."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from naive_rag import local_search_logging as lsl


class _FakeChatClient:
    model_name = "gpt-4o-mini-fake"
    temperature = 0
    max_tokens = None
    max_retries = 0

    def __init__(self, reply="local answer"):
        self.reply = reply
        self.received = []

    def invoke(self, prompt):
        self.received.append(prompt)
        return SimpleNamespace(
            content=self.reply,
            response_metadata={"model_name": "gpt-4o-mini-fake", "finish_reason": "stop",
                               "token_usage": {"prompt_tokens": 50, "completion_tokens": 8}},
            usage_metadata={},
        )


class LoggedAnswerFnTests(unittest.TestCase):
    def test_same_observable_behaviour_as_the_plain_lambda(self):
        """answer_fn(prompt) must return exactly what
        `lambda prompt: chat.invoke(prompt).content` would have."""
        client = _FakeChatClient(reply="the local answer")
        answer_fn = lsl.make_logged_answer_fn(client)

        plain_result = client.invoke("some prompt").content
        logged_result = answer_fn("some prompt")

        self.assertEqual(plain_result, logged_result)

    def test_the_exact_prompt_string_is_what_the_client_receives(self):
        client = _FakeChatClient()
        answer_fn = lsl.make_logged_answer_fn(client)
        prompt = "Kérdés: What?\n\nKontextus:\n..."
        answer_fn(prompt)
        self.assertEqual(client.received, [prompt])

    def test_log_file_records_prompt_as_a_single_user_message(self):
        client = _FakeChatClient()
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            answer_fn = lsl.make_logged_answer_fn(client, log_dir=log_dir, question_id="Q04")
            answer_fn("the full rendered prompt")
            saved = json.loads((log_dir / "local-log-Q04.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["messages"], [{"role": "user", "content": "the full rendered prompt"}])
        self.assertEqual(saved["usage_prompt_tokens"], 50)
        self.assertEqual(saved["usage_completion_tokens"], 8)
        self.assertEqual(saved["local_metadata"], {"question_id": "Q04"})

    def test_question_id_is_not_part_of_the_logged_messages_content(self):
        client = _FakeChatClient()
        answer_fn = lsl.make_logged_answer_fn(client, question_id="Q04")
        answer_fn("prompt with no id inside it")
        self.assertNotIn("Q04", client.received[0])

    def test_api_error_is_raised(self):
        class _FailingClient(_FakeChatClient):
            def invoke(self, prompt):
                raise RuntimeError("boom")

        answer_fn = lsl.make_logged_answer_fn(_FailingClient())
        with self.assertRaises(RuntimeError):
            answer_fn("prompt")


if __name__ == "__main__":
    unittest.main()
