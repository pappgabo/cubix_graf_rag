"""Langfuse sync layer, built against the SDK actually installed in this
project's venv (``langfuse==5.2.0``, EU cloud region), not guessed from
memory. Verified directly against the installed package
(``.venv/Lib/site-packages/langfuse``):

    from langfuse import Langfuse
    Langfuse.run_experiment(self, *, name, run_name=None, description=None,
        data, task, evaluators=[], composite_evaluator=None,
        run_evaluators=[], max_concurrency=50, metadata=None,
        experiment_id=None, _dataset_version=None) -> ExperimentResult

``data`` items are ``LocalExperimentItem`` dicts: ``{"input", "expected_output",
"metadata"}``. ``task`` is called once per item by the SDK and its return
value is traced; the SDK docs explicitly allow a task that "returns a
direct value" (no model call is required by the Protocol) -- this module
uses exactly that: ``task`` only looks up an already-saved local answer,
and ``evaluators`` only read already-saved local scores. No evaluator or
task function here calls a model or embeds anything; the upload is pure
re-statement of what ``measure.py`` already computed and persisted to
``results.jsonl``.

The local JSONL (``results.jsonl``) is the archive of record; Langfuse is
a second, queryable view, not the only copy (per spec: "A helyi JSONL a
folytathatóság alapja; a Langfuse nem az egyetlen archívum.").

## One run per mode, not one per (question, mode)

``sync_mode_group`` issues exactly ONE ``run_experiment`` call per
(run_phase, mode) pair, with ALL of that group's records as ``data`` in a
single call -- never one call per question. This makes the smoke run's
three naiv/lokalis/globalis experiments each cover its three questions,
and the full run's three experiments each cover all 15, so the three
modes are comparable on the same question set inside Langfuse too.

## Idempotent re-sync (verified against the installed SDK's own docstring)

``Langfuse.run_experiment``'s ``experiment_id`` parameter: "Calls with the
same ``experiment_id`` add their items and scores to one experiment in
Langfuse, so separate workers, batches, or a resumed run can share an
experiment, also for local data." ``deterministic_experiment_id`` derives
this id from ``Langfuse.create_trace_id(seed=run_name)`` (a static,
offline, deterministic hash -- no network call), so re-running the sync
for the same (run_phase, mode) always targets the same Langfuse
experiment: it is never duplicated as a separate "run".

**Known SDK limitation, not worked around**: the installed SDK documents
run-level idempotency via ``experiment_id``, but nowhere documents
item-level deduplication -- calling ``run_experiment`` twice with
overlapping items would add those items again as separate item-traces
inside the same experiment. Rather than build a deduplication workaround
on top of an unsupported guarantee, ``sync_mode_group_once`` avoids the
situation by construction: it only ever calls ``run_experiment`` once per
exact (run_phase, mode, record-set) combination, recording a local marker
file keyed by a hash of the included question ids; a second invocation
with the identical record set is a no-op. If the record set for a mode
changes between invocations (e.g. a resumed run that only now completed
the group), this is still a *different* group than before, so it also
only syncs once for *that* resulting set -- it does not attempt a partial
re-sync of the delta, since the SDK gives no documented way to replace or
remove previously added items.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

EXPERIMENT_NAME_SMOKE = "week5-b-smoke"
EXPERIMENT_NAME_FULL = "week5-b-full"


def mode_run_name(run_phase: str, mode: str) -> str:
    """One run name per (run_phase, mode) -- e.g. 'week5-b-smoke-naiv'."""
    return f"week5-b-{run_phase}-{mode}"


def deterministic_experiment_id(run_name: str) -> str:
    """Offline, no network call -- ``Langfuse.create_trace_id`` is a
    ``@staticmethod`` that only hashes the seed (verified via
    ``inspect.getsource`` against the installed ``langfuse==5.2.0``)."""
    from langfuse import Langfuse

    return Langfuse.create_trace_id(seed=run_name)


@dataclass(frozen=True)
class LocalRecord:
    """One (question_id, mode) case's already-computed, already-saved
    local result -- the only input this module reads. Never triggers a
    new model call to build or to sync."""
    question_id: str
    mode: str
    question_text: str
    answer: str | None
    expected_answer: str
    metadata: dict[str, Any]


def to_experiment_item(record: LocalRecord) -> dict[str, Any]:
    """Builds one LocalExperimentItem. ``metadata`` carries everything the
    pure-lookup task/evaluators below need -- no recomputation."""
    return {
        "input": record.question_text,
        "expected_output": record.expected_answer,
        "metadata": {
            "question_id": record.question_id,
            "mode": record.mode,
            "precomputed_answer": record.answer,
            **record.metadata,
        },
    }


def make_lookup_task() -> Callable[..., Any]:
    """TaskFunction: returns the already-saved answer. No model call --
    satisfies 'a feltöltés nem indíthat új modellhívást'."""

    def task(*, item: Any, **_kwargs: Any) -> Any:
        meta = item["metadata"] if isinstance(item, dict) else item.metadata
        return meta.get("precomputed_answer")

    return task


def _meta(item: Any) -> dict[str, Any]:
    return item["metadata"] if isinstance(item, dict) else (item.metadata or {})


def correctness_label_evaluator():
    """EvaluatorFunction re-stating the already-computed correctness label
    (see correctness_judge.label_from_judgement) as a categorical score."""
    from langfuse import Evaluation

    def evaluator(*, input: Any, output: Any, expected_output: Any,
                 metadata: dict[str, Any] | None, **_kwargs: Any) -> Any:
        meta = metadata or {}
        label = meta.get("correctness_label")
        if label is None:
            return Evaluation(name="correctness_label", value="n/a",
                              comment="not yet scored", data_type="CATEGORICAL")
        return Evaluation(name="correctness_label", value=label, data_type="CATEGORICAL")

    return evaluator


def faithfulness_score_evaluator():
    """EvaluatorFunction re-stating the already-computed claim-level
    faithfulness score (own metric, not Ragas -- see
    judges/faithfulness_judge_prompt_v1.md)."""
    from langfuse import Evaluation

    def evaluator(*, input: Any, output: Any, expected_output: Any,
                 metadata: dict[str, Any] | None, **_kwargs: Any) -> Any:
        meta = metadata or {}
        score = meta.get("faithfulness_score")
        if score is None:
            return Evaluation(name="faithfulness_own_metric", value="n/a",
                              comment="not yet scored", data_type="CATEGORICAL")
        if score == "n/a":
            return Evaluation(name="faithfulness_own_metric", value="n/a",
                              comment="no factual claims (e.g. refusal)", data_type="CATEGORICAL")
        return Evaluation(name="faithfulness_own_metric", value=float(score))

    return evaluator


def retrieval_ratio_evaluator():
    """EvaluatorFunction re-stating the already-computed deterministic
    retrieval ratio. Proxy (global) values are tagged, never silently
    merged with genuine retrieval."""
    from langfuse import Evaluation

    def evaluator(*, input: Any, output: Any, expected_output: Any,
                 metadata: dict[str, Any] | None, **_kwargs: Any) -> Any:
        meta = metadata or {}
        ratio = meta.get("retrieval_ratio")
        is_proxy = meta.get("retrieval_is_proxy", False)
        name = "retrieval_ratio_proxy" if is_proxy else "retrieval_ratio"
        if ratio is None:
            return Evaluation(name=name, value="n/a", comment="untraceable or not scored",
                              data_type="CATEGORICAL")
        return Evaluation(name=name, value=float(ratio))

    return evaluator


DEFAULT_EVALUATORS = (
    correctness_label_evaluator,
    faithfulness_score_evaluator,
    retrieval_ratio_evaluator,
)


def _group_signature(records: list[LocalRecord]) -> str:
    """Identifies exactly which (question_id, mode) pairs are in this
    group -- not the answers/scores themselves, so a group whose
    membership hasn't changed is recognized even if e.g. a comment text
    changed in a judge's reasoning field."""
    blob = "|".join(sorted(f"{r.question_id}:{r.mode}" for r in records))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sync_mode_group(
    client: Any, *, run_phase: str, mode: str,
    records: Iterable[LocalRecord], config_metadata: dict[str, Any] | None = None,
) -> Any:
    """ONE ``run_experiment`` call for every record of this (run_phase,
    mode) group at once. ``client`` is dependency injected (a real
    ``langfuse.Langfuse()`` instance or a fake for offline tests) -- this
    function never constructs its own client and never reads credentials.
    Prefer ``sync_mode_group_once`` from the orchestrator, which also
    guards against re-firing this for an unchanged group."""
    records = list(records)
    experiment_name = EXPERIMENT_NAME_SMOKE if run_phase == "smoke" else EXPERIMENT_NAME_FULL
    run_name = mode_run_name(run_phase, mode)
    experiment_id = deterministic_experiment_id(run_name)
    data = [to_experiment_item(record) for record in records]
    evaluators = [factory() for factory in DEFAULT_EVALUATORS]
    return client.run_experiment(
        name=experiment_name,
        run_name=run_name,
        experiment_id=experiment_id,
        data=data,
        task=make_lookup_task(),
        evaluators=evaluators,
        metadata=config_metadata or {},
    )


def sync_mode_group_once(
    client: Any, marker_path: Path, *, run_phase: str, mode: str,
    records: Iterable[LocalRecord], config_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Like ``sync_mode_group``, but skips the call entirely (returns
    ``{"skipped": True, ...}``) when a marker file already records this
    exact (run_phase, mode, record-set) as synced -- so re-running the
    measurement's sync step for an already-fully-synced group never
    re-issues the ``run_experiment`` call, let alone a duplicated run."""
    records = list(records)
    signature = _group_signature(records)
    existing = json.loads(marker_path.read_text(encoding="utf-8")) if marker_path.exists() else None
    if existing is not None and existing.get("signature") == signature:
        return {"skipped": True, "reason": "identical group already synced",
               "experiment_id": existing.get("experiment_id"), "run_name": existing.get("run_name")}

    result = sync_mode_group(
        client, run_phase=run_phase, mode=mode, records=records, config_metadata=config_metadata)
    run_name = mode_run_name(run_phase, mode)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps({
        "signature": signature, "run_name": run_name,
        "experiment_id": deterministic_experiment_id(run_name), "record_count": len(records),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"skipped": False, "result": result}
