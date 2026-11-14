"""Per-case step state for resumability.

A "run" is identified by a signature: the run kind (smoke|full), a hash of
the effective configuration (model/top_k/collection/budgets/prompt
versions), and the golden-set file's own sha256. Resuming only makes
sense when all three match what a saved state file already recorded --
otherwise this is a different measurement and must not silently reuse
old answers.

Four independent step flags per (question_id, mode) case:
``answer_saved``, ``criteria_scored``, ``faithfulness_scored``,
``langfuse_synced``. A case resumes by re-running only the first False
step it finds, in that fixed order. An evaluation or upload error never
forces the already-saved answer to be regenerated.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STEP_ORDER = ("answer_saved", "criteria_scored", "faithfulness_scored", "langfuse_synced")


class StateError(ValueError):
    """The saved state file does not match the requested run signature."""


def config_hash(config: dict[str, Any]) -> str:
    """Stable hash of the effective configuration dict (sorted keys, no
    secrets -- callers must not put API keys in here)."""
    blob = json.dumps(config, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class RunSignature:
    run_kind: str  # "smoke" | "full"
    config_sha256: str
    golden_set_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "run_kind": self.run_kind,
            "config_sha256": self.config_sha256,
            "golden_set_sha256": self.golden_set_sha256,
        }

    def matches(self, other: dict[str, str]) -> bool:
        return self.as_dict() == other


@dataclass
class CaseState:
    question_id: str
    mode: str
    answer_saved: bool = False
    criteria_scored: bool = False
    faithfulness_scored: bool = False
    langfuse_synced: bool = False
    last_error: dict[str, Any] | None = None

    def key(self) -> str:
        return f"{self.question_id}:{self.mode}"

    def next_step(self) -> str | None:
        for step in STEP_ORDER:
            if not getattr(self, step):
                return step
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id, "mode": self.mode,
            "answer_saved": self.answer_saved, "criteria_scored": self.criteria_scored,
            "faithfulness_scored": self.faithfulness_scored, "langfuse_synced": self.langfuse_synced,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CaseState":
        return cls(
            question_id=data["question_id"], mode=data["mode"],
            answer_saved=data.get("answer_saved", False),
            criteria_scored=data.get("criteria_scored", False),
            faithfulness_scored=data.get("faithfulness_scored", False),
            langfuse_synced=data.get("langfuse_synced", False),
            last_error=data.get("last_error"),
        )


@dataclass
class StateStore:
    path: Path
    signature: RunSignature
    cases: dict[str, CaseState] = field(default_factory=dict)

    @classmethod
    def load_or_create(cls, path: Path, signature: RunSignature) -> "StateStore":
        """Raises StateError if a saved file exists but its signature
        differs from the requested one -- callers must not silently reuse
        state from a different configuration or golden-set version."""
        if not path.exists():
            return cls(path=path, signature=signature)
        data = json.loads(path.read_text(encoding="utf-8"))
        saved_sig = data.get("signature", {})
        if not signature.matches(saved_sig):
            raise StateError(
                f"{path}: saved run signature {saved_sig} does not match "
                f"the requested one {signature.as_dict()} -- this is a "
                "different measurement, not a resume"
            )
        cases = {k: CaseState.from_dict(v) for k, v in data.get("cases", {}).items()}
        return cls(path=path, signature=signature, cases=cases)

    def get_or_create(self, question_id: str, mode: str) -> CaseState:
        case = CaseState(question_id=question_id, mode=mode)
        return self.cases.setdefault(case.key(), case)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({
                "signature": self.signature.as_dict(),
                "cases": {k: v.as_dict() for k, v in self.cases.items()},
            }, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    def summary(self) -> dict[str, int]:
        counts = {step: 0 for step in STEP_ORDER}
        for case in self.cases.values():
            for step in STEP_ORDER:
                if getattr(case, step):
                    counts[step] += 1
        return counts
