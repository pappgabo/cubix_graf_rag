"""Phase 3 pilot: up to 3 model calls, one per saved pilot input.

Runs exactly once, in order: smallest, median, largest. No retry of any
kind (client max_retries=0, this script never calls the API twice for the
same input). On the first hard failure (API error, invalid JSON, invalid
report structure, a source_chunk_ids value absent from the actual input,
or finish_reason == "length") it stops immediately, saves whatever
succeeded so far plus the error, and does not call the model again.

Does not modify any existing file. Does not touch Neo4j, does not install
packages, does not re-run Leiden. The API key comes from the project's own
settings (naive_rag.config.get_settings()) and is never printed or saved.
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
MANIFEST_PATH = RESULTS_DIR / "pilot-manifest.json"
TEMPLATE_PATH = HERE / "riportprompt-sablon-v1.md"

RUN_ID = "week4-leiden-elokeszitett-6f05327d7d88ebf0"
PROMPT_VERSION = "riportprompt-v1"
REQUESTED_MODEL = "gpt-4o-mini"
MAX_OUTPUT_TOKENS = 600

PILOT_FILES_IN_ORDER = [
    "pilot-smallest-8.json",
    "pilot-median-205.json",
    "pilot-largest-3.json",
]


class PilotHalt(RuntimeError):
    """A hard-stop condition was reached; no further model calls follow."""


def extract_system_prompt(template_text: str) -> str:
    section = template_text.split("## Rendszerutasítás (system)", 1)[1]
    section = section.split("\n## ", 1)[0]
    match = re.search(r"```\n(.*?)\n```", section, flags=re.DOTALL)
    if not match:
        raise PilotHalt("could not find the fenced system-prompt block in the template")
    return match.group(1).strip()


def verify_hashes(manifest: dict) -> list[dict]:
    """Re-hash all three saved pilot files and compare to the manifest.
    Returns the manifest's pilot entries IN THE FIXED ORDER ABOVE. Raises
    PilotHalt (no model call at all) on any mismatch or missing file."""
    by_file = {Path(p["file"]).name: p for p in manifest["pilots"]}
    mismatches = []
    ordered_entries = []
    for filename in PILOT_FILES_IN_ORDER:
        entry = by_file.get(filename)
        if entry is None:
            mismatches.append(f"{filename}: not present in pilot-manifest.json")
            continue
        path = RESULTS_DIR / filename
        if not path.exists():
            mismatches.append(f"{filename}: file missing on disk")
            continue
        content = path.read_text(encoding="utf-8")
        actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if actual_hash != entry["sha256"]:
            mismatches.append(
                f"{filename}: hash mismatch (manifest={entry['sha256']}, actual={actual_hash})"
            )
            continue
        ordered_entries.append({**entry, "_content": content})
    if mismatches:
        raise PilotHalt("hash verification failed: " + "; ".join(mismatches))
    return ordered_entries


def valid_input_chunk_ids(payload: dict) -> set[str]:
    ids: set[str] = set()
    for node in payload.get("nodes", []):
        ids.update(node.get("source_chunk_ids", []))
    for edge in payload.get("domain_relationships", []):
        ids.update(edge.get("source_chunk_ids", []))
    return ids


def validate_report(parsed: Any, allowed_chunk_ids: set[str]) -> dict:
    """Formal checks only -- never a content-correctness judgement."""
    problems: list[str] = []
    out_of_input_ids: list[str] = []

    if not isinstance(parsed, dict):
        problems.append("top level is not a JSON object")
        return {"valid_structure": False, "problems": problems, "out_of_input_ids": out_of_input_ids}

    if not isinstance(parsed.get("summary"), str) or not parsed.get("summary"):
        problems.append("missing or empty 'summary' (expected non-empty string)")

    statements = parsed.get("key_statements")
    if not isinstance(statements, list) or not statements:
        problems.append("missing or empty 'key_statements' (expected a non-empty list)")
        statements = []

    for index, item in enumerate(statements):
        if not isinstance(item, dict):
            problems.append(f"key_statements[{index}] is not an object")
            continue
        if not isinstance(item.get("statement"), str) or not item.get("statement"):
            problems.append(f"key_statements[{index}].statement missing or empty")
        ids = item.get("source_chunk_ids")
        if not isinstance(ids, list) or not ids:
            problems.append(f"key_statements[{index}].source_chunk_ids missing or empty")
            continue
        for chunk_id in ids:
            if chunk_id not in allowed_chunk_ids:
                out_of_input_ids.append(str(chunk_id))

    valid_structure = not problems and not out_of_input_ids
    return {
        "valid_structure": valid_structure,
        "problems": problems,
        "out_of_input_ids": sorted(set(out_of_input_ids)),
        "note": "formal validation only -- not a judgement of the report's factual correctness",
    }


def call_model(llm, system_text: str, user_text: str) -> tuple[Any, dict]:
    from langchain_core.messages import HumanMessage, SystemMessage

    started = time.monotonic()
    response = llm.invoke([SystemMessage(content=system_text), HumanMessage(content=user_text)])
    elapsed = time.monotonic() - started

    usage = getattr(response, "usage_metadata", None) or {}
    token_usage = (response.response_metadata or {}).get("token_usage", {})
    prompt_tokens = usage.get("input_tokens", token_usage.get("prompt_tokens", "unknown"))
    completion_tokens = usage.get("output_tokens", token_usage.get("completion_tokens", "unknown"))
    finish_reason = (response.response_metadata or {}).get("finish_reason", "unknown")
    returned_model = (response.response_metadata or {}).get("model_name", "unknown")

    measurement = {
        "duration_seconds": round(elapsed, 3),
        "usage_prompt_tokens": prompt_tokens,
        "usage_completion_tokens": completion_tokens,
        "finish_reason": finish_reason,
        "returned_model": returned_model,
    }
    return response, measurement


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    system_prompt = extract_system_prompt(TEMPLATE_PATH.read_text(encoding="utf-8"))

    try:
        entries = verify_hashes(manifest)
    except PilotHalt as exc:
        print("HALT before any model call:", exc)
        RESULTS_DIR.joinpath("week4-pilot-run-summary.json").write_text(
            json.dumps({"halted_before_any_call": True, "reason": str(exc)}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        return 2

    planned_calls = len(entries)
    estimated_total_input = sum(e["constrained_input_token_estimate"] for e in entries)
    print(f"planned max calls: {planned_calls}")
    print(f"estimated total input tokens: {estimated_total_input}")
    print(f"output token cap per call: {MAX_OUTPUT_TOKENS}")

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

    results: list[dict] = []
    halted_reason: str | None = None

    for entry in entries:
        label = entry["label"]
        community_id = entry["community_id"]
        payload = json.loads(entry["_content"])
        allowed_ids = valid_input_chunk_ids(payload)

        record: dict[str, Any] = {
            "label": label,
            "community_id": community_id,
            "run_id": RUN_ID,
            "reporting_level": payload.get("reporting_level"),
            "prompt_version": PROMPT_VERSION,
            "requested_model": REQUESTED_MODEL,
            "input_hash": entry["sha256"],
            "estimated_input_tokens": entry["constrained_input_token_estimate"],
        }

        print(f"\n--- calling model for {label} ({community_id}) ---")
        try:
            response, measurement = call_model(llm, system_prompt, entry["_content"])
        except Exception as exc:  # noqa: BLE001 -- any API/client error is a hard stop
            record["error"] = f"{type(exc).__name__}: {exc}"
            results.append(record)
            halted_reason = f"API error on {label}: {record['error']}"
            RESULTS_DIR.joinpath(f"week4-pilot-report-{label}-{community_id}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            break

        record.update({
            "returned_model": measurement["returned_model"],
            "duration_seconds": measurement["duration_seconds"],
            "usage_prompt_tokens": measurement["usage_prompt_tokens"],
            "usage_completion_tokens": measurement["usage_completion_tokens"],
            "finish_reason": measurement["finish_reason"],
        })

        raw_path = RESULTS_DIR / f"week4-pilot-raw-{label}-{community_id}.json"
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

        if record["valid_json"]:
            validation = validate_report(parsed, allowed_ids)
            record["validation"] = validation
            record["report"] = parsed
        else:
            record["validation"] = {
                "valid_structure": False,
                "problems": ["response was not valid JSON"],
                "out_of_input_ids": [],
            }

        report_path = RESULTS_DIR / f"week4-pilot-report-{label}-{community_id}.json"
        report_path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        results.append(record)

        if measurement["finish_reason"] == "length":
            halted_reason = f"finish_reason=length on {label}"
            break
        if not record["valid_json"]:
            halted_reason = f"invalid JSON on {label}"
            break
        if not record["validation"]["valid_structure"]:
            halted_reason = f"invalid report structure or out-of-input citation on {label}: {record['validation']}"
            break

    remaining = [e["label"] for e in entries[len(results):]]
    summary = {
        "run_id": RUN_ID,
        "prompt_version": PROMPT_VERSION,
        "requested_model": REQUESTED_MODEL,
        "planned_calls": planned_calls,
        "completed_calls": len(results),
        "halted_reason": halted_reason,
        "not_run": remaining,
        "results": [
            {
                "label": r["label"],
                "community_id": r["community_id"],
                "estimated_input_tokens": r["estimated_input_tokens"],
                "usage_prompt_tokens": r.get("usage_prompt_tokens", "unknown"),
                "usage_completion_tokens": r.get("usage_completion_tokens", "unknown"),
                "finish_reason": r.get("finish_reason", "unknown"),
                "duration_seconds": r.get("duration_seconds", "unknown"),
                "valid_json": r.get("valid_json"),
                "valid_structure": r.get("validation", {}).get("valid_structure"),
                "out_of_input_ids": r.get("validation", {}).get("out_of_input_ids", []),
                "error": r.get("error"),
            }
            for r in results
        ],
    }
    RESULTS_DIR.joinpath("week4-pilot-run-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("\n=== summary ===")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if halted_reason is None else 1


if __name__ == "__main__":
    sys.exit(main())
