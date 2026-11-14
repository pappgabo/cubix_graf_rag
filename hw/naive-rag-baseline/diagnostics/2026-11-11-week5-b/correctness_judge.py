"""Structured correctness judge: prompt build, response validation, and
the deterministic labeling rule described in
``judges/correctness_judge_prompt_v1.md``.

The model call itself is dependency-injected (``call_fn``), exactly like
the existing project's ``global_search.ModelCall`` pattern -- this module
never imports an OpenAI/LangChain client directly, so it can be fully
unit-tested with a fake. No call is issued anywhere in this module unless
the caller supplies one and invokes ``judge_one``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from golden_set import GoldenQuestion

PROMPT_VERSION = "correctness_judge_prompt_v1"
PROMPT_PATH = Path(__file__).resolve().parent / "judges" / f"{PROMPT_VERSION}.md"
MODEL = "gpt-4o-mini"
MAX_TOKENS = 700

VALID_VERDICTS = ("met", "not_met", "unclear")

SYSTEM_PROMPT = """
You judge whether an already-produced answer satisfies a fixed set of
grading criteria for one question. You do not answer the question
yourself and you do not use any outside knowledge of Formula One beyond
what the criteria already state.

You receive a JSON object with:
- "question": the original question text
- "answer": the system's answer to judge
- "criteria": a list of {"id", "text", "expected_content", "required"} --
  "expected_content" are semantic hints, not literal strings the answer
  must quote verbatim. Judge meaning, not exact wording. Accept correct
  name variants (e.g. "Lewis Hamilton" vs "Hamilton"), accept a concise
  answer that omits content explicitly marked optional in the criterion
  text.
- "notes": evaluator notes relevant to this question's grading policy
  (may be empty).

For each criterion, decide one of "met", "not_met", "unclear" ("unclear"
when the answer is ambiguous about that specific criterion, not merely
terse).

Separately decide:
- "refused": true only if the answer is a full refusal to answer (states
  it cannot answer from the available material, or an explicit refusal
  sentence), not merely a short or partial answer. A partial answer is
  NOT a refusal.
- "rubric_conflicts": a list of short strings, each describing a concrete
  factual contradiction between the answer and something the supplied
  criteria/notes themselves state as fact (e.g. the answer names the
  reversed entity in a relationship the criteria pin down). Only include
  a conflict you can point to directly in the given criteria or notes --
  do NOT add a conflict based on your own outside Formula One knowledge.
  Empty list if there is no such rubric-provable conflict.

Return only this JSON, nothing else:

{
  "criteria": [
    {"criterion_id": "<id from input>", "verdict": "met" | "not_met" | "unclear",
     "explanation": "<one sentence>"}
  ],
  "refused": <bool>,
  "rubric_conflicts": ["<string>", ...],
  "reasoning": "<one or two sentences, overall>"
}

Every criterion id from the input must appear exactly once in the output
"criteria" list. Never invent a criterion id that was not supplied.
""".strip()


def judge_user_message(question: GoldenQuestion, answer: str) -> str:
    """Never includes gold evidence_groups/chunk ids/status/type -- only
    what the judge prompt documents it needs."""
    payload = {
        "question": question.question,
        "answer": answer,
        "criteria": [
            {
                "id": c.id, "text": c.text,
                "expected_content": list(c.expected_content),
                "required": c.required,
            }
            for c in question.criteria
        ],
        "notes": question.notes,
    }
    return json.dumps(payload, ensure_ascii=False, indent=1) + "\n"


@dataclass(frozen=True)
class CorrectnessValidation:
    valid_structure: bool
    problems: tuple[str, ...]


def validate_judge_response(parsed: Any, question: GoldenQuestion) -> CorrectnessValidation:
    if not isinstance(parsed, dict):
        return CorrectnessValidation(False, ("top level is not a JSON object",))
    problems: list[str] = []

    criteria = parsed.get("criteria")
    expected_ids = {c.id for c in question.criteria}
    if not isinstance(criteria, list):
        problems.append("criteria missing or not a list")
        criteria = []
    seen_ids: set[str] = set()
    for item in criteria:
        if not isinstance(item, dict):
            problems.append(f"criteria item is not an object: {item!r}")
            continue
        cid = item.get("criterion_id")
        if cid not in expected_ids:
            problems.append(f"unknown or missing criterion_id: {cid!r}")
            continue
        if cid in seen_ids:
            problems.append(f"duplicate criterion_id: {cid!r}")
        seen_ids.add(cid)
        if item.get("verdict") not in VALID_VERDICTS:
            problems.append(f"criterion {cid!r}: verdict missing or invalid")
    missing = expected_ids - seen_ids
    if missing:
        problems.append(f"missing verdict for criterion ids: {sorted(missing)}")

    if not isinstance(parsed.get("refused"), bool):
        problems.append("refused missing or not a boolean")

    conflicts = parsed.get("rubric_conflicts")
    if not isinstance(conflicts, list) or not all(isinstance(x, str) for x in conflicts):
        problems.append("rubric_conflicts missing or not a list of strings")

    if not isinstance(parsed.get("reasoning"), str):
        problems.append("reasoning missing or not a string")

    return CorrectnessValidation(not problems, tuple(problems))


Label = str  # "helyes" | "hiányos" | "elutasított" | "téves" | "error"


def label_from_judgement(parsed: dict, question: GoldenQuestion) -> Label:
    """Implements judges/correctness_judge_prompt_v1.md's labeling rule.
    Caller must have already validated the structure (validate_judge_response)
    -- this function assumes a structurally valid ``parsed``."""
    if parsed.get("rubric_conflicts"):
        return "téves"
    if parsed.get("refused") is True:
        return "elutasított"
    verdict_by_id = {item["criterion_id"]: item["verdict"] for item in parsed["criteria"]}
    required_ids = [c.id for c in question.required_criteria()]
    if all(verdict_by_id.get(cid) == "met" for cid in required_ids):
        return "helyes"
    return "hiányos"


# ModelCall matches global_search.ModelCall's shape: (system, user, max_tokens) -> response object
ModelCall = Callable[[str, str, int], Any]


def judge_one(
    question: GoldenQuestion, answer: str, call_fn: ModelCall,
) -> dict:
    """Runs exactly one judge call via the injected ``call_fn`` and returns
    a full record (raw response, validation, label on success, or an
    explicit "error" status on a technical/JSON/structure failure --
    never silently mapped to "hiányos")."""
    user = judge_user_message(question, answer)
    record: dict[str, Any] = {
        "question_id": question.id, "prompt_version": PROMPT_VERSION, "requested_model": MODEL,
    }
    try:
        response = call_fn(SYSTEM_PROMPT, user, MAX_TOKENS)
    except Exception as exc:  # noqa: BLE001
        record["status"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record

    record.update({
        "returned_model": getattr(response, "returned_model", None),
        "usage_prompt_tokens": getattr(response, "usage_prompt_tokens", "unknown"),
        "usage_completion_tokens": getattr(response, "usage_completion_tokens", "unknown"),
        "finish_reason": getattr(response, "finish_reason", None),
        "raw_response": getattr(response, "content", None),
    })

    try:
        parsed = json.loads(record["raw_response"])
    except (json.JSONDecodeError, TypeError) as exc:
        record["status"] = "error"
        record["error"] = f"invalid JSON: {exc}"
        return record

    validation = validate_judge_response(parsed, question)
    if not validation.valid_structure or record.get("finish_reason") == "length":
        record["status"] = "error"
        problems = list(validation.problems)
        if record.get("finish_reason") == "length":
            problems.append("finish_reason=length")
        record["error"] = "; ".join(problems)
        return record

    record["status"] = "scored"
    record["parsed"] = parsed
    record["label"] = label_from_judgement(parsed, question)
    return record
