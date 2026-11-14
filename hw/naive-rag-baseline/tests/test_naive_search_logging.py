"""Offline checks for the naive-search logging adapter. No real OpenAI
call: the chat client is a fake object."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from naive_rag import naive_search_logging as nsl


class _FakeChatClient:
    model_name = "gpt-4o-mini-fake"
    temperature = 0
    max_tokens = 512
    max_retries = 0

    def __init__(self, reply="answer text"):
        self.reply = reply
        self.received = []

    def invoke(self, messages):
        self.received.append(messages)
        return AIMessage(
            content=self.reply,
            response_metadata={"model_name": "gpt-4o-mini-fake", "finish_reason": "stop",
                               "token_usage": {"prompt_tokens": 12, "completion_tokens": 3}},
        )


class LoggedChatCallTests(unittest.TestCase):
    def test_logged_messages_match_what_the_client_actually_received(self):
        client = _FakeChatClient()
        chat_call = nsl.make_logged_chat_call(client, question_id="Q01")
        lc_messages = [SystemMessage(content="sys"), HumanMessage(content="ctx+question")]

        answer = chat_call(lc_messages)

        self.assertEqual(answer, "answer text")
        self.assertEqual(len(client.received), 1)
        sent = client.received[0]
        self.assertEqual([m.content for m in sent], ["sys", "ctx+question"])

    def test_question_id_never_appears_in_sent_content(self):
        client = _FakeChatClient()
        chat_call = nsl.make_logged_chat_call(client, question_id="Q09")
        lc_messages = [SystemMessage(content="sys"), HumanMessage(content="question?")]
        chat_call(lc_messages)
        for m in client.received[0]:
            self.assertNotIn("Q09", m.content)

    def test_saves_a_log_file_with_hash_usage_and_finish_reason(self):
        client = _FakeChatClient()
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            chat_call = nsl.make_logged_chat_call(client, log_dir=log_dir, question_id="Q01")
            chat_call([SystemMessage(content="sys"), HumanMessage(content="q")])
            saved = json.loads((log_dir / "naive-log-Q01.json").read_text(encoding="utf-8"))

        self.assertEqual(saved["messages"], [{"role": "system", "content": "sys"},
                                             {"role": "user", "content": "q"}])
        self.assertEqual(saved["usage_prompt_tokens"], 12)
        self.assertEqual(saved["usage_completion_tokens"], 3)
        self.assertEqual(saved["finish_reason"], "stop")
        self.assertEqual(saved["local_metadata"], {"question_id": "Q01"})
        self.assertIn("messages_sha256", saved)

    def test_api_error_is_raised_after_being_logged(self):
        class _FailingClient(_FakeChatClient):
            def invoke(self, messages):
                raise RuntimeError("simulated failure")

        chat_call = nsl.make_logged_chat_call(_FailingClient())
        with self.assertRaises(RuntimeError):
            chat_call([SystemMessage(content="sys"), HumanMessage(content="q")])


if __name__ == "__main__":
    unittest.main()
