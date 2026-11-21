"""Zero-shot LLM router: picks one of three target search modes (naiv,
lokalis, globalis) from the question text alone.

No few-shot examples from Q01-Q13 and no keyword list tailored to that
question set -- the prompt only characterizes, in general terms, what
each mode is good at and where it is weak. The evaluation-time mapping
from a question's type label (simple/multi-hop/global) to an "expected"
mode lives in ``router_eval.py``, not here: the router itself never sees
a question id, a type label, or a gold answer.

Every call goes through ``call_logging.logged_call`` so the exact sent
messages, their hash, and the full response are always on record.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .call_logging import CallLogEntry, CallParams, RawCaller, logged_call, save_log_entry

MODEL = "gpt-4o-mini"
TEMPERATURE = 0
MAX_TOKENS = 200
MAX_RETRIES = 0

VALID_MODES = ("naiv", "lokalis", "globalis", "drift")

ROUTER_SYSTEM_PROMPT = """
You choose which of four search modes should answer a question, based
only on the question's own wording. Do not rely on knowledge of any
specific test set or example questions -- judge only the general shape of
this one question.

Modes:
- "naiv": plain vector-similarity retrieval over document chunks, then an
  answer grounded only in the retrieved chunks. Good for a single,
  localized fact stated directly in one place. Weak when the answer
  requires connecting information across two or more different entities
  or documents, or aggregating across many documents.
- "lokalis": entity-anchored graph search. It anchors on the entities the
  question names, expands one hop over a typed relationship graph, and
  answers from that local neighborhood plus the originating text. Good
  when the question names one or two specific entities and needs a
  relationship between them or one hop away. Weak for a question that
  needs a broad, corpus-wide aggregation rather than a local hop.
- "globalis": a map-reduce search over community-level summaries that
  cover the whole graph. Good for a corpus-wide, aggregating, or
  "across all X" question. Weak for a question about one narrow, specific
  local fact, where a broad summary may dilute or miss a sharp detail.
- "drift": starts from the most relevant community-level summaries, like
  "globalis", but then follows up with at most two targeted local graph
  lookups on the entities those summaries point to, and combines both
  into one answer. Good for a corpus-wide question whose full answer
  still depends on one or two specific entity-level details a community
  summary alone tends to lose. Weak for a single, already-localized fact,
  where the extra community-level step adds cost without adding value.

Return only the following JSON, nothing else:

{"mode": "naiv" | "lokalis" | "globalis" | "drift", "reasoning": "<one sentence>"}
""".strip()


def router_messages(question: str) -> list[dict[str, str]]:
    """The question text is the only question-specific content. No id,
    label, or gold answer is ever placed here."""
    return [
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]


@dataclass(frozen=True)
class RouterValidation:
    valid_structure: bool
    problems: tuple[str, ...]


def validate_router_response(parsed: Any) -> RouterValidation:
    if not isinstance(parsed, dict):
        return RouterValidation(False, ("top level is not a JSON object",))
    problems: list[str] = []
    if parsed.get("mode") not in VALID_MODES:
        problems.append(f"mode missing or not one of {VALID_MODES}")
    if not isinstance(parsed.get("reasoning"), str) or not parsed.get("reasoning"):
        problems.append("reasoning missing or empty")
    return RouterValidation(not problems, tuple(problems))


def route_one(
    question_id: str, question_text: str, raw_caller: RawCaller, *, log_path: Path | None = None,
) -> dict:
    """Route a single question. ``question_id`` is local metadata only --
    it never enters ``router_messages``. Returns a record with the chosen
    mode/reasoning (or an error/invalid status) plus the full call log."""
    import json

    messages = router_messages(question_text)
    params = CallParams(
        model=MODEL, temperature=TEMPERATURE, max_tokens=MAX_TOKENS,
        response_format={"type": "json_object"}, max_retries=MAX_RETRIES,
    )
    entry = logged_call(messages, params, raw_caller, local_metadata={"question_id": question_id})
    if log_path is not None:
        save_log_entry(log_path, entry)

    record: dict[str, Any] = {
        "question_id": question_id,
        "requested_model": MODEL,
        "messages_sha256": entry.messages_sha256,
        "duration_seconds": entry.duration_seconds,
        "usage_prompt_tokens": entry.usage_prompt_tokens,
        "usage_completion_tokens": entry.usage_completion_tokens,
        "finish_reason": entry.finish_reason,
        "returned_model": entry.returned_model,
    }
    if entry.error:
        record["error"] = entry.error
        return record
    try:
        parsed = json.loads(entry.raw_response)
        record["valid_json"] = True
    except (json.JSONDecodeError, TypeError) as exc:
        record["valid_json"] = False
        record["json_error"] = str(exc)
        return record
    validation = validate_router_response(parsed)
    record["validation"] = {"valid_structure": validation.valid_structure, "problems": list(validation.problems)}
    if validation.valid_structure:
        record["mode"] = parsed["mode"]
        record["reasoning"] = parsed["reasoning"]
    return record


def route_many(
    questions: list[tuple[str, str]], raw_caller: RawCaller, *, log_dir: Path | None = None,
) -> list[dict]:
    """``questions`` is a list of (question_id, question_text) pairs."""
    records = []
    for question_id, question_text in questions:
        log_path = (log_dir / f"router-log-{question_id}.json") if log_dir else None
        records.append(route_one(question_id, question_text, raw_caller, log_path=log_path))
    return records
