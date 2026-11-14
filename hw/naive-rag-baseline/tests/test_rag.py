"""Offline checks for NaiveRAG's new, optional ``chat_call`` injection
point. No real Qdrant or OpenAI call: NaiveRAG is constructed via
``__new__`` (bypassing ``__init__``, which opens a real Qdrant client) and
its ``store``/``settings`` are set to fakes directly.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from naive_rag.rag import NaiveRAG


class _FakeDoc:
    def __init__(self, content, metadata):
        self.page_content = content
        self.metadata = metadata


class _FakeStore:
    def __init__(self, hits):
        self._hits = hits

    def similarity_search_with_score(self, question, k):
        return self._hits[:k]


def _rag_with_fake_store(chat_call=None):
    rag = NaiveRAG.__new__(NaiveRAG)
    rag.settings = SimpleNamespace(top_k=4)
    rag.store = _FakeStore([
        (_FakeDoc("some text", {"chunk_id": "doc#0", "doc_id": "doc"}), 0.9),
    ])
    rag._chat_call = chat_call
    return rag


class DefaultBehaviourPreservedTests(unittest.TestCase):
    def test_default_path_still_calls_get_chat_model_when_no_chat_call_given(self):
        rag = _rag_with_fake_store(chat_call=None)
        with mock.patch("naive_rag.rag.get_chat_model") as get_chat_model:
            get_chat_model.return_value.invoke.return_value.content = "default answer"
            result = rag.ask("What happened?")
        get_chat_model.assert_called_once()
        self.assertEqual(result["answer"], "default answer")

    def test_init_default_signature_still_constructible_without_chat_call(self):
        # NaiveRAG(chat_call=...) is optional; the old no-arg call shape is
        # unaffected by the new parameter (checked via the signature, not a
        # real construction -- __init__ still opens a real Qdrant client).
        import inspect
        sig = inspect.signature(NaiveRAG.__init__)
        self.assertIn("chat_call", sig.parameters)
        self.assertIsNone(sig.parameters["chat_call"].default)


class InjectedChatCallTests(unittest.TestCase):
    def test_injected_chat_call_is_used_instead_of_get_chat_model(self):
        received = []

        def fake_chat_call(messages):
            received.append(messages)
            return "logged answer"

        rag = _rag_with_fake_store(chat_call=fake_chat_call)
        with mock.patch("naive_rag.rag.get_chat_model") as get_chat_model:
            result = rag.ask("What happened?")

        get_chat_model.assert_not_called()
        self.assertEqual(result["answer"], "logged answer")
        self.assertEqual(len(received), 1)
        self.assertEqual(result["question"], "What happened?")


if __name__ == "__main__":
    unittest.main()
