"""Offline checks for the J1-globalis measurement entry point -- fake
clients/dependencies, synthetic collection/golden fixtures, no real API/
DB call, no real Langfuse upload. Does not require a real J1 report
collection (one has not been generated in this round)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import j1_measure_bootstrap  # noqa: F401,E402
import j1_globalis_measure as j1m  # noqa: E402
import measure as week5measure  # noqa: E402
import state_store  # noqa: E402
import golden_set as gs  # noqa: E402

def _golden_row(qid: str) -> dict:
    return {
        "id": qid, "type": "simple", "status": "frozen_w4", "question": "Q?", "expected_answer": "A.",
        "criteria": [{"id": f"{qid}-c1", "text": "t1", "expected_content": ["a"], "required": True}],
        "evidence_groups": [{"id": f"{qid}-e1", "criterion": f"{qid}-c1", "any_of_chunk_ids": ["doc-a#0"]}],
        "gold_docs": ["doc-a"], "notes": "n", "golden_set_version": "test",
        "corpus": {"chunks_file": "x", "chunks_sha256": "abc", "chunk_count": 2},
    }


def _write_golden(path: Path, ids: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for qid in ids:
            handle.write(json.dumps(_golden_row(qid)) + "\n")


def _fake_correctness_call_fn(system, user, max_tokens):
    payload = json.loads(user)
    criterion_id = payload["criteria"][0]["id"]
    return _FakeJudge(json.dumps({
        "criteria": [{"criterion_id": criterion_id, "verdict": "met"}],
        "refused": False, "rubric_conflicts": [], "reasoning": "r",
    }))


def _fake_faithfulness_call_fn(system, user, max_tokens):
    return _FakeJudge(json.dumps({"claims": [], "reasoning": "r"}))


def _write_collection(path: Path, paths: list[str], *, prompt_version: str = "riportprompt-j1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for p in paths:
            row = {"path": p, "run_id": "r", "reporting_level": 0, "prompt_version": prompt_version,
                  "summary": "s", "key_statements": []}
            handle.write(json.dumps(row) + "\n")


class CompletenessAndHashTests(unittest.TestCase):
    """8, 9, 10, 11, 12: missing/corrupt/pilot-only/missing-id/extra-or-
    duplicate-id collections all halt before any call."""

    def setUp(self) -> None:
        self._v3_patch = mock.patch.object(j1m, "V3_COLLECTION_PATH")
        mocked = self._v3_patch.start()
        self.addCleanup(self._v3_patch.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.baseline_path = Path(self.tmp.name) / "v3.jsonl"
        _write_collection(self.baseline_path, ["1", "2", "3"], prompt_version="riportprompt-v3")
        mocked.exists.return_value = True
        j1m.V3_COLLECTION_PATH = self.baseline_path  # simplest: real attribute swap

    def test_missing_collection_halts(self) -> None:
        with self.assertRaises(j1m.J1MeasureHalt):
            j1m.verify_collection_completeness(Path(self.tmp.name) / "does-not-exist.jsonl")

    def test_malformed_collection_halts(self) -> None:
        bad = Path(self.tmp.name) / "bad.jsonl"
        bad.write_text("{not json\n", encoding="utf-8")
        with self.assertRaises(Exception):
            j1m.verify_collection_completeness(bad)

    def test_pilot_only_collection_halts(self) -> None:
        pilot = Path(self.tmp.name) / "pilot.jsonl"
        _write_collection(pilot, ["1"])
        with self.assertRaises(j1m.J1MeasureHalt):
            j1m.verify_collection_completeness(pilot)

    def test_missing_id_halts(self) -> None:
        incomplete = Path(self.tmp.name) / "incomplete.jsonl"
        _write_collection(incomplete, ["1", "2"])  # "3" missing
        with self.assertRaises(j1m.J1MeasureHalt) as ctx:
            j1m.verify_collection_completeness(incomplete)
        self.assertIn("3", str(ctx.exception))

    def test_extra_id_halts(self) -> None:
        extra = Path(self.tmp.name) / "extra.jsonl"
        _write_collection(extra, ["1", "2", "3", "99"])
        with self.assertRaises(j1m.J1MeasureHalt) as ctx:
            j1m.verify_collection_completeness(extra)
        self.assertIn("99", str(ctx.exception))

    def test_duplicate_id_halts(self) -> None:
        dup = Path(self.tmp.name) / "dup.jsonl"
        _write_collection(dup, ["1", "2", "2", "3"])
        with self.assertRaises(j1m.J1MeasureHalt) as ctx:
            j1m.verify_collection_completeness(dup)
        self.assertIn("2", str(ctx.exception))

    def test_valid_collection_passes_and_hash_is_raw_bytes(self) -> None:
        good = Path(self.tmp.name) / "good.jsonl"
        _write_collection(good, ["1", "2", "3"])
        info = j1m.verify_collection_completeness(good)
        self.assertEqual(info["community_path_count"], 3)
        self.assertEqual(info["collection_sha256"], j1m.collection_sha256(good))

    def test_mixed_prompt_version_halts(self) -> None:
        good = Path(self.tmp.name) / "mixed.jsonl"
        good.parent.mkdir(parents=True, exist_ok=True)
        with good.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({"path": "1", "prompt_version": "riportprompt-j1"}) + "\n")
            handle.write(json.dumps({"path": "2", "prompt_version": "riportprompt-v3"}) + "\n")
        with self.assertRaises(j1m.J1MeasureHalt):
            j1m.verify_single_prompt_version(good)


class ResumeIdentityTests(unittest.TestCase):
    """6, 7: a different collection hash/config at a resumed state path
    is refused, not silently continued."""

    def test_state_store_refuses_resume_on_changed_collection_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            golden_path = Path(tmp) / "golden.jsonl"
            golden_path.write_text("fake golden bytes", encoding="utf-8")
            state_path = Path(tmp) / "state.json"
            collection_info_a = {"collection_path": "x.jsonl", "collection_sha256": "aaa"}
            config_a = j1m.effective_config(collection_info_a, "riportprompt-j1")
            sig_a = j1m.build_run_signature(golden_path, config_a)
            store = state_store.StateStore.load_or_create(state_path, sig_a)
            store.save()

            collection_info_b = {"collection_path": "x.jsonl", "collection_sha256": "bbb"}  # same path, different hash
            config_b = j1m.effective_config(collection_info_b, "riportprompt-j1")
            sig_b = j1m.build_run_signature(golden_path, config_b)
            with self.assertRaises(state_store.StateError):
                state_store.StateStore.load_or_create(state_path, sig_b)


class ConfigMatchesBaselineTests(unittest.TestCase):
    """3, 4: everything except the report collection matches week5-b's
    own FULL config; week5measure's own defaults are untouched."""

    def test_effective_config_reuses_week5measure_values_unchanged(self) -> None:
        info = {"collection_path": "p", "collection_sha256": "h"}
        config = j1m.effective_config(info, "riportprompt-j1")
        self.assertEqual(config["chat_model"], week5measure.CONFIG["chat_model"])
        self.assertEqual(config["temperature"], week5measure.CONFIG["temperature"])
        self.assertEqual(config["global_run_id"], week5measure.CONFIG["global_run_id"])
        self.assertEqual(config["global_reporting_level"], week5measure.CONFIG["global_reporting_level"])
        self.assertEqual(config["correctness_judge_prompt_version"],
                         week5measure.CONFIG["correctness_judge_prompt_version"])
        self.assertEqual(config["faithfulness_judge_prompt_version"],
                         week5measure.CONFIG["faithfulness_judge_prompt_version"])

    def test_week5measure_defaults_untouched(self) -> None:
        self.assertEqual(
            week5measure.CONFIG["global_report_collection"],
            "diagnostics/2026-11-10-phase3-measurement/results/week4-report-v3-collection.jsonl",
        )
        self.assertEqual(week5measure.MODES, ("naiv", "lokalis", "globalis"))


class PathIsolationTests(unittest.TestCase):
    """5, 13: J1-globalis output/ledger paths never collide with week5-b's
    or week6's own paths."""

    def test_output_and_ledger_paths_are_disjoint_from_week5b(self) -> None:
        self.assertNotEqual(j1m.LEDGER_PATH, week5measure.RESULTS_DIR / "week5-b-cost-ledger.json")
        self.assertNotEqual(j1m.STATE_PATH.parent, week5measure.STATE_DIR)
        self.assertNotEqual(j1m.CASES_DIR, week5measure.CASES_DIR)
        self.assertTrue(str(j1m.RESULTS_DIR).endswith("week78-j1-globalis-measure" + __import__("os").sep + "results"))

    def test_results_file_is_its_own_not_week5b_results_jsonl(self) -> None:
        results_path = j1m.RESULTS_DIR / f"results-{j1m.RUN_KIND}.jsonl"
        self.assertNotEqual(results_path, week5measure.RESULTS_DIR / "results.jsonl")


class ModeAndQuestionSelectionTests(unittest.TestCase):
    """1: only globalis mode, no smoke-subsetting -- every loaded question
    becomes a globalis-only case."""

    def test_run_j1_globalis_cases_only_creates_globalis_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            golden_path = Path(tmp) / "golden.jsonl"
            _write_golden(golden_path, ("X01", "X02"))
            questions = list(gs.load_golden_set(golden_path))

            calls = []

            def fake_global_fn(question):
                calls.append(question.id)
                return {"question_id": question.id, "mode": "globalis", "question_text": question.question,
                       "answer": "a", "actual_context": "", "actual_chunk_ids": [], "chunk_ids_traceable": True,
                       "is_proxy_retrieval": True, "error": None, "duration_seconds": 0.1, "run_phase": "test"}

            ctx = week5measure.CaseContext(
                run_phase="test", budget=None, ledger=None, gen_fns={"globalis": fake_global_fn},
                correctness_call_fn_factory=lambda *a: _fake_correctness_call_fn,
                faithfulness_call_fn_factory=lambda *a: _fake_faithfulness_call_fn,
                langfuse_sync_fn=None, case_store_dir=Path(tmp) / "cases",
            )
            store = state_store.StateStore(path=Path(tmp) / "state.json",
                                           signature=state_store.RunSignature("k", "c", "g"))
            j1m.run_j1_globalis_cases(questions, store, ctx)

            self.assertEqual(sorted(calls), ["X01", "X02"])
            self.assertEqual(sorted(store.cases.keys()), ["X01:globalis", "X02:globalis"])


class _FakeJudge:
    def __init__(self, content: str):
        self.content = content
        self.usage_prompt_tokens = 10
        self.usage_completion_tokens = 5


class CollectionReachesExecutorTests(unittest.TestCase):
    """2: the explicit J1 collection path is what the real globalis
    executor actually receives (via the injected gen_fns_builder, which
    mirrors week5measure.build_real_gen_fns's exact signature)."""

    def test_run_measurement_passes_the_j1_collection_reports_to_the_executor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            v3_fixture = tmp_path / "v3.jsonl"
            _write_collection(v3_fixture, ["10", "20"], prompt_version="riportprompt-v3")
            j1_fixture = tmp_path / "j1.jsonl"
            _write_collection(j1_fixture, ["10", "20"], prompt_version="riportprompt-j1")
            golden_path = tmp_path / "golden.jsonl"
            _write_golden(golden_path, ("X01",))

            captured_reports = []

            def fake_gen_fns_builder(budget, phase_ledger, reports, run_phase):
                captured_reports.append(reports)
                def global_fn(question):
                    return {"question_id": question.id, "mode": "globalis", "question_text": question.question,
                           "answer": "a", "actual_context": "", "actual_chunk_ids": [], "chunk_ids_traceable": True,
                           "is_proxy_retrieval": True, "error": None, "duration_seconds": 0.1, "run_phase": run_phase}
                return {"globalis": global_fn}

            fake_reports = ("FAKE_REPORTS_FOR_J1",)

            def fake_judge_builder(budget, phase_ledger, base_label, log_dir):
                is_faithfulness = "faithfulness" in base_label
                fn = _fake_faithfulness_call_fn if is_faithfulness else _fake_correctness_call_fn
                return lambda question_id, mode, step: fn

            with mock.patch.object(j1m, "V3_COLLECTION_PATH", v3_fixture), \
                 mock.patch.object(j1m, "RESULTS_DIR", tmp_path / "results"), \
                 mock.patch.object(j1m, "STATE_DIR", tmp_path / "state"), \
                 mock.patch.object(j1m, "STATE_PATH", tmp_path / "state" / "s.json"), \
                 mock.patch.object(j1m, "CASES_DIR", tmp_path / "results" / "cases"), \
                 mock.patch.object(j1m, "LEDGER_PATH", tmp_path / "results" / "ledger.json"), \
                 mock.patch.object(j1m, "REQUEST_LOG_PATH", tmp_path / "results" / "req.json"), \
                 mock.patch("naive_rag.global_search.load_reports", return_value=fake_reports), \
                 mock.patch.object(j1m, "verify_single_corpus_snapshot", return_value="sha"), \
                 mock.patch.object(j1m, "verify_corpus_matches_disk", return_value=None):
                outcome = j1m.run_measurement(
                    j1_fixture, golden_path=golden_path, sync_langfuse=False,
                    gen_fns_builder=fake_gen_fns_builder,
                    judge_call_fn_factory_builder=fake_judge_builder,
                )

            self.assertEqual(captured_reports, [fake_reports])
            self.assertEqual(outcome["case_count"], 1)
            self.assertEqual(outcome["collection_info"]["collection_path"], str(j1_fixture))


class LangfuseGatingTests(unittest.TestCase):
    """14, 15: Langfuse sync only fires once every expected case has both
    judge scores; no real Langfuse client/call is used."""

    def test_sync_is_a_noop_while_the_group_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "cases"
            case_dir.mkdir(parents=True)
            (case_dir / "X01-globalis.json").write_text(json.dumps(
                {"question_id": "X01", "mode": "globalis", "correctness": {"status": "scored"},
                "faithfulness": None}), encoding="utf-8")  # faithfulness missing -- incomplete

            with mock.patch.object(week5measure, "load_project_env", return_value=None), \
                 mock.patch.object(week5measure, "ensure_langfuse_configured", return_value=None), \
                 mock.patch("langfuse.Langfuse", return_value=mock.Mock()):
                import langfuse_week78 as lw78
                with mock.patch.object(lw78, "sync_j1_globalis_group_once") as fake_sync:
                    sync_fn = j1m.build_real_langfuse_sync_fn(("X01",), case_dir, {"cfg": 1})
                    sync_fn({"question_id": "X01", "mode": "globalis"})
                    fake_sync.assert_not_called()

    def test_sync_fires_once_the_whole_group_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "cases"
            case_dir.mkdir(parents=True)
            row = {"question_id": "X01", "mode": "globalis", "question_text": "q", "answer": "a",
                  "correctness": {"status": "scored"}, "faithfulness": {"score": 1.0}}
            (case_dir / "X01-globalis.json").write_text(json.dumps(row), encoding="utf-8")

            with mock.patch.object(week5measure, "load_project_env", return_value=None), \
                 mock.patch.object(week5measure, "ensure_langfuse_configured", return_value=None), \
                 mock.patch("langfuse.Langfuse", return_value=mock.Mock()):
                import langfuse_week78 as lw78
                with mock.patch.object(lw78, "sync_j1_globalis_group_once") as fake_sync:
                    sync_fn = j1m.build_real_langfuse_sync_fn(("X01",), case_dir, {"cfg": 1})
                    sync_fn(row)
                    fake_sync.assert_called_once()


if __name__ == "__main__":
    unittest.main()
