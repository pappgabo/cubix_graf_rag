"""Claim-level faithfulness judge: own metric, explicitly not Ragas
faithfulness (Ragas is not installed in this project -- see
docs/week5-felmeres.md section 2). Prompt build, response validation,
and scoring per ``judges/faithfulness_judge_prompt_v1.md``.

The model call is dependency-injected (``call_fn``); this module never
calls a model on its own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

PROMPT_VERSION = "faithfulness_judge_prompt_v1"
PROMPT_PATH = Path(__file__).resolve().parent / "judges" / f"{PROMPT_VERSION}.md"
MODEL = "gpt-4o-mini"
MAX_TOKENS = 900

VALID_VERDICTS = ("supported", "unsupported", "unclear")

SYSTEM_PROMPT = """
You check whether an answer's factual claims are supported by the exact
context that was actually given to the system that produced the answer.
You do not use any outside knowledge of Formula One. Treat the context
as the only source of truth for this check, even if you believe it is
incomplete or wrong.

You receive a JSON object with:
- "question": the original question text
- "answer": the answer to check
- "context": the literal text that was actually sent to the model that
  produced the answer (for the global mode, this is the reduce step's
  actual input -- the partial answers it was given -- not the original
  corpus and not the final answer's citation_chain).

Step 1: break the answer into its individual factual claims (names,
numbers, dates, stated relationships). Ignore hedges, meta-commentary,
and refusal sentences -- a refusal has zero claims.

Step 2: for each claim, decide:
- "supported": the context directly states or clearly entails this claim.
- "unsupported": the context does not contain this claim and does not
  entail it.
- "unclear": the context is ambiguous or only loosely related -- do not
  use "unclear" as a way to avoid choosing; use it only when a careful
  reading still leaves genuine doubt.

Return only this JSON, nothing else:

{
  "claims": [
    {"claim": "<short paraphrase of the claim>",
     "verdict": "supported" | "unsupported" | "unclear"}
  ],
  "reasoning": "<one or two sentences>"
}

If the answer has no factual claims (e.g. it is a refusal), return an
empty "claims" list.
""".strip()


def judge_user_message(question_text: str, answer: str, context: str) -> str:
    payload = {"question": question_text, "answer": answer, "context": context}
    return json.dumps(payload, ensure_ascii=False, indent=1) + "\n"


@dataclass(frozen=True)
class FaithfulnessValidation:
    valid_structure: bool
    problems: tuple[str, ...]


def validate_judge_response(parsed: Any) -> FaithfulnessValidation:
    if not isinstance(parsed, dict):
        return FaithfulnessValidation(False, ("top level is not a JSON object",))
    problems: list[str] = []
    claims = parsed.get("claims")
    if not isinstance(claims, list):
        problems.append("claims missing or not a list")
        claims = []
    for item in claims:
        if not isinstance(item, dict) or not isinstance(item.get("claim"), str):
            problems.append(f"claim item malformed: {item!r}")
            continue
        if item.get("verdict") not in VALID_VERDICTS:
            problems.append(f"claim {item.get('claim')!r}: verdict missing or invalid")
    if not isinstance(parsed.get("reasoning"), str):
        problems.append("reasoning missing or not a string")
    return FaithfulnessValidation(not problems, tuple(problems))


def score_from_judgement(parsed: dict) -> dict:
    """score is "n/a" (never 0 or 1 by default) when there are no scored
    claims. unclear counts as not-supported for the score but is counted
    separately."""
    claims = parsed.get("claims") or []
    supported = sum(1 for c in claims if c["verdict"] == "supported")
    unsupported = sum(1 for c in claims if c["verdict"] == "unsupported")
    unclear = sum(1 for c in claims if c["verdict"] == "unclear")
    scored_count = supported + unsupported + unclear
    score = (supported / scored_count) if scored_count else "n/a"
    return {
        "supported_count": supported,
        "unsupported_count": unsupported,
        "unclear_count": unclear,
        "scored_count": scored_count,
        "score": score,
    }


ModelCall = Callable[[str, str, int], Any]


def judge_one(
    question_id: str, question_text: str, answer: str, context: str, call_fn: ModelCall,
) -> dict:
    user = judge_user_message(question_text, answer, context)
    record: dict[str, Any] = {
        "question_id": question_id, "prompt_version": PROMPT_VERSION, "requested_model": MODEL,
        "context_chars": len(context),
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

    validation = validate_judge_response(parsed)
    if not validation.valid_structure or record.get("finish_reason") == "length":
        record["status"] = "error"
        problems = list(validation.problems)
        if record.get("finish_reason") == "length":
            problems.append("finish_reason=length")
        record["error"] = "; ".join(problems)
        return record

    record["status"] = "scored"
    record["parsed"] = parsed
    record["scoring"] = score_from_judgement(parsed)
    return record
