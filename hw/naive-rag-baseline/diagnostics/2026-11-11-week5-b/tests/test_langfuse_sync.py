import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import langfuse_sync as ls


class FakeLangfuseClient:
    """No network, no model call -- records every run_experiment call it
    received and actually invokes task/evaluators locally so tests can
    prove they never call anything beyond reading the item's metadata."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_experiment(self, *, name, run_name, data, task, evaluators,
                       experiment_id=None, metadata=None, **kwargs):
        results = []
        for item in data:
            output = task(item=item)
            evals = [e(input=item["input"], output=output, expected_output=item.get("expected_output"),
                      metadata=item.get("metadata")) for e in evaluators]
            results.append({"item": item, "output": output, "evaluations": evals})
        self.calls.append({
            "name": name, "run_name": run_name, "experiment_id": experiment_id,
            "data": data, "metadata": metadata,
        })
        return {"results": results}


def _record(question_id="Q01", mode="naiv", **overrides) -> ls.LocalRecord:
    base = dict(
        question_id=question_id, mode=mode, question_text="Q?", answer="A.", expected_answer="A.",
        metadata={"correctness_label": "helyes", "faithfulness_score": 0.8, "retrieval_ratio": 1.0,
                 "retrieval_is_proxy": False},
    )
    base.update(overrides)
    return ls.LocalRecord(**base)


class ModeRunNameTests(unittest.TestCase):
    def test_distinct_per_phase_and_mode(self) -> None:
        names = {
            ls.mode_run_name("smoke", "naiv"), ls.mode_run_name("smoke", "lokalis"),
            ls.mode_run_name("smoke", "globalis"), ls.mode_run_name("full", "naiv"),
        }
        self.assertEqual(len(names), 4)


class DeterministicExperimentIdTests(unittest.TestCase):
    def test_stable_for_same_run_name_offline(self) -> None:
        # No network call: Langfuse.create_trace_id(seed=...) is a pure hash.
        first = ls.deterministic_experiment_id("week5-b-smoke-naiv")
        second = ls.deterministic_experiment_id("week5-b-smoke-naiv")
        self.assertEqual(first, second)

    def test_differs_for_different_run_names(self) -> None:
        a = ls.deterministic_experiment_id("week5-b-smoke-naiv")
        b = ls.deterministic_experiment_id("week5-b-smoke-lokalis")
        self.assertNotEqual(a, b)


class SyncModeGroupTests(unittest.TestCase):
    def test_one_call_covers_the_whole_group_not_one_per_record(self) -> None:
        client = FakeLangfuseClient()
        records = [_record("Q01"), _record("Q07"), _record("Q11")]
        ls.sync_mode_group(client, run_phase="smoke", mode="naiv", records=records)
        self.assertEqual(len(client.calls), 1)  # one run_experiment call total
        self.assertEqual(len(client.calls[0]["data"]), 3)  # all three questions in it

    def test_run_name_and_experiment_id_are_mode_scoped(self) -> None:
        client = FakeLangfuseClient()
        ls.sync_mode_group(client, run_phase="smoke", mode="lokalis", records=[_record("Q01", "lokalis")])
        call = client.calls[0]
        self.assertEqual(call["run_name"], "week5-b-smoke-lokalis")
        self.assertEqual(call["experiment_id"], ls.deterministic_experiment_id("week5-b-smoke-lokalis"))

    def test_task_returns_precomputed_answer_without_model_call(self) -> None:
        client = FakeLangfuseClient()
        ls.sync_mode_group(client, run_phase="smoke", mode="naiv", records=[_record()])
        output = client.calls[0]["data"][0]["metadata"]["precomputed_answer"]
        self.assertEqual(output, "A.")


class SyncModeGroupOnceTests(unittest.TestCase):
    def test_second_call_with_identical_group_is_skipped(self) -> None:
        client = FakeLangfuseClient()
        records = [_record("Q01"), _record("Q07"), _record("Q11")]
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "smoke-naiv.json"
            first = ls.sync_mode_group_once(client, marker, run_phase="smoke", mode="naiv", records=records)
            second = ls.sync_mode_group_once(client, marker, run_phase="smoke", mode="naiv", records=records)
            self.assertFalse(first["skipped"])
            self.assertTrue(second["skipped"])
            self.assertEqual(len(client.calls), 1)  # no duplicate run_experiment call

    def test_changed_group_membership_triggers_a_new_call(self) -> None:
        client = FakeLangfuseClient()
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "smoke-naiv.json"
            ls.sync_mode_group_once(client, marker, run_phase="smoke", mode="naiv",
                                    records=[_record("Q01"), _record("Q07")])
            ls.sync_mode_group_once(client, marker, run_phase="smoke", mode="naiv",
                                    records=[_record("Q01"), _record("Q07"), _record("Q11")])
            self.assertEqual(len(client.calls), 2)

    def test_marker_persists_across_separate_invocations(self) -> None:
        """Simulates a resumed process: a fresh call to sync_mode_group_once
        with the same marker path (as if the process restarted) still
        recognizes the group as already synced."""
        client = FakeLangfuseClient()
        records = [_record("Q01"), _record("Q07"), _record("Q11")]
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "smoke-naiv.json"
            ls.sync_mode_group_once(client, marker, run_phase="smoke", mode="naiv", records=records)
            # fresh client instance + fresh call, only the marker file carries over
            another_client = FakeLangfuseClient()
            result = ls.sync_mode_group_once(another_client, marker, run_phase="smoke", mode="naiv", records=records)
            self.assertTrue(result["skipped"])
            self.assertEqual(len(another_client.calls), 0)

    def test_different_modes_do_not_share_a_marker(self) -> None:
        client = FakeLangfuseClient()
        with tempfile.TemporaryDirectory() as tmp:
            marker_naiv = Path(tmp) / "smoke-naiv.json"
            marker_lokalis = Path(tmp) / "smoke-lokalis.json"
            ls.sync_mode_group_once(client, marker_naiv, run_phase="smoke", mode="naiv",
                                    records=[_record("Q01", "naiv")])
            ls.sync_mode_group_once(client, marker_lokalis, run_phase="smoke", mode="lokalis",
                                    records=[_record("Q01", "lokalis")])
            self.assertEqual(len(client.calls), 2)


class EvaluatorTests(unittest.TestCase):
    def test_proxy_retrieval_uses_separate_metric_name(self) -> None:
        proxy_eval = ls.retrieval_ratio_evaluator()
        result = proxy_eval(input="q", output="a", expected_output="e",
                            metadata={"retrieval_ratio": 0.5, "retrieval_is_proxy": True})
        self.assertEqual(result.name, "retrieval_ratio_proxy")

    def test_non_proxy_retrieval_uses_plain_metric_name(self) -> None:
        real_eval = ls.retrieval_ratio_evaluator()
        result = real_eval(input="q", output="a", expected_output="e",
                           metadata={"retrieval_ratio": 0.5, "retrieval_is_proxy": False})
        self.assertEqual(result.name, "retrieval_ratio")

    def test_faithfulness_na_is_categorical_not_numeric_zero(self) -> None:
        evaluator = ls.faithfulness_score_evaluator()
        result = evaluator(input="q", output="a", expected_output="e",
                           metadata={"faithfulness_score": "n/a"})
        self.assertEqual(result.value, "n/a")


if __name__ == "__main__":
    unittest.main()
