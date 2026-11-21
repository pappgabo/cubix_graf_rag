"""Offline checks for the DRIFT local-follow-up switch and run isolation."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "diagnostics" / "2026-11-14-week6-drift"))
sys.path.insert(0, str(ROOT / "src"))

import drift_measure as dm  # noqa: E402
import drift_runner  # noqa: E402
import state_store  # noqa: E402
from golden_set import Criterion, EvidenceGroup, GoldenQuestion  # noqa: E402
from naive_rag.drift_search import DriftAnswer, drift_search  # noqa: E402


def _question() -> GoldenQuestion:
    return GoldenQuestion(
        id="Q01", type="simple", status="frozen_w4", question="How many titles?",
        expected_answer="7",
        criteria=(Criterion("Q01-c1", "seven", ("7",), True),),
        evidence_groups=(EvidenceGroup("Q01-e1", "Q01-c1", ("gold-chunk",)),),
        gold_docs=("doc",), notes="", golden_set_version="test",
        corpus_chunks_file="x", corpus_chunks_sha256="abc", corpus_chunk_count=1,
    )


def _answer() -> DriftAnswer:
    return DriftAnswer(
        question="How many titles?", status="ok", answer="synthesis only",
        report_ids=(), report_anchors=(), primer_prompt="", primer_raw_response="",
        primer_initial_answer="primer", subquestions=("about a",), subquestion_results=(),
        synthesis_prompt="prompt", synthesis_context="primer context",
        synthesis_context_truncation=None, synthesis_raw_response="synthesis only", steps=(),
    )


def _golden(path: Path) -> None:
    path.write_text(
        '{"id":"Q01","type":"simple","status":"frozen_w4","question":"Q?",'
        '"expected_answer":"A.","criteria":[{"id":"Q01-c1","text":"t",'
        '"expected_content":["a"],"required":true}],'
        '"evidence_groups":[{"id":"Q01-e1","criterion":"Q01-c1","any_of_chunk_ids":["c0"]}],'
        '"gold_docs":["doc"],"notes":"n","golden_set_version":"test",'
        '"corpus":{"chunks_file":"x","chunks_sha256":"abc","chunk_count":1}}\n',
        encoding="utf-8",
    )


class FollowupIsolationTests(unittest.TestCase):
    def test_switch_default_paths_and_shared_ledger(self):
        self.assertIs(drift_search.__kwdefaults__["local_search_followup"], True)
        self.assertEqual(dm.M3_QUESTION_IDS, ("Q01", "Q07", "Q09", "Q10", "Q11"))
        on = dm.ablation_paths("m3-followup-on")
        off = dm.ablation_paths("m3-followup-off")
        self.assertNotEqual(on["results"], off["results"])
        self.assertNotEqual(on["state"], off["state"])
        self.assertNotEqual(on["logs"], off["logs"])
        self.assertEqual(on["cost_ledger"], dm.LEDGER_PATH)
        self.assertEqual(off["cost_ledger"], dm.LEDGER_PATH)
        self.assertEqual(dm.LEDGER_PATH, dm.RESULTS_DIR / "week6-cost-ledger.json")
        self.assertFalse(str(on["cost_ledger"]).startswith(str(on["results"])))
        on_cfg = dm.ablation_config(global_run_id="r", reports_hash="h", run_id="m3-followup-on", local_followup=True)
        off_cfg = dm.ablation_config(global_run_id="r", reports_hash="h", run_id="m3-followup-on", local_followup=False)
        self.assertEqual(
            {key for key in on_cfg if on_cfg[key] != off_cfg[key]},
            {"local_search_followup"},
        )
        self.assertEqual(on_cfg["question_ids"], ["Q01", "Q07", "Q09", "Q10", "Q11"])
        self.assertEqual(on_cfg["min_subquestions"], off_cfg["min_subquestions"])
        self.assertEqual(dm.main(["run", "--local-followup", "off"]), 1)

    def test_existing_target_and_identity_stop_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {"results": root / "results", "state": root / "state.json", "logs": root / "logs"}
            paths["results"].mkdir()
            with self.assertRaises(dm.MeasurementHalted):
                dm.refuse_existing_run(paths)
            golden = root / "golden.jsonl"
            _golden(golden)
            on = dm.ablation_signature(
                golden, global_run_id="r", reports_hash="h", run_id="m3-followup-on", local_followup=True,
            )
            off = dm.ablation_signature(
                golden, global_run_id="r", reports_hash="h", run_id="m3-followup-on", local_followup=False,
            )
            self.assertNotEqual(on.config_sha256, off.config_sha256)
            state_store.StateStore.load_or_create(paths["state"], on).save()
            with self.assertRaises(state_store.StateError):
                state_store.StateStore.load_or_create(paths["state"], off)
            changed = dm.ablation_config(
                global_run_id="r", reports_hash="h", run_id="m3-followup-on", local_followup=True,
            )
            changed["question_ids"] = ["Q01"]
            other = state_store.RunSignature("m3-followup-on", state_store.config_hash(changed), on.golden_set_sha256)
            with self.assertRaises(state_store.StateError):
                state_store.StateStore.load_or_create(paths["state"], other)

    def test_capture_and_scored_retrieval_follow_the_switch(self):
        question = _question()
        answer = _answer()
        with patch.object(drift_runner, "build_real_call_chat", return_value=lambda *a, **k: ("", {})), \
                patch.object(drift_runner, "build_real_call_embed", return_value=lambda *a, **k: ([[0.0]], 1)), \
                patch.object(drift_runner, "drift_search", return_value=answer) as search:
            record = drift_runner.run_drift_capture(
                "Q01", question.question, None, run_phase="m3-followup-off",
                reports=(), report_index=None, graph=None, local_index=None, chunk_texts={},
                local_search_followup=False, log_dir=Path(tempfile.gettempdir()),
            )
        self.assertFalse(search.call_args.kwargs["local_search_followup"])
        self.assertFalse(record["chunk_ids_traceable"])
        self.assertEqual(record["actual_chunk_ids"], [])
        row = self._score(question, record)
        self.assertEqual(row["retrieval"]["status"], "not_applicable")
        self.assertNotEqual(row["retrieval"]["status"], "untraceable")
        self.assertIsNone(row["retrieval"]["ratio"])
        self.assertIsNone(row["retrieval"]["hit_count"])
        self.assertIsNone(row["retrieval"]["untraceable_reason"])
        self.assertEqual(
            row["retrieval"]["not_applicable_reason"],
            "nem alkalmazható: a local followup szándékosan kikapcsolva",
        )
        cell = dm.report_mod._cell([
            {"correctness": {"label": "helyes"}, "retrieval": {"status": "scored", "ratio": 1.0, "is_proxy": False}},
            {"correctness": {"label": "helyes"}, "retrieval": row["retrieval"]},
        ])
        self.assertIn("retrieval_avg=1.00", cell)
        self.assertNotIn("retrieval_avg=0.50", cell)
        ran = dict(record)
        ran["chunk_ids_traceable"] = True
        ran["retrieval_not_applicable"] = False
        ran["retrieval_untraceable_reason"] = None
        ran["actual_chunk_ids"] = []
        scored = self._score(question, ran)
        self.assertEqual(scored["retrieval"]["status"], "scored")
        self.assertEqual(scored["retrieval"]["ratio"], 0.0)

    def _score(self, question: GoldenQuestion, record: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = dm.week5measure.CaseContext(
                run_phase="m3", budget=type("Budget", (), {"spent_usd": 0.0})(), ledger=None,
                gen_fns={"drift": lambda _question: record},
                correctness_call_fn_factory=None, faithfulness_call_fn_factory=None,
                langfuse_sync_fn=None, case_store_dir=Path(tmp),
            )
            case = state_store.CaseState(question_id=question.id, mode="drift")
            return dm.week5measure.process_case(question, "drift", case, ctx)


if __name__ == "__main__":
    unittest.main()
