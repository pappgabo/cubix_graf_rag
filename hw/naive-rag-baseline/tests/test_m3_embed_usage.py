"""Offline proof that provider embedding usage is forwarded, and missing usage stops."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "diagnostics" / "2026-11-14-week6-drift"))

import drift_runner  # noqa: E402
import cost_guard  # noqa: E402
from golden_set import Criterion, EvidenceGroup, GoldenQuestion  # noqa: E402
from naive_rag.drift_search import EmbeddingUsageUnknown, _run_embed_step  # noqa: E402

LEDGER = ROOT / "diagnostics" / "2026-11-14-week6-drift" / "results" / "week6-cost-ledger.json"
VECTOR = [0.25, -0.5]


class _Client:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls = 0

    def create(self, *args, **kwargs):
        self.calls += 1
        return self.response


class _Embeddings:
    def __init__(self, response: dict) -> None:
        self.client = _Client(response)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = self.client.create(input=list(texts), model="text-embedding-3-small")
        return [row["embedding"] for row in response["data"]]


def _question() -> GoldenQuestion:
    return GoldenQuestion(
        id="Q01", type="simple", status="frozen_w4", question="q", expected_answer="a",
        criteria=(Criterion("Q01-c1", "t", ("a",), True),),
        evidence_groups=(EvidenceGroup("Q01-e1", "Q01-c1", ("gold",)),),
        gold_docs=("doc",), notes="", golden_set_version="test",
        corpus_chunks_file="x", corpus_chunks_sha256="abc", corpus_chunk_count=1,
    )


class EmbeddingUsageForwardTests(unittest.TestCase):
    def test_provider_total_is_booked_known_and_missing_usage_stops(self) -> None:
        before = LEDGER.read_bytes()
        known = {"data": [{"embedding": VECTOR}], "usage": {"prompt_tokens": 17, "total_tokens": 17}}
        embeddings = _Embeddings(known)
        with patch("naive_rag.models.get_embeddings", return_value=embeddings):
            call_embed = drift_runner.build_real_call_embed()
        vectors, tokens = call_embed(["same input"], "drift-report-embed")
        self.assertEqual(vectors, [VECTOR])
        self.assertEqual(tokens, 17)
        self.assertEqual(embeddings.client.calls, 1)

        with tempfile.TemporaryDirectory() as tmp:
            ledger = cost_guard.SharedCostLedger.load(Path(tmp) / "ledger.json")
            _run_embed_step(call_embed, ledger, texts=["same input"], label="drift-report-embed")
            self.assertTrue(ledger.entries[-1]["usage_known"])
            self.assertEqual(ledger.entries[-1]["actual_prompt_tokens"], 17)

            missing = _Embeddings({"data": [{"embedding": VECTOR}]})
            with patch("naive_rag.models.get_embeddings", return_value=missing):
                unknown_embed = drift_runner.build_real_call_embed()
            unknown_vectors, unknown_tokens = unknown_embed(["same input"], "drift-report-embed")
            self.assertEqual(unknown_vectors, [VECTOR])
            self.assertEqual(unknown_tokens, "unknown")
            with self.assertRaises(EmbeddingUsageUnknown):
                _run_embed_step(unknown_embed, ledger, texts=["same input"], label="drift-report-embed")
            self.assertFalse(ledger.entries[-1]["usage_known"])
            self.assertEqual(ledger.entries[-1]["actual_prompt_tokens"], "unknown")

            import measure as week5measure
            import state_store
            ctx = week5measure.CaseContext(
                run_phase="m3", budget=ledger, ledger=None,
                gen_fns={"drift": lambda _question: (_ for _ in ()).throw(EmbeddingUsageUnknown("missing"))},
                correctness_call_fn_factory=None, faithfulness_call_fn_factory=None,
                langfuse_sync_fn=None, case_store_dir=Path(tmp),
            )
            with self.assertRaises(week5measure.MeasurementHalted):
                week5measure.process_case(
                    _question(), "drift", state_store.CaseState("Q01", "drift"), ctx,
                )
        self.assertEqual(LEDGER.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
