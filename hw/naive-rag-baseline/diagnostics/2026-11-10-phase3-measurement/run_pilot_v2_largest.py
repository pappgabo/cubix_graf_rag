"""Phase 3, largest-pilot retry v2: at most ONE model call.

Only the citation mechanism changes relative to the first largest pilot
(results/pilot-largest-3.json): long chunk identifiers are replaced with
short, stable record identifiers (N001.../E001...) before the input is
ever sent, and the model is asked for `evidence_ids` (record ids) instead
of `source_chunk_ids` (chunk ids). The selected nodes/edges, their text,
and their order are byte-for-byte the same data as the first pilot --
nothing is re-selected, nothing is re-truncated, and the token budget that
frees up from dropping long chunk-id arrays is not spent on more data.

No retry (client max_retries=0, and this script makes exactly one call).
No Neo4j write, no src/ change, no Leiden run, no package install, no new
backup. Does not overwrite any existing file.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
ORIGINAL_MANIFEST_PATH = RESULTS_DIR / "pilot-manifest.json"
ORIGINAL_INPUT_PATH = RESULTS_DIR / "pilot-largest-3.json"
TEMPLATE_V2_PATH = HERE / "week4-pilot-v2-prompt-template.md"

V2_INPUT_PATH = RESULTS_DIR / "week4-pilot-v2-input-largest-3.json"
V2_RECORD_CHUNK_MAP_PATH = RESULTS_DIR / "week4-pilot-v2-record-chunk-map-largest-3.json"
V2_INPUT_MANIFEST_PATH = RESULTS_DIR / "week4-pilot-v2-input-manifest.json"
V2_RAW_RESPONSE_PATH = RESULTS_DIR / "week4-pilot-v2-raw-largest-3.json"
V2_REPORT_PATH = RESULTS_DIR / "week4-pilot-v2-report-largest-3.json"
V2_VERIFICATION_PATH = RESULTS_DIR / "week4-pilot-v2-verification-largest-3.md"
V2_RUN_SUMMARY_PATH = RESULTS_DIR / "week4-pilot-v2-run-summary.json"

RUN_ID = "week4-leiden-elokeszitett-6f05327d7d88ebf0"
PROMPT_VERSION = "riportprompt-v2"
REQUESTED_MODEL = "gpt-4o-mini"
MAX_OUTPUT_TOKENS = 600
INPUT_PRICE_PER_MTOK = 0.15
OUTPUT_PRICE_PER_MTOK = 0.60


class PilotHalt(RuntimeError):
    pass


def fail_without_calling(reason: str, extra: dict | None = None) -> int:
    print("HALT before any model call:", reason)
    payload = {"halted_before_any_call": True, "reason": reason}
    if extra:
        payload.update(extra)
    for path in (V2_REPORT_PATH, V2_RUN_SUMMARY_PATH):
        if not path.exists():
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return 2


def guard_no_overwrite(path: Path) -> None:
    if path.exists():
        raise PilotHalt(f"refusing to overwrite an existing file: {path}")


# --------------------------------------------------------------------------
# 1. Input preparation
# --------------------------------------------------------------------------


def verify_original_hash() -> str:
    manifest = json.loads(ORIGINAL_MANIFEST_PATH.read_text(encoding="utf-8"))
    entry = next((p for p in manifest["pilots"] if p["label"] == "largest"), None)
    if entry is None:
        raise PilotHalt("pilot-manifest.json has no 'largest' entry")
    content = ORIGINAL_INPUT_PATH.read_text(encoding="utf-8")
    actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if actual != entry["sha256"]:
        raise PilotHalt(
            f"pilot-largest-3.json hash mismatch (manifest={entry['sha256']}, actual={actual})"
        )
    return content


def build_v2_input(original_text: str) -> tuple[dict, dict]:
    original = json.loads(original_text)
    record_chunk_map: dict[str, list[str]] = {}

    new_nodes = []
    for index, node in enumerate(original["nodes"], start=1):
        record_id = f"N{index:03d}"
        record_chunk_map[record_id] = sorted(node["source_chunk_ids"])
        new_node = {k: v for k, v in node.items() if k != "source_chunk_ids"}
        new_node["record_id"] = record_id
        # offline check: everything but the id<->chunk-ids swap is unchanged
        assert {k: v for k, v in new_node.items() if k != "record_id"} == {
            k: v for k, v in node.items() if k != "source_chunk_ids"
        }
        new_nodes.append(new_node)

    new_edges = []
    for index, edge in enumerate(original["domain_relationships"], start=1):
        record_id = f"E{index:03d}"
        record_chunk_map[record_id] = sorted(edge["source_chunk_ids"])
        new_edge = {k: v for k, v in edge.items() if k != "source_chunk_ids"}
        new_edge["record_id"] = record_id
        assert {k: v for k, v in new_edge.items() if k != "record_id"} == {
            k: v for k, v in edge.items() if k != "source_chunk_ids"
        }
        new_edges.append(new_edge)

    # same keys, same order, same every other field -- only the per-record
    # source_chunk_ids -> record_id swap, and prompt_version bumped to v2.
    new_payload = {
        "prompt_version": PROMPT_VERSION,
        "community_id": original["community_id"],
        "reporting_level": original["reporting_level"],
        "nodes": new_nodes,
        "domain_relationships": new_edges,
    }
    return new_payload, record_chunk_map


def extract_system_prompt(template_text: str) -> str:
    section = template_text.split("## Rendszerutasítás (system)", 1)[1]
    section = section.split("\n## ", 1)[0]
    match = re.search(r"```\n(.*?)\n```", section, flags=re.DOTALL)
    if not match:
        raise PilotHalt("could not find the fenced system-prompt block in the v2 template")
    return match.group(1).strip()


# --------------------------------------------------------------------------
# 3. Validation and reference resolution
# --------------------------------------------------------------------------


def validate_v2_report(parsed: Any, valid_record_ids: set[str]) -> dict:
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
            chunk_id
            for record_id in evidence_ids
            for chunk_id in record_chunk_map.get(record_id, [])
        })
        resolved.append({
            "statement": item.get("statement"),
            "evidence_ids": evidence_ids,
            "candidate_source_chunk_ids": candidate_chunk_ids,
        })
    return resolved


# --------------------------------------------------------------------------
# 4. Human-readable verification file
# --------------------------------------------------------------------------


def record_text_index(v2_payload: dict) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for node in v2_payload["nodes"]:
        index[node["record_id"]] = {"kind": "node", "text": node["text"]}
    for edge in v2_payload["domain_relationships"]:
        index[edge["record_id"]] = {
            "kind": "domain_relationship",
            "text": edge["text"],
            "source": edge["source"],
            "rel_type": edge["rel_type"],
            "target": edge["target"],
        }
    return index


def write_verification_file(resolved: list[dict], v2_payload: dict, record_chunk_map: dict) -> None:
    index = record_text_index(v2_payload)
    lines = ["# Olvasható ellenőrzési fájl -- largest-pilot v2 (közösség 3)", ""]
    for i, item in enumerate(resolved, start=1):
        lines.append(f"## Állítás {i}")
        lines.append("")
        lines.append(f"**Statement:** {item['statement']}")
        lines.append("")
        lines.append(f"**evidence_ids:** {', '.join(item['evidence_ids']) or '(nincs)'}")
        lines.append("")
        for record_id in item["evidence_ids"]:
            record = index.get(record_id)
            lines.append(f"- `{record_id}`")
            if record is None:
                lines.append("  - ISMERETLEN rekordazonosító -- nem létezik a bemenetben.")
                continue
            lines.append(f"  - szöveg: {record['text']}")
            lines.append(f"  - eredeti source_chunk_ids: {record_chunk_map.get(record_id, [])}")
        lines.append("")
    V2_VERIFICATION_PATH.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> int:
    for path in (
        V2_INPUT_PATH, V2_RECORD_CHUNK_MAP_PATH, V2_INPUT_MANIFEST_PATH,
        V2_RAW_RESPONSE_PATH, V2_REPORT_PATH, V2_VERIFICATION_PATH, V2_RUN_SUMMARY_PATH,
    ):
        try:
            guard_no_overwrite(path)
        except PilotHalt as exc:
            return fail_without_calling(str(exc))

    try:
        original_text = verify_original_hash()
    except PilotHalt as exc:
        return fail_without_calling(str(exc))

    v2_payload, record_chunk_map = build_v2_input(original_text)
    v2_text = json.dumps(v2_payload, ensure_ascii=False, indent=1) + "\n"
    V2_INPUT_PATH.write_text(v2_text, encoding="utf-8")
    V2_RECORD_CHUNK_MAP_PATH.write_text(
        json.dumps(record_chunk_map, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    v2_hash = hashlib.sha256(v2_text.encode("utf-8")).hexdigest()
    V2_INPUT_MANIFEST_PATH.write_text(
        json.dumps({
            "label": "largest-v2",
            "community_id": v2_payload["community_id"],
            "file": str(V2_INPUT_PATH.relative_to(ROOT)),
            "sha256": v2_hash,
            "derived_from": {
                "file": str(ORIGINAL_INPUT_PATH.relative_to(ROOT)),
                "sha256": hashlib.sha256(original_text.encode("utf-8")).hexdigest(),
            },
        }, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )

    system_prompt = extract_system_prompt(TEMPLATE_V2_PATH.read_text(encoding="utf-8"))
    valid_record_ids = set(record_chunk_map.keys())

    estimated_input_tokens_char4 = -(-len(v2_text) // 4)
    print("planned max calls: 1")
    print(f"estimated input tokens (character/4): {estimated_input_tokens_char4}")
    print(f"output token cap: {MAX_OUTPUT_TOKENS}")

    record: dict[str, Any] = {
        "community_id": v2_payload["community_id"],
        "run_id": RUN_ID,
        "reporting_level": v2_payload["reporting_level"],
        "prompt_version": PROMPT_VERSION,
        "requested_model": REQUESTED_MODEL,
        "input_hash": v2_hash,
    }

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

    try:
        started = time.monotonic()
        response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=v2_text)])
        elapsed = time.monotonic() - started
    except Exception as exc:  # noqa: BLE001
        record["error"] = f"{type(exc).__name__}: {exc}"
        V2_REPORT_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        V2_RUN_SUMMARY_PATH.write_text(
            json.dumps({"halted_reason": record["error"], "completed_calls": 0}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print("API ERROR:", record["error"])
        return 1

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

    V2_RAW_RESPONSE_PATH.write_text(
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

    cost_usd = None
    if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
        cost_usd = round(
            prompt_tokens / 1_000_000 * INPUT_PRICE_PER_MTOK
            + completion_tokens / 1_000_000 * OUTPUT_PRICE_PER_MTOK,
            6,
        )
    record["measured_cost_usd"] = cost_usd if cost_usd is not None else "unknown"

    if record["valid_json"]:
        validation = validate_v2_report(parsed, valid_record_ids)
        record["validation"] = validation
        if validation["valid_structure"]:
            resolved = resolve_statements(parsed, record_chunk_map)
            record["summary"] = parsed.get("summary")
            record["key_statements"] = resolved
            write_verification_file(resolved, v2_payload, record_chunk_map)
        else:
            record["raw_report"] = parsed
    else:
        record["validation"] = {
            "valid_structure": False,
            "problems": ["response was not valid JSON"],
            "unknown_record_ids": [],
        }

    V2_REPORT_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")

    halted_reason = None
    if finish_reason == "length":
        halted_reason = "finish_reason=length"
    elif not record["valid_json"]:
        halted_reason = "invalid JSON"
    elif not record["validation"]["valid_structure"]:
        halted_reason = f"invalid report structure or unknown record id: {record['validation']}"

    summary = {
        "run_id": RUN_ID,
        "prompt_version": PROMPT_VERSION,
        "requested_model": REQUESTED_MODEL,
        "returned_model": returned_model,
        "input_hash": v2_hash,
        "usage_prompt_tokens": prompt_tokens,
        "usage_completion_tokens": completion_tokens,
        "finish_reason": finish_reason,
        "duration_seconds": record["duration_seconds"],
        "measured_cost_usd": record["measured_cost_usd"],
        "valid_json": record["valid_json"],
        "valid_structure": record["validation"]["valid_structure"],
        "unknown_record_ids": record["validation"].get("unknown_record_ids", []),
        "halted_reason": halted_reason,
    }
    V2_RUN_SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if halted_reason is None else 1


if __name__ == "__main__":
    sys.exit(main())
