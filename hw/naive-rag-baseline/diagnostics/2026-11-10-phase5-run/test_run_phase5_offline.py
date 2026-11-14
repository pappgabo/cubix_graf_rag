"""Offline, fake-client-only checks for run_phase5.py. No real OpenAI,
Qdrant, or Neo4j call anywhere in this file."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import run_phase5 as rp  # noqa: E402
from naive_rag import global_search as gs  # noqa: E402


# --------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------


class BudgetTests(unittest.TestCase):
    def test_generative_within_cap_is_allowed(self):
        budget = rp.Budget(cap_usd=0.15)
        upper = budget.check_generative(1000, 900, "test")
        self.assertGreater(upper, 0)

    def test_generative_exceeding_cap_raises_without_spending(self):
        budget = rp.Budget(cap_usd=0.0001)
        with self.assertRaises(rp.BudgetExceeded):
            budget.check_generative(100000, 900, "test")
        self.assertEqual(budget.spent_usd, 0.0)

    def test_record_generative_uses_actual_usage_when_known(self):
        budget = rp.Budget(cap_usd=0.15)
        upper = budget.check_generative(1000, 900, "x")
        cost = budget.record_generative(1000, 100, upper)
        expected = 1000 / 1e6 * 0.15 + 100 / 1e6 * 0.60
        self.assertAlmostEqual(cost, expected)
        self.assertAlmostEqual(budget.spent_usd, expected)

    def test_record_generative_books_upper_bound_when_usage_unknown(self):
        """Unknown usage must never be treated as zero cost."""
        budget = rp.Budget(cap_usd=0.15)
        upper = budget.check_generative(1000, 900, "x")
        cost = budget.record_generative("unknown", "unknown", upper)
        self.assertEqual(cost, upper)
        self.assertGreater(budget.spent_usd, 0)

    def test_embedding_within_cap_and_cost_recorded(self):
        budget = rp.Budget(cap_usd=0.15)
        upper = budget.check_embedding(10000, "idx")
        cost = budget.record_embedding(10000, upper)
        self.assertAlmostEqual(cost, 10000 / 1e6 * 0.02)

    def test_sequential_calls_accumulate_and_eventually_block(self):
        budget = rp.Budget(cap_usd=0.01)
        allowed = 0
        try:
            for _ in range(1000):
                upper = budget.check_generative(50000, 900, "loop")
                budget.record_generative(50000, 900, upper)
                allowed += 1
        except rp.BudgetExceeded:
            pass
        self.assertGreater(allowed, 0)
        self.assertLessEqual(budget.spent_usd, 0.01 + 1e-9)


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------


class LedgerTests(unittest.TestCase):
    def test_entries_persist_to_disk_after_every_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            ledger = rp.Ledger(run_id="test-run", path=path)
            ledger.add(step="router", question_id="Q01", status="success")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["question_id"], "Q01")
            self.assertEqual(saved[0]["run_id"], "test-run")

    def test_metadata_never_required_to_be_in_message_content(self):
        # The ledger itself only stores metadata -- it is a separate
        # artifact from the logged request content (see call_logging.py).
        with tempfile.TemporaryDirectory() as tmp:
            ledger = rp.Ledger(run_id="r", path=Path(tmp) / "l.json")
            entry = ledger.add(step="answer", mode="naiv", question_id="Q01", cost_usd=0.001)
            self.assertNotIn("messages", entry)


# --------------------------------------------------------------------------
# embed_texts (fake OpenAI client)
# --------------------------------------------------------------------------


class _FakeEmbeddingResponse:
    def __init__(self, n, total_tokens=42):
        self.data = [SimpleNamespace(embedding=[0.1] * 3) for _ in range(n)]
        self.usage = SimpleNamespace(total_tokens=total_tokens)


class _FakeOpenAIClient:
    def __init__(self, total_tokens=42, fail=False):
        self.total_tokens = total_tokens
        self.fail = fail
        self.calls = []
        self.embeddings = SimpleNamespace(create=self._create)

    def _create(self, model, input):
        self.calls.append({"model": model, "input": list(input)})
        if self.fail:
            raise RuntimeError("simulated embedding failure")
        return _FakeEmbeddingResponse(len(input), self.total_tokens)


class EmbedTextsTests(unittest.TestCase):
    def test_uses_exact_requested_model_and_texts(self):
        budget = rp.Budget(cap_usd=0.15)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = rp.Ledger(run_id="r", path=Path(tmp) / "l.json")
            client = _FakeOpenAIClient()
            vectors = rp.embed_texts(["a", "b"], ["id1", "id2"], budget, ledger,
                                     label="test", openai_client=client)
        self.assertEqual(len(vectors), 2)
        self.assertEqual(client.calls[0]["model"], rp.EMBEDDING_MODEL)
        self.assertEqual(client.calls[0]["input"], ["a", "b"])

    def test_records_real_usage_not_an_estimate(self):
        budget = rp.Budget(cap_usd=0.15)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = rp.Ledger(run_id="r", path=Path(tmp) / "l.json")
            client = _FakeOpenAIClient(total_tokens=999)
            rp.embed_texts(["hello"], ["id1"], budget, ledger, label="t", openai_client=client)
        expected = 999 / 1e6 * rp.EMBEDDING_PRICE_PER_MTOK
        self.assertAlmostEqual(budget.spent_usd, expected)

    def test_over_budget_raises_before_calling_the_client(self):
        budget = rp.Budget(cap_usd=0.0000001)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = rp.Ledger(run_id="r", path=Path(tmp) / "l.json")
            client = _FakeOpenAIClient()
            with self.assertRaises(rp.BudgetExceeded):
                rp.embed_texts(["x" * 10000], ["id1"], budget, ledger, label="t", openai_client=client)
        self.assertEqual(client.calls, [])  # never called
        self.assertEqual(budget.spent_usd, 0.0)

    def test_api_error_is_logged_and_raised_not_retried(self):
        budget = rp.Budget(cap_usd=0.15)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = rp.Ledger(run_id="r", path=Path(tmp) / "l.json")
            client = _FakeOpenAIClient(fail=True)
            with self.assertRaises(RuntimeError):
                rp.embed_texts(["x"], ["id1"], budget, ledger, label="t", openai_client=client)
            self.assertEqual(len(client.calls), 1)  # exactly once, no retry
            saved = json.loads((Path(tmp) / "l.json").read_text(encoding="utf-8"))
            self.assertEqual(saved[-1]["status"], "error")


# --------------------------------------------------------------------------
# Globalis rerun -- A-only, no B call ever attempted
# --------------------------------------------------------------------------


class GlobalisRerunTests(unittest.TestCase):
    RUN_ID = "week4-leiden-elokeszitett-6f05327d7d88ebf0"

    def _reports(self):
        return (
            gs.CommunityReport("5", f"{self.RUN_ID}:5", self.RUN_ID, 0, "s",
                              (gs.ReportStatement("5#1", "x", (), ()),)),
            gs.CommunityReport("22", f"{self.RUN_ID}:22", self.RUN_ID, 0, "s",
                              (gs.ReportStatement("22#1", "y", (), ()),)),
        )

    def test_never_calls_reduce_b(self):
        reports = self._reports()
        calls = []

        def fake_call_fn(system, user, max_tokens):
            calls.append(json.loads(user))
            payload = json.loads(user)
            if "partial_answers" in payload:
                return gs.ModelResponse(
                    content=json.dumps({"answer": "final", "cited_partial_answer_ids": [p["id"] for p in payload["partial_answers"]]}),
                    returned_model="m", usage_prompt_tokens=10, usage_completion_tokens=5, finish_reason="stop",
                )
            sid = payload["statements"][0]["id"]
            return gs.ModelResponse(
                content=json.dumps({"partial_answer": "ans", "usefulness_score": 50, "cited_statement_ids": [sid]}),
                returned_model="m", usage_prompt_tokens=10, usage_completion_tokens=5, finish_reason="stop",
            )

        import run_phase5 as rp_mod
        with tempfile.TemporaryDirectory() as tmp:
            rp_mod.LOG_DIR = Path(tmp)
            outcome = rp_mod.gs_run_question_a_only(gs.Question("Q09", "global", "q?"), reports, fake_call_fn)

        self.assertIsNone(outcome["halted_reason"])
        reduce_calls = [c for c in calls if "partial_answers" in c]
        self.assertEqual(len(reduce_calls), 1)  # exactly the A reduce, never a B

    def test_all_zero_scores_refuse_without_a_reduce_call(self):
        reports = self._reports()
        reduce_calls = []

        def fake_call_fn(system, user, max_tokens):
            payload = json.loads(user)
            if "partial_answers" in payload:
                reduce_calls.append(payload)
                raise AssertionError("must not call reduce when there is no positive partial")
            return gs.ModelResponse(
                content=json.dumps({"partial_answer": "", "usefulness_score": 0, "cited_statement_ids": []}),
                returned_model="m", usage_prompt_tokens=5, usage_completion_tokens=2, finish_reason="stop",
            )

        import run_phase5 as rp_mod
        with tempfile.TemporaryDirectory() as tmp:
            rp_mod.LOG_DIR = Path(tmp)
            outcome = rp_mod.gs_run_question_a_only(gs.Question("Q09", "global", "q?"), reports, fake_call_fn)

        self.assertIsNone(outcome["halted_reason"])
        self.assertEqual(outcome["reduce_a"]["answer"], gs.GLOBAL_REFUSAL)
        self.assertEqual(reduce_calls, [])
        # a clean, rule-based refusal is not an error
        self.assertNotEqual(outcome["reduce_a"].get("status"), "error")

    def test_invalid_map_response_halts_immediately(self):
        reports = self._reports()
        calls = []

        def fake_call_fn(system, user, max_tokens):
            calls.append(user)
            if len(calls) == 1:
                return gs.ModelResponse(
                    content=json.dumps({"partial_answer": "x", "usefulness_score": 10, "cited_statement_ids": []}),
                    returned_model="m", usage_prompt_tokens=5, usage_completion_tokens=2, finish_reason="stop",
                )
            raise AssertionError("must stop after the first invalid map response, no retry")

        import run_phase5 as rp_mod
        with tempfile.TemporaryDirectory() as tmp:
            rp_mod.LOG_DIR = Path(tmp)
            outcome = rp_mod.gs_run_question_a_only(gs.Question("Q09", "global", "q?"), reports, fake_call_fn)

        self.assertIsNotNone(outcome["halted_reason"])
        self.assertEqual(len(calls), 1)


# --------------------------------------------------------------------------
# run_router_all (fake raw_caller) -- leak check, budget check, halting
# --------------------------------------------------------------------------


class RouterAllTests(unittest.TestCase):
    def _fake_caller(self, reply='{"mode": "naiv", "reasoning": "single fact"}'):
        def raw_caller(messages, params):
            from langchain_core.messages import AIMessage
            return AIMessage(content=reply, response_metadata={
                "model_name": "gpt-4o-mini-fake", "finish_reason": "stop",
                "token_usage": {"prompt_tokens": 20, "completion_tokens": 5},
            })
        return raw_caller

    def test_question_id_and_label_never_in_logged_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            rp.LOG_DIR = Path(tmp)
            budget = rp.Budget(cap_usd=0.15)
            ledger = rp.Ledger(run_id="r", path=Path(tmp) / "ledger.json")
            rp.run_router_all([("Q09", "Across all drivers who won the most titles?")],
                              budget, ledger, raw_caller=self._fake_caller())
            log = json.loads((Path(tmp) / "router-log-Q09.json").read_text(encoding="utf-8"))
        content = json.dumps(log["messages"])
        self.assertNotIn("Q09", content)
        import re
        self.assertNotRegex(content, r"\bglobal\b")

    def test_budget_checked_before_each_call_and_halts_on_exhaustion(self):
        with tempfile.TemporaryDirectory() as tmp:
            rp.LOG_DIR = Path(tmp)
            budget = rp.Budget(cap_usd=0.0000001)
            ledger = rp.Ledger(run_id="r", path=Path(tmp) / "ledger.json")
            with self.assertRaises(rp.BudgetExceeded):
                rp.run_router_all([("Q01", "q1?"), ("Q02", "q2?")], budget, ledger,
                                  raw_caller=self._fake_caller())

    def test_stops_after_first_router_error(self):
        calls = {"n": 0}

        def failing_caller(messages, params):
            calls["n"] += 1
            raise RuntimeError("simulated router failure")

        with tempfile.TemporaryDirectory() as tmp:
            rp.LOG_DIR = Path(tmp)
            budget = rp.Budget(cap_usd=0.15)
            ledger = rp.Ledger(run_id="r", path=Path(tmp) / "ledger.json")
            records = rp.run_router_all([("Q01", "q1?"), ("Q02", "q2?")], budget, ledger,
                                        raw_caller=failing_caller)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(len(records), 1)
        self.assertIn("error", records[0])


class RunNaivTests(unittest.TestCase):
    def test_search_fn_injection_avoids_real_qdrant_and_openai(self):
        with tempfile.TemporaryDirectory() as tmp:
            rp.LOG_DIR = Path(tmp)
            budget = rp.Budget(cap_usd=0.15)
            ledger = rp.Ledger(run_id="r", path=Path(tmp) / "ledger.json")
            embed_client = _FakeOpenAIClient(total_tokens=10)

            def fake_search_fn(vector):
                doc = SimpleNamespace(page_content="some chunk text",
                                      metadata={"chunk_id": "doc#0", "doc_id": "doc", "file": "f", "format": "html", "url": "u"})
                return [(doc, 0.9)]

            class _FakeAIMessage:
                content = '{"ok": true}'
                response_metadata = {"model_name": "gpt-4o-mini-fake", "finish_reason": "stop",
                                     "token_usage": {"prompt_tokens": 30, "completion_tokens": 10}}

            class _FakeChatClient:
                model_name = "gpt-4o-mini-fake"
                temperature = 0
                max_tokens = 900
                max_retries = 0

                def invoke(self, messages):
                    return _FakeAIMessage()

            result = rp.run_naiv(
                "Q01", "question text?", budget, ledger,
                openai_client=embed_client, search_fn=fake_search_fn, chat_client=_FakeChatClient(),
            )
        self.assertIsNone(result["error"])
        self.assertEqual(result["answer"], '{"ok": true}')
        self.assertEqual(len(result["sources"]), 1)
        self.assertGreater(budget.spent_usd, 0)


if __name__ == "__main__":
    unittest.main()
