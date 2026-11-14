"""Shared, persisted cost ledger across the smoke run, the full run, and
any resume -- one 0.50 USD/week project cap, checked before every single
paid call (generation or judge). Reuses the already-verified prices from
the Phase 5 runner (``diagnostics/2026-11-10-phase5-run/run_phase5.py``)
instead of re-stating them.

``SharedCostLedger`` is a drop-in replacement for ``run_phase5.Budget``:
it implements the exact same four methods with the exact same
signatures (``check_generative``, ``check_embedding``, ``record_generative``,
``record_embedding`` -- see ``run_phase5.py``'s ``Budget`` class), since
``generation_runner.py`` passes a ``SharedCostLedger`` instance anywhere
``run_phase5.py``'s own functions (``run_naiv``, ``run_lokalis``'s
``embed_texts`` calls, etc.) expect a ``Budget``. This is not a
reimplementation of the pricing logic under a different name -- it is the
same interface, backed by a persisted, cross-run-sharing ledger instead
of a fresh in-memory ``Budget()`` per process.

No retry logic lives here or anywhere in this package: a failed call is
recorded and the run halts (see measure.py). Missing usage is recorded as
an explicit null with the conservative upper-bound estimate booked
instead -- never as zero consumption.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401  (sys.path side effect; must run before run_phase5 import)
import run_phase5 as phase5  # same prices already verified for Phase 5; not redefined here

CAP_USD_PER_WEEK = 0.50
PRICE_SOURCE = (
    "gpt-4o-mini 0.15/0.60 USD per 1M tokens and text-embedding-3-small "
    "0.02 USD per 1M input tokens: reused unchanged from "
    "diagnostics/2026-11-10-phase5-run/run_phase5.py (" + phase5.PRICE_SOURCE + "). "
    "The correctness/faithfulness judges use the same gpt-4o-mini rate; no "
    "new price was invented for them."
)


class BudgetExceeded(RuntimeError):
    """A call was not issued because it would exceed the shared weekly cap."""


def estimate_tokens(text: str) -> int:
    return phase5.estimate_tokens(text)


@dataclass
class SharedCostLedger:
    """Persisted across process runs. ``path`` is the single shared ledger
    file for the whole week5-b measurement (smoke + full + every resume)."""

    path: Path
    cap_usd: float = CAP_USD_PER_WEEK
    entries: list[dict] = field(default_factory=list)
    spent_usd: float = 0.0

    @classmethod
    def load(cls, path: Path, cap_usd: float = CAP_USD_PER_WEEK) -> "SharedCostLedger":
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
            spent = sum(e["cost_usd"] for e in entries)
            return cls(path=path, cap_usd=data.get("cap_usd", cap_usd), entries=entries, spent_usd=spent)
        return cls(path=path, cap_usd=cap_usd)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"cap_usd": self.cap_usd, "entries": self.entries}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    def _check(self, upper: float, label: str) -> float:
        if self.spent_usd + upper > self.cap_usd:
            raise BudgetExceeded(
                f"{label}: spent={self.spent_usd:.6f} + upper_bound={upper:.6f} "
                f"would exceed shared weekly cap={self.cap_usd}"
            )
        return upper

    # -- run_phase5.Budget-compatible interface (exact same signatures) ----

    def check_generative(self, input_tokens: int, max_output_tokens: int, label: str) -> float:
        """Same formula as ``run_phase5.Budget.check_generative``: an
        upper-bound cost estimate from the (not yet known) output size,
        checked against the SHARED cap rather than a fresh per-process one."""
        upper = (input_tokens / 1_000_000 * phase5.INPUT_PRICE_PER_MTOK
                + max_output_tokens / 1_000_000 * phase5.OUTPUT_PRICE_PER_MTOK)
        return self._check(upper, label)

    def check_embedding(self, tokens: int, label: str) -> float:
        """Same formula as ``run_phase5.Budget.check_embedding``."""
        upper = tokens / 1_000_000 * phase5.EMBEDDING_PRICE_PER_MTOK
        return self._check(upper, label)

    def record_generative(self, actual_usage_prompt: Any, actual_usage_completion: Any, upper_bound: float) -> float:
        """Same signature and same "usage unknown -> book the upper bound,
        never zero" rule as ``run_phase5.Budget.record_generative``."""
        if isinstance(actual_usage_prompt, int) and isinstance(actual_usage_completion, int):
            cost = (actual_usage_prompt / 1_000_000 * phase5.INPUT_PRICE_PER_MTOK
                    + actual_usage_completion / 1_000_000 * phase5.OUTPUT_PRICE_PER_MTOK)
            usage_known = True
        else:
            cost = upper_bound
            usage_known = False
        self._record_entry(step="generative", cost=cost, usage_known=usage_known,
                           actual_prompt_tokens=actual_usage_prompt, actual_completion_tokens=actual_usage_completion)
        return cost

    def record_embedding(self, actual_tokens: Any, upper_bound: float) -> float:
        """Same signature and same "usage unknown -> book the upper bound,
        never zero" rule as ``run_phase5.Budget.record_embedding``."""
        if isinstance(actual_tokens, int):
            cost = actual_tokens / 1_000_000 * phase5.EMBEDDING_PRICE_PER_MTOK
            usage_known = True
        else:
            cost = upper_bound
            usage_known = False
        self._record_entry(step="embedding", cost=cost, usage_known=usage_known,
                           actual_prompt_tokens=actual_tokens, actual_completion_tokens=None)
        return cost

    def _record_entry(self, *, step: str, cost: float, usage_known: bool,
                      actual_prompt_tokens: Any, actual_completion_tokens: Any) -> dict:
        entry = {
            "timestamp": time.time(), "step": step, "cost_usd": round(cost, 6),
            "usage_known": usage_known,
            "note": None if usage_known else
                   "usage unknown from provider response; booked the pre-call upper-bound estimate, not zero",
            "actual_prompt_tokens": actual_prompt_tokens, "actual_completion_tokens": actual_completion_tokens,
        }
        self.entries.append(entry)
        self.spent_usd += cost
        self._save()
        return entry

    def remaining_usd(self) -> float:
        return self.cap_usd - self.spent_usd
