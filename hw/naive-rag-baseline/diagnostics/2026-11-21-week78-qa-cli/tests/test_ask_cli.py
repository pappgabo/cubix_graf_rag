"""Offline checks for ask_cli.py's dispatch wiring -- fake mode_fn
builders/raw_caller, no real API/DB call. Does not re-test
`naive_rag.answer_question.answer_question` itself (already covered by
tests/test_answer_question.py) -- only ask_cli's own real-client wiring,
readiness gating, and cost-guard interaction."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import week78_bootstrap  # noqa: F401,E402
import ask_cli  # noqa: E402
import cost_guard  # noqa: E402


class FakeLedger:
    """Minimal stand-in for cost_guard.SharedCostLedger's
    entries/spent_usd/remaining_usd surface, for tests that only care
    about dispatch/branch wiring, not real cap arithmetic."""

    def __init__(self) -> None:
        self.entries: list[dict] = []
        self.spent_usd = 0.0
        self.cap_usd = 1.0

    def remaining_usd(self) -> float:
        return self.cap_usd - self.spent_usd


def _fake_router_response(mode: str):
    return SimpleNamespace(
        content=json.dumps({"mode": mode, "reasoning": "test reasoning"}),
        response_metadata={"model_name": "gpt-4o-mini-test", "finish_reason": "stop",
                           "token_usage": {"prompt_tokens": 5, "completion_tokens": 5}},
        usage_metadata={},
    )


def _all_ready_builder(calls: list[str]):
    """A fake mode_fn_builder: every mode in `only` (or all four) is
    "ready", each real-client builder is replaced with a fake that
    records which branch actually ran."""

    def builder(cost_ledger, request_log, *, only=None):
        wanted = only if only is not None else set(ask_cli.MODES)

        def make(name):
            def fn(question_text: str) -> dict:
                calls.append(name)
                return {"answer": f"{name}-answer"}
            return fn

        mode_fns = {name: make(name) for name in ask_cli.MODES if name in wanted}
        return mode_fns, {}
    return builder


class RouterDispatchTests(unittest.TestCase):
    """1. Each of the router's four possible decisions invokes the
    matching real-client branch, and only that one."""

    def test_each_router_decision_invokes_only_its_own_branch(self) -> None:
        for mode in ask_cli.MODES:
            calls: list[str] = []

            def raw_caller(messages, params, mode=mode):
                return _fake_router_response(mode)

            outcome = ask_cli.dispatch(
                "auto", "question text", cost_ledger=FakeLedger(), request_log=None,
                mode_fn_builder=_all_ready_builder(calls),
                router_raw_caller_builder=lambda cl: raw_caller,
            )
            self.assertEqual(calls, [mode])
            self.assertEqual(outcome["record"]["mode"], mode)
            self.assertEqual(outcome["record"]["mode_source"], "router")
            self.assertIsNone(outcome["error"])


class ExplicitModeTests(unittest.TestCase):
    """2. All four explicit modes run without ever calling the router."""

    def test_all_four_explicit_modes_run_without_a_router_call(self) -> None:
        for mode in ask_cli.MODES:
            calls: list[str] = []
            router_calls: list[str] = []

            def raw_caller_builder(cost_ledger):
                router_calls.append("built")

                def raw_caller(messages, params):
                    router_calls.append("called")
                    return _fake_router_response(mode)
                return raw_caller

            outcome = ask_cli.dispatch(
                mode, "question text", cost_ledger=FakeLedger(), request_log=None,
                mode_fn_builder=_all_ready_builder(calls),
                router_raw_caller_builder=raw_caller_builder,
            )
            self.assertEqual(calls, [mode])
            self.assertEqual(router_calls, [])  # the router raw_caller is never even built
            self.assertEqual(outcome["record"]["mode_source"], "explicit")
            self.assertIsNone(outcome["error"])


class PrerequisiteMissingTests(unittest.TestCase):
    """3. A missing prerequisite/artifact produces no paid call."""

    def test_missing_prerequisite_for_explicit_mode_makes_no_paid_call(self) -> None:
        def unready_builder(cost_ledger, request_log, *, only=None):
            mode = next(iter(only))
            return {}, {mode: f"{mode}: fake missing artifact"}

        ledger = FakeLedger()
        outcome = ask_cli.dispatch(
            "drift", "question text", cost_ledger=ledger, request_log=None,
            mode_fn_builder=unready_builder,
            router_raw_caller_builder=lambda cl: (_ for _ in ()).throw(
                AssertionError("router must not be built for an explicit mode")),
        )
        self.assertIsNotNone(outcome["error"])
        self.assertIn("fake missing artifact", outcome["error"])
        self.assertEqual(ledger.entries, [])  # no cost recorded
        self.assertEqual(outcome["new_ledger_entries"], [])

    def test_missing_prerequisite_for_auto_mode_is_reported_not_crashed(self) -> None:
        def partially_ready_builder(cost_ledger, request_log, *, only=None):
            return {}, {"naiv": "naiv: fake missing artifact", "lokalis": "lokalis: fake missing artifact",
                       "globalis": "globalis: fake missing artifact", "drift": "drift: fake missing artifact"}

        def raw_caller(messages, params):
            return _fake_router_response("drift")

        outcome = ask_cli.dispatch(
            "auto", "question text", cost_ledger=FakeLedger(), request_log=None,
            mode_fn_builder=partially_ready_builder,
            router_raw_caller_builder=lambda cl: raw_caller,
        )
        self.assertIsNone(outcome["error"])  # answer_question itself handles this, not an exception
        self.assertIsNone(outcome["record"]["result"])
        self.assertIn("error", outcome["record"])


class CostGuardRejectionTests(unittest.TestCase):
    """4. A cost-guard rejection (BudgetExceeded) prevents the paid call,
    using the real SharedCostLedger (same class ask_cli uses in
    production), not a fake, so the cap arithmetic itself is exercised."""

    def test_budget_exceeded_before_any_call_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = cost_guard.SharedCostLedger.load(Path(tmp) / "ledger.json", cap_usd=0.0000001)

            def over_cap_fn(question_text: str) -> dict:
                ledger.check_generative(1_000_000, 1_000_000, "fake-expensive-call")
                raise AssertionError("must never reach the simulated paid call")

            def ready_builder(cost_ledger, request_log, *, only=None):
                return {"drift": over_cap_fn}, {}

            outcome = ask_cli.dispatch(
                "drift", "question text", cost_ledger=ledger, request_log=None,
                mode_fn_builder=ready_builder,
                router_raw_caller_builder=lambda cl: (_ for _ in ()).throw(
                    AssertionError("router must not be built for an explicit mode")),
            )
            self.assertIsNotNone(outcome["error"])
            self.assertIn("cost guard rejected", outcome["error"])
            self.assertEqual(ledger.entries, [])  # nothing recorded -- rejected before the call
            self.assertEqual(ledger.spent_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
