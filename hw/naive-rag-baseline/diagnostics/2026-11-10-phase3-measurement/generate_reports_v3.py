"""Phase 3: generate the 37 level-0 community reports (v3 prompt, record-id
citations), at most one gpt-4o-mini call per community, at most 37 calls
total for this script.

Reuses, rather than re-implements:
  - measure_report_inputs.py for the plan, the consolidated domain edges,
    and the already-audited per-community selection/ordering/truncation
    (measure_community() / CommunityMeasurement.input_payload) -- nothing
    about membership, alias resolution, exclusion, or edge semantics is
    recomputed differently here.
  - the v2 pilot's record-id transform pattern (source_chunk_ids ->
    N.../E... record ids, with a separate record->chunk map).

Resumable by design: a persistent attempt ledger
(results/week4-report-v3-attempt-ledger.json) records every community this
script has ever ATTEMPTED to call, success or failure. On any run (fresh
or restarted), a community already in the ledger is never called again
without a separate, explicit authorization -- this file's own logic will
not do it automatically. An entry left in "in_progress" state (the process
was interrupted between issuing the call and recording its outcome) halts
the whole script immediately as an uncertain prior outcome, rather than
guessing or retrying.

No Neo4j write, no src/ change, no Leiden run, no package install or
tokenizer download, no new backup/restore, no automatic retry.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import measure_report_inputs as m  # noqa: E402  (adds its own sys.path entries)

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
TEMPLATE_V3_PATH = HERE / "week4-report-v3-prompt-template.md"
LEDGER_PATH = RESULTS_DIR / "week4-report-v3-attempt-ledger.json"
RUN_SUMMARY_PATH = RESULTS_DIR / "week4-report-v3-run-summary.json"
COLLECTION_PATH = RESULTS_DIR / "week4-report-v3-collection.jsonl"

RUN_ID = "week4-leiden-elokeszitett-6f05327d7d88ebf0"
PROMPT_VERSION = "riportprompt-v3"
REQUESTED_MODEL = "gpt-4o-mini"
MAX_OUTPUT_TOKENS = 900
MAX_TOTAL_CALLS = 37
INPUT_PRICE_PER_MTOK = 0.15
OUTPUT_PRICE_PER_MTOK = 0.60
PILOT_COMMUNITY_PATHS = {"8", "205", "3"}
ORIGINAL_24K_BUDGET = 24_000


class PilotHalt(RuntimeError):
    pass


# --------------------------------------------------------------------------
# System prompt extraction (same fenced-block convention as v1/v2)
# --------------------------------------------------------------------------


def extract_system_prompt(template_text: str) -> str:
    import re

    section = template_text.split("## Rendszerutasítás (system)", 1)[1]
    section = section.split("\n## ", 1)[0]
    match = re.search(r"```\n(.*?)\n```", section, flags=re.DOTALL)
    if not match:
        raise PilotHalt("could not find the fenced system-prompt block in the v3 template")
    return match.group(1).strip()


# --------------------------------------------------------------------------
# Record-id transform (same pattern as run_pilot_v2_largest.py, generalized)
# --------------------------------------------------------------------------


def to_record_id_payload(v1_payload: dict) -> tuple[dict, dict[str, list[str]]]:
    record_chunk_map: dict[str, list[str]] = {}
    new_nodes = []
    for index, node in enumerate(v1_payload["nodes"], start=1):
        record_id = f"N{index:03d}"
        record_chunk_map[record_id] = sorted(node["source_chunk_ids"])
        new_node = {k: v for k, v in node.items() if k != "source_chunk_ids"}
        new_node["record_id"] = record_id
        assert {k: v for k, v in new_node.items() if k != "record_id"} == {
            k: v for k, v in node.items() if k != "source_chunk_ids"
        }
        new_nodes.append(new_node)

    new_edges = []
    for index, edge in enumerate(v1_payload["domain_relationships"], start=1):
        record_id = f"E{index:03d}"
        record_chunk_map[record_id] = sorted(edge["source_chunk_ids"])
        new_edge = {k: v for k, v in edge.items() if k != "source_chunk_ids"}
        new_edge["record_id"] = record_id
        assert {k: v for k, v in new_edge.items() if k != "record_id"} == {
            k: v for k, v in edge.items() if k != "source_chunk_ids"
        }
        new_edges.append(new_edge)

    new_payload = {
        "prompt_version": PROMPT_VERSION,
        "community_id": v1_payload["community_id"],
        "reporting_level": v1_payload["reporting_level"],
        "nodes": new_nodes,
        "domain_relationships": new_edges,
    }
    return new_payload, record_chunk_map


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def validate_report(parsed: Any, valid_record_ids: set[str]) -> dict:
    problems: list[str] = []
    unknown_ids: list[str] = []
    if not isinstance(parsed, dict):
        return {"valid_structure": False, "problems": ["top level is not a JSON object"],
                "unknown_record_ids": []}
    if not isinstance(parsed.get("summary"), str) or not parsed.get("summary"):
        problems.append("missing or empty 'summary'")
    statements = parsed.get("key_statements")
    if not isinstance(statements, list) or not statements:
        problems.append("missing or empty 'key_statements'")
        statements = []
    for index, item in enumerate(statements):
        if not isinstance(item, dict):
            problems.append(f"key_statements[{index}] is not an object")
            continue
        if not isinstance(item.get("statement"), str) or not item.get("statement"):
            problems.append(f"key_statements[{index}].statement missing or empty")
        ids = item.get("evidence_ids")
        if not isinstance(ids, list) or not ids:
            problems.append(f"key_statements[{index}].evidence_ids missing or empty")
            continue
        for record_id in ids:
            if record_id not in valid_record_ids:
                unknown_ids.append(str(record_id))
    valid_structure = not problems and not unknown_ids
    return {
        "valid_structure": valid_structure,
        "problems": problems,
        "unknown_record_ids": sorted(set(unknown_ids)),
        "note": "formal record-id validation only -- not a judgement of the report's factual correctness",
    }


def resolve_statements(parsed: dict, record_chunk_map: dict[str, list[str]]) -> list[dict]:
    resolved = []
    for item in parsed.get("key_statements", []):
        evidence_ids = item.get("evidence_ids") or []
        candidate_chunk_ids = sorted({
            chunk_id for rid in evidence_ids for chunk_id in record_chunk_map.get(rid, [])
        })
        resolved.append({
            "statement": item.get("statement"),
            "evidence_ids": evidence_ids,
            "candidate_source_chunk_ids": candidate_chunk_ids,
        })
    return resolved


# --------------------------------------------------------------------------
# Ledger (persistent, resumability-safe)
# --------------------------------------------------------------------------


def load_ledger() -> dict:
    if LEDGER_PATH.exists():
        return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    return {}


def save_ledger(ledger: dict) -> None:
    LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------
# Build all 37 community payloads (reusing measure_report_inputs verbatim)
# --------------------------------------------------------------------------


def build_all_payloads() -> dict[str, dict]:
    mapping, plan = m.load_plan()
    forward = dict(mapping["alias"])
    excluded = frozenset(mapping["kizart"])
    records = m.load_records(m.w4.CORPUS)
    graph = m.merged_graph(records)
    nodes_by_key = {node.entity_key: node for node in graph.nodes}
    prepared_pairs = m.build_prepared_pairs(graph, forward, excluded)
    domain_edges = m.consolidate_domain_edges(graph, forward, excluded)
    level0_members, _level1_members = m.level_membership(plan)
    assert len(level0_members) == 37

    payloads: dict[str, dict] = {}
    for path, members in level0_members.items():
        measurement = m.measure_community(path, 0, members, nodes_by_key, prepared_pairs, domain_edges)
        payloads[path] = measurement.input_payload

    # consistency check: the 3 pilot communities must match the already
    # hashed, previously saved pilot inputs byte-for-byte.
    pilot_manifest = json.loads((RESULTS_DIR / "pilot-manifest.json").read_text(encoding="utf-8"))
    by_community = {p["community_id"]: p for p in pilot_manifest["pilots"]}
    for path in PILOT_COMMUNITY_PATHS:
        saved_file = RESULTS_DIR / Path(by_community[path]["file"]).name
        saved_text = saved_file.read_text(encoding="utf-8")
        regenerated_text = json.dumps(payloads[path], ensure_ascii=False, indent=1) + "\n"
        if saved_text != regenerated_text:
            raise PilotHalt(
                f"regenerated payload for pilot community {path!r} does not match "
                f"the already-saved {saved_file.name} byte-for-byte"
            )
    return payloads


def path_tuple(path: str) -> tuple[int, ...]:
    return tuple(int(seg) for seg in path.split("/"))


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> int:
    payloads = build_all_payloads()
    ordered_paths = sorted(payloads, key=path_tuple)
    system_prompt = extract_system_prompt(TEMPLATE_V3_PATH.read_text(encoding="utf-8"))

    ledger = load_ledger()
    for path, entry in ledger.items():
        if entry.get("status") == "in_progress":
            print(f"HALT: community {path!r} has an 'in_progress' ledger entry from a prior "
                  f"run with no recorded outcome -- uncertain, not retrying automatically.")
            return 3

    already_attempted = [p for p in ordered_paths if p in ledger]
    remaining_budget = MAX_TOTAL_CALLS - len(ledger)
    print(f"communities: {len(ordered_paths)}")
    print(f"already attempted (this or a prior run): {len(already_attempted)}")
    print(f"remaining call budget: {remaining_budget} (of {MAX_TOTAL_CALLS} total)")

    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
    from naive_rag.config import get_settings

    settings = get_settings()
    llm = ChatOpenAI(
        model=REQUESTED_MODEL,
        temperature=0,
        max_retries=0,
        max_tokens=MAX_OUTPUT_TOKENS,
        api_key=settings.openai_api_key,
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    estimated_total_chars = 0
    for path in ordered_paths:
        v3_payload, _ = to_record_id_payload(payloads[path])
        user_text = json.dumps(v3_payload, ensure_ascii=False, indent=1) + "\n"
        estimated_total_chars += len(system_prompt) + len(user_text)
    print(f"estimated total input tokens across all 37 (character/4, ESTIMATE): "
          f"{-(-estimated_total_chars // 4)}")
    print(f"planned output budget: up to {MAX_TOTAL_CALLS} x {MAX_OUTPUT_TOKENS} = "
          f"{MAX_TOTAL_CALLS * MAX_OUTPUT_TOKENS} tokens")

    collection: list[dict] = []
    halted_reason: str | None = None

    for path in ordered_paths:
        if path in ledger:
            continue
        if len(ledger) >= MAX_TOTAL_CALLS:
            halted_reason = f"call budget exhausted ({MAX_TOTAL_CALLS}) before community {path!r}"
            break

        v1_payload = payloads[path]
        v3_payload, record_chunk_map = to_record_id_payload(v1_payload)
        user_text = json.dumps(v3_payload, ensure_ascii=False, indent=1) + "\n"
        input_hash = hashlib.sha256(user_text.encode("utf-8")).hexdigest()
        full_community_id = f"{RUN_ID}:{path}"

        input_path = RESULTS_DIR / f"week4-report-v3-input-{path.replace('/', '-')}.json"
        map_path = RESULTS_DIR / f"week4-report-v3-record-chunk-map-{path.replace('/', '-')}.json"
        raw_path = RESULTS_DIR / f"week4-report-v3-raw-{path.replace('/', '-')}.json"
        report_path = RESULTS_DIR / f"week4-report-v3-report-{path.replace('/', '-')}.json"

        if input_path.exists() or map_path.exists() or raw_path.exists() or report_path.exists():
            halted_reason = f"refusing to overwrite an existing v3 file for community {path!r}"
            break

        input_path.write_text(user_text, encoding="utf-8")
        map_path.write_text(
            json.dumps(record_chunk_map, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )

        estimated_input_tokens = -(-(len(system_prompt) + len(user_text)) // 4)
        budget_note = None
        if estimated_input_tokens > ORIGINAL_24K_BUDGET:
            budget_note = (
                f"estimated total input (system+user) {estimated_input_tokens} tokens "
                f"exceeds the original 24000-token per-community budget "
                "(that budget only ever covered the JSON payload, not the system prompt)"
            )
            print("NOTE:", budget_note)

        # mark in_progress BEFORE calling, so an interruption is detectable
        ledger[path] = {"status": "in_progress", "input_hash": input_hash, "started_at": time.time()}
        save_ledger(ledger)

        print(f"\n--- calling model for community {path!r} ({ordered_paths.index(path) + 1}/37) ---")
        record: dict[str, Any] = {
            "community_id": full_community_id,
            "path": path,
            "run_id": RUN_ID,
            "reporting_level": 0,
            "prompt_version": PROMPT_VERSION,
            "requested_model": REQUESTED_MODEL,
            "input_hash": input_hash,
            "estimated_input_tokens": estimated_input_tokens,
            "estimated_input_tokens_method": "character/4 ceiling (includes system+user text)",
            "budget_note": budget_note,
        }

        try:
            started = time.monotonic()
            response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_text)])
            elapsed = time.monotonic() - started
        except Exception as exc:  # noqa: BLE001
            record["error"] = f"{type(exc).__name__}: {exc}"
            report_path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
            ledger[path] = {"status": "error", "input_hash": input_hash}
            save_ledger(ledger)
            halted_reason = f"API error on community {path!r}: {record['error']}"
            break

        usage = getattr(response, "usage_metadata", None) or {}
        token_usage = (response.response_metadata or {}).get("token_usage", {})
        prompt_tokens = usage.get("input_tokens", token_usage.get("prompt_tokens", "unknown"))
        completion_tokens = usage.get("output_tokens", token_usage.get("completion_tokens", "unknown"))
        finish_reason = (response.response_metadata or {}).get("finish_reason", "unknown")
        returned_model = (response.response_metadata or {}).get("model_name", "unknown")

        record.update({
            "returned_model": returned_model,
            "duration_seconds": round(elapsed, 3),
            "usage_prompt_tokens": prompt_tokens,
            "usage_completion_tokens": completion_tokens,
            "finish_reason": finish_reason,
        })
        if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
            record["measured_cost_usd"] = round(
                prompt_tokens / 1_000_000 * INPUT_PRICE_PER_MTOK
                + completion_tokens / 1_000_000 * OUTPUT_PRICE_PER_MTOK, 6,
            )
        else:
            record["measured_cost_usd"] = "unknown"

        raw_path.write_text(
            json.dumps({"content": response.content, "response_metadata": response.response_metadata},
                       ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

        try:
            parsed = json.loads(response.content)
            record["valid_json"] = True
        except (json.JSONDecodeError, TypeError) as exc:
            record["valid_json"] = False
            record["json_error"] = str(exc)
            parsed = None

        valid_record_ids = set(record_chunk_map.keys())
        if record["valid_json"]:
            validation = validate_report(parsed, valid_record_ids)
            record["validation"] = validation
            if validation["valid_structure"]:
                record["summary"] = parsed.get("summary")
                record["key_statements"] = resolve_statements(parsed, record_chunk_map)
            else:
                record["raw_report"] = parsed
        else:
            record["validation"] = {"valid_structure": False,
                                     "problems": ["response was not valid JSON"],
                                     "unknown_record_ids": []}

        report_path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")

        outcome_status = "success" if record["validation"]["valid_structure"] else "invalid"
        ledger[path] = {"status": outcome_status, "input_hash": input_hash}
        save_ledger(ledger)

        if outcome_status == "success":
            collection.append(record)
            with COLLECTION_PATH.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"  OK: prompt_tokens={prompt_tokens} completion_tokens={completion_tokens} "
                  f"finish_reason={finish_reason} cost=${record['measured_cost_usd']}")
        else:
            halted_reason = (
                f"invalid report on community {path!r}: finish_reason={finish_reason}, "
                f"valid_json={record['valid_json']}, validation={record['validation']}"
            )
            print("  STOPPING:", halted_reason)
            break

    not_run = [p for p in ordered_paths if p not in ledger]
    successes = [p for p, e in ledger.items() if e.get("status") == "success"]
    invalid = [p for p, e in ledger.items() if e.get("status") == "invalid"]
    errored = [p for p, e in ledger.items() if e.get("status") == "error"]

    summary = {
        "run_id": RUN_ID,
        "prompt_version": PROMPT_VERSION,
        "requested_model": REQUESTED_MODEL,
        "total_communities": len(ordered_paths),
        "attempted_calls_total": len(ledger),
        "successes": sorted(successes, key=path_tuple),
        "invalid": sorted(invalid, key=path_tuple),
        "errored": sorted(errored, key=path_tuple),
        "not_run": sorted(not_run, key=path_tuple),
        "halted_reason": halted_reason,
    }
    RUN_SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n=== summary ===")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if halted_reason is None else 1


if __name__ == "__main__":
    sys.exit(main())
