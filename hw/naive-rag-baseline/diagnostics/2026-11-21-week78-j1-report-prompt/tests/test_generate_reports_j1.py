"""Offline checks for the J1 report-prompt variant -- fake call_fn, no
real API call. Confirms prompt selection/separation, artifact-identity
guarding, and path isolation from v3; does NOT and cannot confirm that
the model actually preserves a numeric fact (see module docstring of
generate_reports_j1.py and docs/week78-javitasok.md)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import j1_bootstrap  # noqa: F401,E402
import generate_reports_j1 as j1  # noqa: E402
import generate_reports_v3 as v3  # noqa: E402


def _fake_response(content: dict, *, prompt_tokens=100, completion_tokens=50):
    return SimpleNamespace(
        content=json.dumps(content),
        response_metadata={"model_name": "gpt-4o-mini-test", "finish_reason": "stop",
                           "token_usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}},
        usage_metadata={},
    )


VALID_REPORT = {
    "summary": "Test community summary.",
    "key_statements": [{"statement": "Entity X holds Y titles.", "evidence_ids": ["N001"]}],
}


class PromptSeparationTests(unittest.TestCase):
    """1 & 2: old/new prompt version separately selectable; the numeric
    rule exists only in J1's prompt."""

    def test_v3_and_j1_prompts_are_separately_selectable_and_differ(self) -> None:
        v3_prompt = v3.extract_system_prompt(v3.TEMPLATE_V3_PATH.read_text(encoding="utf-8"))
        j1_prompt = j1.j1_system_prompt()
        self.assertNotEqual(v3_prompt, j1_prompt)
        self.assertNotEqual(j1.PROMPT_VERSION, v3.PROMPT_VERSION)

    def test_numeric_preservation_rule_exists_only_in_j1(self) -> None:
        v3_prompt = v3.extract_system_prompt(v3.TEMPLATE_V3_PATH.read_text(encoding="utf-8"))
        j1_prompt = j1.j1_system_prompt()
        marker = "explicit, factual, quantitative result"
        self.assertNotIn(marker, v3_prompt)
        self.assertIn(marker, j1_prompt)

    def test_j1_prompt_is_v3_prompt_plus_exactly_one_new_paragraph(self) -> None:
        v3_prompt = v3.extract_system_prompt(v3.TEMPLATE_V3_PATH.read_text(encoding="utf-8"))
        j1_prompt = j1.j1_system_prompt()
        new_paragraph = (
            "If the supplied records state an explicit, factual, quantitative result or\n"
            "aggregate performance for an entity -- for example a title count, a win\n"
            "count, a record, a podium or points count, a duration, or another clearly\n"
            "quantitative result or aggregate-performance figure -- preserve that fact\n"
            "as its own key statement. Keep the entity, the number, the measured\n"
            "category, and any explicit time or validity qualifier the source states;\n"
            "none of these may be dropped, changed, or replaced by a general career,\n"
            "team, or success summary that omits the number. Do not calculate a\n"
            "missing figure, infer a new number, turn a year into a result count, or\n"
            "merge different categories of number together."
        )
        self.assertIn(new_paragraph, j1_prompt)
        reconstructed = j1_prompt.replace("\n\n" + new_paragraph, "")
        self.assertEqual(reconstructed, v3_prompt)


class UnchangedSettingsTests(unittest.TestCase):
    """4: model, settings, token budget, schema unchanged vs v3."""

    def test_model_and_generation_settings_match_v3(self) -> None:
        self.assertEqual(j1.REQUESTED_MODEL, v3.REQUESTED_MODEL)
        self.assertEqual(j1.MAX_OUTPUT_TOKENS, v3.MAX_OUTPUT_TOKENS)
        self.assertEqual(j1.TEMPERATURE, 0)
        self.assertEqual(j1.MAX_RETRIES, 0)
        self.assertEqual(j1.RUN_ID, v3.RUN_ID)

    def test_j1_input_is_the_frozen_v3_input_with_only_prompt_version_swapped(self) -> None:
        user_text, record_chunk_map, v3_input_hash = j1.build_j1_payload("4")
        v3_input_path = v3.RESULTS_DIR / "week4-report-v3-input-4.json"
        v3_payload = json.loads(v3_input_path.read_text(encoding="utf-8"))
        j1_payload = json.loads(user_text)
        self.assertEqual(j1_payload["prompt_version"], "riportprompt-j1")
        j1_payload_without_version = {k: v for k, v in j1_payload.items() if k != "prompt_version"}
        v3_payload_without_version = {k: v for k, v in v3_payload.items() if k != "prompt_version"}
        self.assertEqual(j1_payload_without_version, v3_payload_without_version)
        self.assertTrue(record_chunk_map)
        self.assertTrue(v3_input_hash)


class SentPromptContainsRuleTests(unittest.TestCase):
    """3: the rule is actually present in the text handed to call_fn."""

    def test_call_fn_receives_system_prompt_with_the_numeric_rule(self) -> None:
        captured = []

        def fake_call_fn(system_prompt: str, user_text: str):
            captured.append((system_prompt, user_text))
            return _fake_response(VALID_REPORT)

        with tempfile.TemporaryDirectory() as tmp:
            j1.RESULTS_DIR = Path(tmp)
            summary = j1.run_j1_reports("pilot", call_fn=fake_call_fn, community_paths=("4",))

        self.assertEqual(len(captured), 1)
        sent_system_prompt, sent_user_text = captured[0]
        self.assertIn("explicit, factual, quantitative result", sent_system_prompt)
        self.assertEqual(json.loads(sent_user_text)["prompt_version"], "riportprompt-j1")
        self.assertEqual(summary["successes"], ["4"])


class PathIsolationTests(unittest.TestCase):
    """5 & 7: old/new output paths never mix; no v3 artifact can be
    overwritten by this module's own write paths."""

    def test_j1_paths_differ_from_and_do_not_overlap_v3_paths(self) -> None:
        paths = j1.paths_for_run_kind("full")
        self.assertNotEqual(paths["ledger_path"], v3.LEDGER_PATH)
        self.assertNotEqual(paths["collection_path"], v3.COLLECTION_PATH)
        j1.assert_no_v3_path_overlap(paths)  # must not raise

    def test_assert_no_v3_path_overlap_raises_if_a_path_points_under_v3_results(self) -> None:
        bad_paths = {"ledger_path": v3.RESULTS_DIR / "sneaky.json"}
        with self.assertRaises(j1.J1Halt):
            j1.assert_no_v3_path_overlap(bad_paths)

    def test_run_refuses_to_overwrite_an_existing_j1_report_file(self) -> None:
        def fake_call_fn(system_prompt, user_text):
            return _fake_response(VALID_REPORT)

        with tempfile.TemporaryDirectory() as tmp:
            j1.RESULTS_DIR = Path(tmp)
            first = j1.run_j1_reports("pilot", call_fn=fake_call_fn, community_paths=("4",))
            self.assertIsNone(first["halted_reason"])

            # Simulate a second, independent invocation attempting the same
            # community without clearing the ledger -- must not re-call or overwrite.
            calls = []

            def counting_call_fn(system_prompt, user_text):
                calls.append(1)
                return _fake_response(VALID_REPORT)

            second = j1.run_j1_reports("pilot", call_fn=counting_call_fn, community_paths=("4",))
            self.assertEqual(calls, [])  # already in ledger as success -- skipped, not re-called
            self.assertEqual(second["successes"], ["4"])


class IdentityGuardTests(unittest.TestCase):
    """6: a mismatched prompt/version/input identity halts before any call."""

    def test_mismatched_existing_run_metadata_halts_before_any_call(self) -> None:
        calls = []

        def fake_call_fn(system_prompt, user_text):
            calls.append(1)
            return _fake_response(VALID_REPORT)

        with tempfile.TemporaryDirectory() as tmp:
            j1.RESULTS_DIR = Path(tmp)
            paths = j1.paths_for_run_kind("pilot")
            paths["run_metadata_path"].parent.mkdir(parents=True, exist_ok=True)
            paths["run_metadata_path"].write_text(json.dumps({
                "prompt_version": "riportprompt-j1", "prompt_sha256": "deadbeef",
                "input_run_id": j1.RUN_ID, "community_paths": ["4"],
            }), encoding="utf-8")

            with self.assertRaises(j1.J1Halt):
                j1.run_j1_reports("pilot", call_fn=fake_call_fn, community_paths=("4",))
            self.assertEqual(calls, [])  # halted before any model call

    def test_matching_metadata_on_first_write_does_not_halt(self) -> None:
        def fake_call_fn(system_prompt, user_text):
            return _fake_response(VALID_REPORT)

        with tempfile.TemporaryDirectory() as tmp:
            j1.RESULTS_DIR = Path(tmp)
            summary = j1.run_j1_reports("pilot", call_fn=fake_call_fn, community_paths=("4",))
            self.assertIsNone(summary["halted_reason"])


if __name__ == "__main__":
    unittest.main()
