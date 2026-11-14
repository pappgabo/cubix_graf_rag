import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cost_guard as cg
import _bootstrap  # noqa: F401
import run_phase5 as phase5


class SharedCostLedgerInterfaceTests(unittest.TestCase):
    """SharedCostLedger must be a drop-in replacement for run_phase5.Budget:
    same method names, same signatures -- this is what actually broke the
    first smoke run ('SharedCostLedger' object has no attribute
    'check_embedding'), so these assert the exact interface, not just
    'some check/record methods exist'."""

    def test_has_all_four_budget_methods_with_matching_signatures(self) -> None:
        import inspect

        for name in ("check_generative", "check_embedding", "record_generative", "record_embedding"):
            self.assertTrue(hasattr(cg.SharedCostLedger, name), f"missing method: {name}")
            budget_sig = inspect.signature(getattr(phase5.Budget, name))
            ledger_sig = inspect.signature(getattr(cg.SharedCostLedger, name))
            self.assertEqual(list(budget_sig.parameters), list(ledger_sig.parameters), name)

    def test_check_embedding_raises_before_exceeding_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = cg.SharedCostLedger.load(Path(tmp) / "ledger.json", cap_usd=0.0000001)
            with self.assertRaises(cg.BudgetExceeded):
                ledger.check_embedding(1_000_000, "embed-1")

    def test_check_generative_raises_before_exceeding_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = cg.SharedCostLedger.load(Path(tmp) / "ledger.json", cap_usd=0.0000001)
            with self.assertRaises(cg.BudgetExceeded):
                ledger.check_generative(1_000_000, 1_000_000, "gen-1")

    def test_record_embedding_known_usage_books_actual_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = cg.SharedCostLedger.load(Path(tmp) / "ledger.json", cap_usd=1.0)
            cost = ledger.record_embedding(1000, upper_bound=0.01)
            expected = 1000 / 1_000_000 * phase5.EMBEDDING_PRICE_PER_MTOK
            self.assertAlmostEqual(cost, expected)
            self.assertAlmostEqual(ledger.spent_usd, expected)

    def test_record_embedding_unknown_usage_books_upper_bound_not_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = cg.SharedCostLedger.load(Path(tmp) / "ledger.json", cap_usd=1.0)
            cost = ledger.record_embedding("unknown", upper_bound=0.03)
            self.assertEqual(cost, 0.03)
            self.assertEqual(ledger.entries[-1]["usage_known"], False)
            self.assertIsNotNone(ledger.entries[-1]["note"])

    def test_record_generative_known_usage_books_actual_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = cg.SharedCostLedger.load(Path(tmp) / "ledger.json", cap_usd=1.0)
            cost = ledger.record_generative(1000, 100, upper_bound=0.01)
            expected = (1000 / 1_000_000 * phase5.INPUT_PRICE_PER_MTOK
                       + 100 / 1_000_000 * phase5.OUTPUT_PRICE_PER_MTOK)
            self.assertAlmostEqual(cost, expected)

    def test_persists_and_shares_spend_across_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            first = cg.SharedCostLedger.load(path, cap_usd=1.0)
            first.record_embedding(1000, upper_bound=0.01)
            second = cg.SharedCostLedger.load(path, cap_usd=1.0)
            self.assertAlmostEqual(second.spent_usd, first.spent_usd)

    def test_remaining_usd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = cg.SharedCostLedger.load(Path(tmp) / "ledger.json", cap_usd=0.50)
            ledger.record_generative(1_000_000, 0, upper_bound=1.0)
            self.assertAlmostEqual(ledger.remaining_usd(), 0.50 - phase5.INPUT_PRICE_PER_MTOK)


# ---------------------------------------------------------------------------
# Real integration: SharedCostLedger wired into the ACTUAL run_phase5
# callers (embed_texts / run_naiv), with fake external clients -- not a
# permissive mock ledger. This is the regression test for the reported
# crash: 'SharedCostLedger' object has no attribute 'check_embedding'.
# ---------------------------------------------------------------------------


@dataclass
class FakeAIMessage:
    content: str
    usage_metadata: dict = field(default_factory=lambda: {"input_tokens": 50, "output_tokens": 10})
    response_metadata: dict = field(
        default_factory=lambda: {"model_name": "gpt-4o-mini-fake", "finish_reason": "stop"})


class FakeChatClient:
    model_name = "gpt-4o-mini-fake"
    temperature = 0
    max_tokens = 900
    max_retries = 0

    def invoke(self, messages):
        return FakeAIMessage(content="Fake answer mentioning Lewis Hamilton and seven titles.")


class FakeOpenAIClient:
    """Fake raw ``openai.OpenAI`` client -- only the ``embeddings.create``
    surface ``run_phase5.embed_texts`` actually calls."""

    def __init__(self) -> None:
        self.embeddings = SimpleNamespace(create=self._create)
        self.calls = 0

    def _create(self, *, model: str, input: list[str]):
        self.calls += 1
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1] * 8) for _ in input],
            usage=SimpleNamespace(total_tokens=12 * len(input)),
        )


class RealLedgerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        # embed_texts/run_naiv write log files under module-level
        # phase5.LOG_DIR -- redirect to a temp dir for the test so nothing
        # lands in the preserved Phase 5 folder, then restore it.
        self._orig_log_dir = phase5.LOG_DIR
        self._tmp = tempfile.TemporaryDirectory()
        phase5.LOG_DIR = Path(self._tmp.name) / "logs"

    def tearDown(self) -> None:
        phase5.LOG_DIR = self._orig_log_dir
        self._tmp.cleanup()

    def test_embed_texts_uses_shared_ledger_without_attribute_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            budget = cg.SharedCostLedger.load(Path(tmp) / "cost-ledger.json", cap_usd=1.0)
            ledger = phase5.Ledger(run_id="test", path=Path(tmp) / "run-ledger.json")
            openai_client = FakeOpenAIClient()
            vectors = phase5.embed_texts(
                ["hello world"], ["id-1"], budget, ledger, label="test-embed", openai_client=openai_client,
            )
            self.assertEqual(len(vectors), 1)
            self.assertEqual(openai_client.calls, 1)
            self.assertGreater(budget.spent_usd, 0)
            self.assertEqual(budget.entries[-1]["step"], "embedding")

    def test_run_naiv_end_to_end_with_shared_ledger_and_fake_clients(self) -> None:
        """Exercises BOTH check_embedding/record_embedding (query embed)
        AND check_generative/record_generative (chat call) through the
        real run_phase5.run_naiv, with a real SharedCostLedger -- the
        exact call path generation_runner.run_naiv_capture uses."""
        with tempfile.TemporaryDirectory() as tmp:
            budget = cg.SharedCostLedger.load(Path(tmp) / "cost-ledger.json", cap_usd=1.0)
            ledger = phase5.Ledger(run_id="test", path=Path(tmp) / "run-ledger.json")
            openai_client = FakeOpenAIClient()
            chat_client = FakeChatClient()

            def fake_search_fn(vector):
                doc = SimpleNamespace(
                    page_content="Lewis Hamilton has won seven titles.",
                    metadata={"chunk_id": "driver-lewis-hamilton#0", "doc_id": "driver-lewis-hamilton"},
                )
                return [(doc, 0.95)]

            result = phase5.run_naiv(
                "Q01", "How many titles has Hamilton won?", budget, ledger,
                chat_client=chat_client, openai_client=openai_client, search_fn=fake_search_fn,
            )

            self.assertIsNone(result["error"])
            self.assertIn("seven", result["answer"])
            steps = {entry["step"] for entry in budget.entries}
            self.assertEqual(steps, {"embedding", "generative"})
            self.assertGreater(budget.spent_usd, 0)

    def test_run_naiv_halts_before_call_when_cap_too_low(self) -> None:
        """The shared cap, not a permissive mock, actually gates the call.
        cap_usd=0.0 guarantees even the smallest non-zero estimate exceeds
        it, so the very first check (embedding) must raise."""
        with tempfile.TemporaryDirectory() as tmp:
            budget = cg.SharedCostLedger.load(Path(tmp) / "cost-ledger.json", cap_usd=0.0)
            ledger = phase5.Ledger(run_id="test", path=Path(tmp) / "run-ledger.json")
            openai_client = FakeOpenAIClient()
            chat_client = FakeChatClient()

            def fake_search_fn(vector):
                return [(SimpleNamespace(page_content="x", metadata={"chunk_id": "a#0", "doc_id": "a"}), 0.5)]

            with self.assertRaises(cg.BudgetExceeded):
                phase5.run_naiv(
                    "Q01", "How many titles?", budget, ledger,
                    chat_client=chat_client, openai_client=openai_client, search_fn=fake_search_fn,
                )
            self.assertEqual(openai_client.calls, 0)  # halted before the embedding call was even made


if __name__ == "__main__":
    unittest.main()
