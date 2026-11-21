"""Week6-named Langfuse sync, built on week5-b's generic Langfuse pieces.

``langfuse_sync.py`` (week5-b, unchanged) hardcodes its own experiment/run
names to the ``"week5-b-"`` prefix (`EXPERIMENT_NAME_SMOKE`,
`EXPERIMENT_NAME_FULL`, `mode_run_name`) -- calling its own
``sync_mode_group``/``sync_mode_group_once`` unchanged would silently file
every week6 drift experiment under those week5-b names. Everything else in
that module (`LocalRecord`, `to_experiment_item`, `make_lookup_task`,
`DEFAULT_EVALUATORS`, `deterministic_experiment_id`) is generic and is
reused here unmodified -- only the naming and the two thin orchestration
functions are redefined, with a ``"week6-drift-"`` prefix instead.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import week6_bootstrap  # noqa: F401
import langfuse_sync as ls

EXPERIMENT_NAME_SMOKE = "week6-drift-smoke"
EXPERIMENT_NAME_FULL = "week6-drift-full"


def mode_run_name(run_phase: str) -> str:
    """One run name per run_phase -- there is only one mode (drift) in
    week6, so this is simpler than week5-b's (run_phase, mode) pair."""
    return f"week6-drift-{run_phase}"


def sync_drift_group(
    client: Any, *, run_phase: str, records: Iterable[ls.LocalRecord],
    config_metadata: dict[str, Any] | None = None,
) -> Any:
    records = list(records)
    experiment_name = EXPERIMENT_NAME_SMOKE if run_phase == "smoke" else EXPERIMENT_NAME_FULL
    run_name = mode_run_name(run_phase)
    experiment_id = ls.deterministic_experiment_id(run_name)
    data = [ls.to_experiment_item(record) for record in records]
    evaluators = [factory() for factory in ls.DEFAULT_EVALUATORS]
    return client.run_experiment(
        name=experiment_name, run_name=run_name, experiment_id=experiment_id,
        data=data, task=ls.make_lookup_task(), evaluators=evaluators,
        metadata=config_metadata or {},
    )


def _group_signature(records: list[ls.LocalRecord]) -> str:
    blob = "|".join(sorted(f"{record.question_id}:{record.mode}" for record in records))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sync_drift_group_once(
    client: Any, marker_path: Path, *, run_phase: str,
    records: Iterable[ls.LocalRecord], config_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Same once-only guard as `langfuse_sync.sync_mode_group_once`, kept
    as a small, separately-named copy so a resumed, not-yet-complete week6
    group is never conflated with a week5-b marker file."""
    records = list(records)
    signature = _group_signature(records)
    existing = json.loads(marker_path.read_text(encoding="utf-8")) if marker_path.exists() else None
    if existing is not None and existing.get("signature") == signature:
        return {"skipped": True, "reason": "identical group already synced",
               "experiment_id": existing.get("experiment_id"), "run_name": existing.get("run_name")}

    result = sync_drift_group(client, run_phase=run_phase, records=records, config_metadata=config_metadata)
    run_name = mode_run_name(run_phase)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps({
        "signature": signature, "run_name": run_name,
        "experiment_id": ls.deterministic_experiment_id(run_name), "record_count": len(records),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"skipped": False, "result": result}
