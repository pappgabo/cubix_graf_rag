"""Offline mocks for the J2 measurement entry. No model, database, or network."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import j2_measure_bootstrap  # noqa: F401,E402
import j2_naive_measure as j2  # noqa: E402
import run_phase5 as phase5  # noqa: E402
import state_store  # noqa: E402
from golden_set import load_golden_set  # noqa: E402


def _write_golden(path: Path, rows: list[tuple[str, str]]) -> None:
    lines = []
    for qid, text in rows:
        lines.append(json.dumps({
            "id": qid, "type": "multi-hop", "status": "frozen_w4", "question": text,
            "expected_answer": "A.",
            "criteria": [{"id": f"{qid}-c1", "text": "t", "expected_content": ["a"], "required": True}],
            "evidence_groups": [{"id": f"{qid}-e1", "criterion": f"{qid}-c1", "any_of_chunk_ids": ["gold#1"]}],
            "gold_docs": ["doc"], "notes": "n", "golden_set_version": "test",
            "corpus": {"chunks_file": "x", "chunks_sha256": "abc", "chunk_count": 1},
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _point(text: str, score: float, chunk_id: str):
    return SimpleNamespace(payload={"text": text, "chunk_id": chunk_id}, score=score)


class _FakeJudge:
    def __init__(self, content: str):
        self.content = content
        self.usage_prompt_tokens = 3
        self.usage_completion_tokens = 2
        self.finish_reason = "stop"


def _correctness(system, user, max_tokens):
    criterion_id = json.loads(user)["criteria"][0]["id"]
    return _FakeJudge(json.dumps({
        "criteria": [{"criterion_id": criterion_id, "verdict": "met"}],
        "refused": False, "rubric_conflicts": [], "reasoning": "r",
    }))


def _faithfulness(system, user, max_tokens):
    return _FakeJudge(json.dumps({"claims": [], "reasoning": "r"}))


class SearchUsesJ2Tests(unittest.TestCase):
    def test_one_search_uses_the_common_algorithm_and_records_candidates(self):
        calls = []

        def query_points(vector, limit):
            calls.append((list(vector), limit))
            points = [_point(f"other {i}", 1 - i / 100, f"c{i}") for i in range(limit)]
            points[5] = _point("the 2016 season text", 0.42, "gold#1")
            points[8] = _point("20160 is not a year", 0.2, "long")
            return points

        with mock.patch.object(j2, "retrieve_naive_hits", wraps=j2.retrieve_naive_hits) as spy:
            search_fn, trace = j2.build_j2_search("teammate in 2016", query_points)
            final = search_fn([0.5, 0.25])

        self.assertEqual(calls, [([0.5, 0.25], 12)])
        self.assertEqual(spy.call_args.kwargs["j2_enabled"], True)
        self.assertEqual(trace["final_order"][0], "gold#1")
        self.assertEqual(
            [hit[0].metadata["chunk_id"] for hit in final],
            trace["final_order"],
        )
        gold = trace["candidates"][5]
        self.assertEqual(gold, {
            "chunk_id": "gold#1", "text": "the 2016 season text",
            "score": 0.42, "rank": 6, "year_match": True,
        })
        self.assertFalse(trace["candidates"][8]["year_match"])
        self.assertEqual(final[0][1], 0.42)


class BaselineUnchangedTests(unittest.TestCase):
    def test_run_naiv_without_j2_still_requests_top_4(self):
        seen = []

        class Client:
            def query_points(self, collection, query, limit, with_payload):
                seen.append(limit)
                point = _point("2016 should not widen this query", 0.5, "c0")
                return SimpleNamespace(points=[point])

        class Embed:
            def __init__(self):
                self.embeddings = SimpleNamespace(create=self._create)

            def _create(self, model, input):
                return SimpleNamespace(
                    data=[SimpleNamespace(embedding=[0.1])],
                    usage=SimpleNamespace(total_tokens=4),
                )

        class Chat:
            def invoke(self, messages):
                return SimpleNamespace(
                    content="ok",
                    response_metadata={
                        "model_name": "fake", "finish_reason": "stop",
                        "token_usage": {"prompt_tokens": 2, "completion_tokens": 1},
                    },
                )

        with tempfile.TemporaryDirectory() as tmp:
            phase5.LOG_DIR = Path(tmp)
            budget = phase5.Budget(cap_usd=0.15)
            ledger = phase5.Ledger(run_id="r", path=Path(tmp) / "ledger.json")
            phase5.run_naiv(
                "Q04", "Who was the teammate in 2016?", budget, ledger,
                openai_client=Embed(), qdrant_client=Client(), chat_client=Chat(),
            )
        self.assertEqual(seen, [4])


class PathIsolationTests(unittest.TestCase):
    def test_pilot_and_full_stay_apart_and_off_the_week5_tree(self):
        pilot = j2.paths_for("pilot")
        full = j2.paths_for("full")
        self.assertNotEqual(pilot["state"], full["state"])
        self.assertNotEqual(pilot["request_log"], full["request_log"])
        self.assertNotEqual(pilot["cost_ledger"], full["cost_ledger"])
        for paths in (pilot, full):
            for path in paths.values():
                self.assertNotIn("2026-11-11-week5-b", str(path))

        week5_state = (
            Path(j2.week5measure.STATE_DIR) / "week5-b-state-full.json"
        )
        before = hashlib.sha256(week5_state.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            golden = root / "golden.jsonl"
            _write_golden(golden, [("Q04", "Who was the teammate in 2016?"), ("Q05", "no year")])
            questions = list(load_golden_set(golden))
            paths = {name: root / "pilot" / Path(path).name for name, path in j2.paths_for("pilot").items()}
            paths["cases"] = root / "pilot" / "cases"
            calls = {"n": 0}

            def gen_fn(question):
                calls["n"] += 1
                search_fn, trace = j2.build_j2_search(question.question, lambda vector, limit: [
                    _point("plain", 0.9, "c0"), _point("in 2016", 0.2, "gold#1"),
                ])
                final = search_fn([0.1])
                return {
                    "question_id": question.id, "mode": "naiv", "run_phase": "pilot",
                    "answer": "ok", "error": None, "model_called": True,
                    "actual_context": "ctx", "actual_chunk_ids": trace["final_order"],
                    "chunk_ids_traceable": True, "is_proxy_retrieval": False,
                    "j2_retrieval": {
                        "j2_enabled": True,
                        "candidates": trace["candidates"],
                        "final_order": trace["final_order"],
                        "actual_chunk_ids": [hit[0].metadata["chunk_id"] for hit in final],
                    },
                }

            budget = SimpleNamespace(spent_usd=0.0)
            ledger = SimpleNamespace()
            selected = j2.select_questions(questions, "pilot")
            self.assertEqual([q.id for q in selected], ["Q04"])
            j2.execute_j2(
                "pilot", selected, golden, paths,
                gen_fn=gen_fn, budget=budget, ledger=ledger,
                correctness_call_fn_factory=lambda *args: _correctness,
                faithfulness_call_fn_factory=lambda *args: _faithfulness,
            )
            saved = json.loads((paths["cases"] / "Q04-naiv.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["j2_retrieval"]["final_order"][0], "gold#1")
            self.assertEqual(saved["j2_retrieval"]["actual_chunk_ids"][0], "gold#1")
            self.assertEqual(saved["actual_chunk_ids"][0], "gold#1")
            state = json.loads(paths["state"].read_text(encoding="utf-8"))
            self.assertEqual(state["signature"]["run_kind"], "pilot")
            self.assertEqual(state["signature"]["config_sha256"], state_store.config_hash(j2.effective_config()))
            self.assertTrue(j2.effective_config()["j2_enabled"])
            self.assertEqual(calls["n"], 1)
            j2.execute_j2(
                "pilot", selected, golden, paths,
                gen_fn=gen_fn, budget=budget, ledger=ledger,
                correctness_call_fn_factory=lambda *args: _correctness,
                faithfulness_call_fn_factory=lambda *args: _faithfulness,
            )
            self.assertEqual(calls["n"], 1)
            other = state_store.RunSignature("full", state["signature"]["config_sha256"], state["signature"]["golden_set_sha256"])
            with self.assertRaises(state_store.StateError):
                state_store.StateStore.load_or_create(paths["state"], other)
        self.assertEqual(hashlib.sha256(week5_state.read_bytes()).hexdigest(), before)


class PairWiringTests(unittest.TestCase):
    def test_switch_and_retrieval_limit(self):
        def limits(enabled, question):
            calls = []

            def query_points(vector, limit):
                calls.append(limit)
                return [_point("2016 and 2017", 0.5, "c0")]

            search_fn, trace = j2.build_j2_search(question, query_points, j2_enabled=enabled)
            search_fn([0.1])
            self.assertIs(trace["j2_enabled"], enabled)
            return calls

        self.assertEqual(limits(False, "teammate in 2016"), [4])
        self.assertEqual(limits(True, "teammate in 2016"), [12])
        self.assertEqual(limits(True, "2016 and 2017"), [4])
        self.assertEqual(limits(True, "no year here"), [4])

    def test_shared_settings_separated_outputs_and_shared_cap(self):
        baseline = j2.pair_config("baseline", "idx")
        j2_config = j2.pair_config("j2", "idx")
        self.assertEqual(
            {key for key in baseline if baseline[key] != j2_config[key]},
            {"variant", "j2_enabled"},
        )
        self.assertEqual(baseline["chat_model"], "gpt-4o-mini")
        self.assertEqual(baseline["embedding_model"], "text-embedding-3-small")
        self.assertEqual(baseline["final_k"], 4)
        self.assertEqual(baseline["shared_cost_cap_usd"], 0.50)
        self.assertFalse(baseline["j2_enabled"])
        self.assertTrue(j2_config["j2_enabled"])
        self.assertTrue(baseline["generation_prompt_sha256"])
        self.assertEqual(baseline["correctness_prompt_sha256"], j2_config["correctness_prompt_sha256"])
        self.assertEqual(baseline["faithfulness_prompt_sha256"], j2_config["faithfulness_prompt_sha256"])

        base_paths = j2.pair_paths("baseline")
        j2_paths = j2.pair_paths("j2")
        self.assertNotEqual(base_paths["state"], j2_paths["state"])
        self.assertNotEqual(base_paths["results"], j2_paths["results"])
        self.assertNotEqual(base_paths["request_log"], j2_paths["request_log"])
        self.assertEqual(base_paths["cost_ledger"], j2_paths["cost_ledger"])
        self.assertEqual(base_paths["fingerprint"], j2_paths["fingerprint"])
        self.assertNotEqual(base_paths["state"], j2.paths_for("pilot")["state"])
        self.assertNotEqual(base_paths["results"], j2.paths_for("full")["results"])

        import cost_guard
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "shared.json"
            first = j2.RunTaggedBudget(cost_guard.SharedCostLedger.load(ledger_path), "pair-baseline-full")
            upper = first.check_embedding(1000, "naiv-query-Q01")
            first.record_embedding(1000, upper)
            second = j2.RunTaggedBudget(cost_guard.SharedCostLedger.load(ledger_path), "pair-j2-full")
            self.assertEqual(second.cap_usd, 0.50)
            self.assertGreater(second.spent_usd, 0)
            saved = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["cap_usd"], 0.50)
            self.assertEqual(saved["entries"][0]["label"], "pair-baseline-full|naiv-query-Q01")
            with self.assertRaises(cost_guard.BudgetExceeded):
                second.check_generative(10_000_000, 10_000_000, "naiv-Q01")

    def test_config_or_index_mismatch_blocks_start_and_resume(self):
        with self.assertRaises(j2.J2MeasureHalt):
            j2.assert_same_index({"collection": "a"}, {"collection": "b"})
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"
            with self.assertRaises(j2.J2MeasureHalt):
                j2.load_recorded_index(missing)
            golden = Path(tmp) / "golden.jsonl"
            _write_golden(golden, [("Q04", "Who was the teammate in 2016?")])
            base = j2.pair_signature("baseline", golden, "idx")
            other = j2.pair_signature("j2", golden, "idx")
            self.assertNotEqual(base.config_sha256, other.config_sha256)
            self.assertNotEqual(base.run_kind, other.run_kind)
            state = Path(tmp) / "state.json"
            state_store.StateStore.load_or_create(state, base).save()
            with self.assertRaises(state_store.StateError):
                state_store.StateStore.load_or_create(state, other)
        self.assertEqual(j2.main(["run", "--full"]), 1)
        self.assertEqual(j2.main(["run", "--variant", "baseline"]), 1)


class PairOutputDirTests(unittest.TestCase):
    def test_empty_directory_gets_request_log_state_and_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {
                "results": root / "results",
                "cases": root / "results" / "cases",
                "state": root / "state" / "state.json",
                "request_log": root / "results" / "j2-pair-request-log.json",
                "logs": root / "logs",
                "judge_logs": root / "logs" / "judges",
                "report": root / "results" / "report.md",
                "results_jsonl": root / "results" / "results.jsonl",
                "cost_ledger": root / "shared" / "ledger.json",
                "fingerprint": root / "shared" / "fingerprint.json",
            }
            self.assertFalse(paths["request_log"].parent.exists())
            self.assertFalse(paths["state"].parent.exists())
            j2.ensure_pair_output_dirs(paths)
            golden = root / "golden.jsonl"
            _write_golden(golden, [("Q01", "How many titles?")])
            questions = list(load_golden_set(golden))
            calls = {"embed": 0, "chat": 0}

            def gen_fn(question):
                self.assertTrue(paths["request_log"].parent.is_dir())
                calls["embed"] += 1
                phase5.Ledger(run_id="pair-baseline-full", path=paths["request_log"]).add(
                    step="embedding", label="pair-baseline-full|naiv-query-Q01",
                    actual_tokens=11, cost_usd=0.0, status="success",
                )
                calls["chat"] += 1
                return {
                    "question_id": question.id, "mode": "naiv", "run_phase": "pair-baseline-full",
                    "answer": "ok", "error": None, "model_called": True,
                    "actual_context": "ctx", "actual_chunk_ids": ["c0"],
                    "chunk_ids_traceable": True, "is_proxy_retrieval": False,
                }

            j2.execute_j2(
                "pair-baseline-full", questions, golden, paths,
                gen_fn=gen_fn, budget=SimpleNamespace(spent_usd=0.0), ledger=SimpleNamespace(),
                correctness_call_fn_factory=lambda *args: _correctness,
                faithfulness_call_fn_factory=lambda *args: _faithfulness,
            )
            self.assertEqual(calls, {"embed": 1, "chat": 1})
            self.assertTrue(paths["request_log"].is_file())
            self.assertTrue(paths["state"].is_file())
            self.assertTrue(paths["results_jsonl"].is_file())
            self.assertTrue((paths["cases"] / "Q01-naiv.json").is_file())
            self.assertTrue(paths["judge_logs"].is_dir())


if __name__ == "__main__":
    unittest.main()
