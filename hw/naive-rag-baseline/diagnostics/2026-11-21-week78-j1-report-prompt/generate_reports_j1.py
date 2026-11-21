"""J1 community-report generation: the SAME reusable, unmodified pipeline
pieces as ``generate_reports_v3.py`` (``validate_report``,
``resolve_statements``, ``extract_system_prompt`` -- imported, not
copied), with only the prompt template, prompt version, and output
artifact paths swapped, so the numeric-fact-preservation rule
(docs/week78-javitasok.md, diagnosis Q09/globalis) can be generated and
later measured without touching any v3 file.

Nothing about the model, its settings, temperature, max output tokens,
retries, the community payloads/membership, or the report JSON schema
changes here. The community payload (``nodes``/``domain_relationships``)
is never recomputed -- it is loaded byte-for-byte from the already-saved,
frozen v3 input/record-chunk-map files
(``diagnostics/2026-11-10-phase3-measurement/results/
week4-report-v3-input-<path>.json`` / ``...-record-chunk-map-<path>.json``),
with only the embedded ``prompt_version`` field swapped to J1's.

No real API call is made by this module as imported -- ``run_j1_reports``
takes an injected ``call_fn`` (offline tests pass a fake; a later,
separately-approved real run would inject a real ``ChatOpenAI``-backed
one, the same shape ``generate_reports_v3.py``'s own ``llm.invoke(...)``
call uses: ``call_fn(system_prompt, user_text) -> response`` with
``response.content`` / ``response.response_metadata`` / (optionally)
``response.usage_metadata``).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

import j1_bootstrap  # noqa: F401
import generate_reports_v3 as v3  # reused, unmodified: validate_report, resolve_statements, extract_system_prompt

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
TEMPLATE_J1_PATH = HERE / "week4-report-j1-prompt-template.md"

V3_RESULTS_DIR = v3.RESULTS_DIR  # read-only source of the frozen inputs; never written to from here
V3_RUN_SUMMARY_PATH = v3.RUN_SUMMARY_PATH

RUN_ID = v3.RUN_ID  # same Leiden/community partition -- not re-chosen, not re-derived
PROMPT_VERSION = "riportprompt-j1"
REQUESTED_MODEL = v3.REQUESTED_MODEL
MAX_OUTPUT_TOKENS = v3.MAX_OUTPUT_TOKENS
TEMPERATURE = 0
MAX_RETRIES = 0
INPUT_PRICE_PER_MTOK = v3.INPUT_PRICE_PER_MTOK
OUTPUT_PRICE_PER_MTOK = v3.OUTPUT_PRICE_PER_MTOK
REPORT_SCHEMA_VERSION = "v3-schema-unchanged"  # summary/key_statements/evidence_ids shape, untouched

RUN_KINDS = ("pilot", "full")
PILOT_COMMUNITY_PATHS = ("4",)


class J1Halt(RuntimeError):
    """Raised before any model call -- never a silent continuation from a
    mismatched prior run, and never an overwrite of an existing artifact."""


def paths_for_run_kind(run_kind: str) -> dict[str, Path]:
    if run_kind not in RUN_KINDS:
        raise ValueError(f"run_kind must be one of {RUN_KINDS}, got {run_kind!r}")
    run_dir = RESULTS_DIR / run_kind
    return {
        "run_dir": run_dir,
        "ledger_path": run_dir / f"week4-report-j1-{run_kind}-attempt-ledger.json",
        "collection_path": run_dir / f"week4-report-j1-{run_kind}-collection.jsonl",
        "run_summary_path": run_dir / f"week4-report-j1-{run_kind}-run-summary.json",
        "run_metadata_path": run_dir / f"week4-report-j1-{run_kind}-run-metadata.json",
        "ledger_cost_path": run_dir / f"week4-report-j1-{run_kind}-cost-ledger.json",
    }


def community_paths_for_run_kind(run_kind: str) -> tuple[str, ...]:
    """The pilot is hardcoded to path="4" (the diagnosed community);
    "full" reads the already-saved v3 run summary's successful community
    list -- the SAME 37 communities v3 used, never recomputed."""
    if run_kind == "pilot":
        return PILOT_COMMUNITY_PATHS
    summary = json.loads(V3_RUN_SUMMARY_PATH.read_text(encoding="utf-8"))
    successes = tuple(summary["successes"])
    if len(successes) != 37:
        raise J1Halt(f"expected 37 successful v3 communities, found {len(successes)} in {V3_RUN_SUMMARY_PATH}")
    return successes


def j1_system_prompt() -> str:
    return v3.extract_system_prompt(TEMPLATE_J1_PATH.read_text(encoding="utf-8"))


def prompt_sha256(system_prompt: str) -> str:
    return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()


def build_j1_payload(path: str) -> tuple[str, dict[str, list[str]], str]:
    """Loads the already-saved, frozen v3 community payload and
    record-chunk map for `path` (never recomputed) and swaps only the
    embedded `prompt_version` field. Returns (user_text, record_chunk_map,
    v3_input_hash) -- `v3_input_hash` is the hash of the UNCHANGED v3
    input bytes, kept for provenance, not of the J1 user_text itself."""
    v3_input_path = V3_RESULTS_DIR / f"week4-report-v3-input-{path}.json"
    v3_map_path = V3_RESULTS_DIR / f"week4-report-v3-record-chunk-map-{path}.json"
    if not v3_input_path.exists() or not v3_map_path.exists():
        raise J1Halt(f"missing frozen v3 input/map for community {path!r} -- J1 does not regenerate it")
    v3_input_text = v3_input_path.read_text(encoding="utf-8")
    v3_input_hash = hashlib.sha256(v3_input_text.encode("utf-8")).hexdigest()
    v3_payload = json.loads(v3_input_text)
    j1_payload = {**v3_payload, "prompt_version": PROMPT_VERSION}
    user_text = json.dumps(j1_payload, ensure_ascii=False, indent=1) + "\n"
    record_chunk_map = json.loads(v3_map_path.read_text(encoding="utf-8"))
    return user_text, record_chunk_map, v3_input_hash


def artifact_metadata(system_prompt: str, *, run_kind: str, community_paths: tuple[str, ...]) -> dict[str, Any]:
    return {
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha256(system_prompt),
        "input_run_id": RUN_ID,
        "input_collection_id": "diagnostics/2026-11-10-phase3-measurement/results/week4-report-v3-input-*.json",
        "requested_model": REQUESTED_MODEL,
        "generation_settings": {
            "temperature": TEMPERATURE, "max_retries": MAX_RETRIES, "max_output_tokens": MAX_OUTPUT_TOKENS,
        },
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "run_kind": run_kind,
        "community_paths": list(community_paths),
        "created_at": time.time(),
    }


def assert_identity_matches_or_record(metadata: dict[str, Any], run_metadata_path: Path) -> None:
    """Refuses to continue if a run-metadata file already exists for this
    run_kind with a different prompt version/hash, input run id, or
    community-path set than the one this invocation is about to use --
    never a silent resume from a mismatched prior identity. First call
    for a fresh run_kind directory records the metadata instead."""
    identity_keys = ("prompt_version", "prompt_sha256", "input_run_id", "community_paths")
    if run_metadata_path.exists():
        saved = json.loads(run_metadata_path.read_text(encoding="utf-8"))
        mismatches = {
            key: (saved.get(key), metadata.get(key))
            for key in identity_keys if saved.get(key) != metadata.get(key)
        }
        if mismatches:
            raise J1Halt(
                f"existing run metadata at {run_metadata_path} does not match this run's identity: "
                f"{mismatches} -- refusing to resume silently"
            )
        return
    run_metadata_path.parent.mkdir(parents=True, exist_ok=True)
    run_metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=1), encoding="utf-8")


def assert_no_v3_path_overlap(paths: dict[str, Path]) -> None:
    """A structural guard, not just a convention: every J1 output path
    must live under this package's own `results/` dir, never under v3's
    `RESULTS_DIR` -- raises before anything is written if that is ever
    violated (e.g. by a future edit to `paths_for_run_kind`)."""
    for name, path in paths.items():
        if V3_RESULTS_DIR in path.parents or path == V3_RESULTS_DIR:
            raise J1Halt(f"refusing to write J1 artifact {name}={path} under v3's own results dir {V3_RESULTS_DIR}")


def load_ledger(ledger_path: Path) -> dict:
    if ledger_path.exists():
        return json.loads(ledger_path.read_text(encoding="utf-8"))
    return {}


def save_ledger(ledger_path: Path, ledger: dict) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")


def run_j1_reports(
    run_kind: str, *, call_fn: Callable[[str, str], Any], community_paths: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """`call_fn(system_prompt, user_text) -> response` (response has
    `.content`, `.response_metadata`, optionally `.usage_metadata` --
    same shape `generate_reports_v3.py`'s own `llm.invoke(...)` returns).
    No client is constructed here -- offline tests inject a fake; a real
    run (separately approved) would inject a real one."""
    paths = paths_for_run_kind(run_kind)
    assert_no_v3_path_overlap(paths)
    community_paths = community_paths if community_paths is not None else community_paths_for_run_kind(run_kind)
    system_prompt = j1_system_prompt()
    metadata = artifact_metadata(system_prompt, run_kind=run_kind, community_paths=community_paths)
    assert_identity_matches_or_record(metadata, paths["run_metadata_path"])

    ledger = load_ledger(paths["ledger_path"])
    for path, entry in ledger.items():
        if entry.get("status") == "in_progress":
            raise J1Halt(f"community {path!r} has an 'in_progress' J1-{run_kind} ledger entry -- not retrying")

    collection: list[dict] = []
    halted_reason: str | None = None

    for path in community_paths:
        if path in ledger:
            continue
        existing_report = paths["run_dir"] / f"week4-report-j1-{run_kind}-report-{path}.json"
        if existing_report.exists():
            halted_reason = f"refusing to overwrite an existing J1-{run_kind} report file for community {path!r}"
            break

        user_text, record_chunk_map, v3_input_hash = build_j1_payload(path)
        ledger[path] = {"status": "in_progress", "v3_input_hash": v3_input_hash, "started_at": time.time()}
        save_ledger(paths["ledger_path"], ledger)

        response = call_fn(system_prompt, user_text)
        usage = getattr(response, "usage_metadata", None) or {}
        token_usage = (getattr(response, "response_metadata", None) or {}).get("token_usage", {})
        prompt_tokens = usage.get("input_tokens", token_usage.get("prompt_tokens", "unknown"))
        completion_tokens = usage.get("output_tokens", token_usage.get("completion_tokens", "unknown"))
        finish_reason = (getattr(response, "response_metadata", None) or {}).get("finish_reason", "unknown")
        returned_model = (getattr(response, "response_metadata", None) or {}).get("model_name", "unknown")

        record: dict[str, Any] = {
            "community_id": f"{RUN_ID}:{path}", "path": path, "run_id": RUN_ID,
            "reporting_level": 0, "prompt_version": PROMPT_VERSION, "requested_model": REQUESTED_MODEL,
            "v3_input_hash": v3_input_hash, "returned_model": returned_model,
            "usage_prompt_tokens": prompt_tokens, "usage_completion_tokens": completion_tokens,
            "finish_reason": finish_reason,
        }
        if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
            record["measured_cost_usd"] = round(
                prompt_tokens / 1_000_000 * INPUT_PRICE_PER_MTOK
                + completion_tokens / 1_000_000 * OUTPUT_PRICE_PER_MTOK, 6)
        else:
            record["measured_cost_usd"] = "unknown"

        try:
            parsed = json.loads(response.content)
            record["valid_json"] = True
        except (json.JSONDecodeError, TypeError) as exc:
            record["valid_json"] = False
            record["json_error"] = str(exc)
            parsed = None

        valid_record_ids = set(record_chunk_map.keys())
        if record["valid_json"]:
            validation = v3.validate_report(parsed, valid_record_ids)
            record["validation"] = validation
            if validation["valid_structure"]:
                record["summary"] = parsed.get("summary")
                record["key_statements"] = v3.resolve_statements(parsed, record_chunk_map)
        else:
            record["validation"] = {"valid_structure": False,
                                     "problems": ["response was not valid JSON"], "unknown_record_ids": []}

        paths["run_dir"].mkdir(parents=True, exist_ok=True)
        existing_report.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")

        outcome_status = "success" if record["validation"]["valid_structure"] else "invalid"
        ledger[path] = {"status": outcome_status, "v3_input_hash": v3_input_hash}
        save_ledger(paths["ledger_path"], ledger)

        if outcome_status == "success":
            collection.append(record)
            with paths["collection_path"].open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        else:
            halted_reason = f"invalid J1-{run_kind} report on community {path!r}: {record['validation']}"
            break

    summary = {
        "run_id": RUN_ID, "prompt_version": PROMPT_VERSION, "run_kind": run_kind,
        "requested_communities": list(community_paths),
        "successes": [p for p, e in ledger.items() if e.get("status") == "success"],
        "invalid": [p for p, e in ledger.items() if e.get("status") == "invalid"],
        "not_run": [p for p in community_paths if p not in ledger],
        "halted_reason": halted_reason,
    }
    paths["run_summary_path"].parent.mkdir(parents=True, exist_ok=True)
    paths["run_summary_path"].write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def build_real_call_fn(ledger) -> Callable[[str, str], Any]:
    """A real ``ChatOpenAI``-backed ``call_fn``, same shape
    ``generate_reports_v3.py``'s own ``llm.invoke(...)`` call uses (model,
    temperature, max_retries, max_output_tokens, JSON response format --
    unchanged from v3), gated through ``ledger.check_generative`` before
    every call, same convention as every other real call in this project.
    Not invoked anywhere in this round -- see docs/week78-javitasok.md."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from naive_rag.config import get_settings
    from naive_rag.local_search import estimate_tokens

    settings = get_settings()
    llm = ChatOpenAI(
        model=REQUESTED_MODEL, temperature=TEMPERATURE, max_retries=MAX_RETRIES,
        max_tokens=MAX_OUTPUT_TOKENS, api_key=settings.openai_api_key,
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    def call_fn(system_prompt: str, user_text: str):
        upper = ledger.check_generative(
            estimate_tokens(system_prompt + user_text), MAX_OUTPUT_TOKENS, "j1-report")
        response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_text)])
        usage = getattr(response, "usage_metadata", None) or {}
        token_usage = (response.response_metadata or {}).get("token_usage", {})
        prompt_tokens = usage.get("input_tokens", token_usage.get("prompt_tokens", "unknown"))
        completion_tokens = usage.get("output_tokens", token_usage.get("completion_tokens", "unknown"))
        ledger.record_generative(prompt_tokens, completion_tokens, upper)
        return response

    return call_fn


def main(argv: list[str] | None = None) -> int:
    """Real entry point -- NOT exercised in this round (see
    docs/week78-javitasok.md's "Tervezett ... pilot/full" sections)."""
    import argparse

    import cost_guard

    parser = argparse.ArgumentParser(prog="python generate_reports_j1.py")
    parser.add_argument("--run-kind", choices=RUN_KINDS, required=True)
    args = parser.parse_args(argv)

    paths = paths_for_run_kind(args.run_kind)
    ledger = cost_guard.SharedCostLedger.load(paths["ledger_cost_path"])
    call_fn = build_real_call_fn(ledger)
    summary = run_j1_reports(args.run_kind, call_fn=call_fn)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary["halted_reason"] is None else 1


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
