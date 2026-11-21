"""Week78-named Langfuse sync, built on week5-b's generic Langfuse pieces
(same pattern as week6's `langfuse_week6.py`). `langfuse_sync.py`
(week5-b, unchanged) hardcodes its own experiment/run names to the
``"week5-b-"`` prefix -- calling it unchanged would silently file every
J1-globalis experiment under those week5-b names. Only the naming and
the two thin orchestration functions are redefined here, with a
``"week78-j1-globalis-"`` prefix; everything else (`LocalRecord`,
`to_experiment_item`, `make_lookup_task`, `DEFAULT_EVALUATORS`,
`deterministic_experiment_id`) is reused unmodified from `langfuse_sync`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import j1_measure_bootstrap  # noqa: F401
import langfuse_sync as ls

EXPERIMENT_NAME = "week78-j1-globalis-full"


def run_name(run_phase: str) -> str:
    return f"week78-j1-globalis-{run_phase}"


def sync_j1_globalis_group(
    client: Any, *, run_phase: str, records: Iterable[ls.LocalRecord],
    config_metadata: dict[str, Any] | None = None,
) -> Any:
    records = list(records)
    rn = run_name(run_phase)
    experiment_id = ls.deterministic_experiment_id(rn)
    data = [ls.to_experiment_item(record) for record in records]
    evaluators = [factory() for factory in ls.DEFAULT_EVALUATORS]
    return client.run_experiment(
        name=EXPERIMENT_NAME, run_name=rn, experiment_id=experiment_id,
        data=data, task=ls.make_lookup_task(), evaluators=evaluators,
        metadata=config_metadata or {},
    )


def _group_signature(records: list[ls.LocalRecord]) -> str:
    blob = "|".join(sorted(f"{record.question_id}:{record.mode}" for record in records))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sync_j1_globalis_group_once(
    client: Any, marker_path: Path, *, run_phase: str,
    records: Iterable[ls.LocalRecord], config_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Same once-only guard as `langfuse_sync.sync_mode_group_once` /
    `langfuse_week6.sync_drift_group_once`, kept as a small, separately-
    named copy so this run's marker is never conflated with week5-b's or
    week6's own marker files, and a restart never re-submits an already
    fully-synced, identical group."""
    records = list(records)
    signature = _group_signature(records)
    existing = json.loads(marker_path.read_text(encoding="utf-8")) if marker_path.exists() else None
    if existing is not None and existing.get("signature") == signature:
        return {"skipped": True, "reason": "identical group already synced",
               "experiment_id": existing.get("experiment_id"), "run_name": existing.get("run_name")}

    result = sync_j1_globalis_group(client, run_phase=run_phase, records=records, config_metadata=config_metadata)
    rn = run_name(run_phase)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps({
        "signature": signature, "run_name": rn,
        "experiment_id": ls.deterministic_experiment_id(rn), "record_count": len(records),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"skipped": False, "result": result}
