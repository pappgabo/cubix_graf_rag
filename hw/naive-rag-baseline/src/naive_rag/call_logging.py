"""Mandatory request/response logging for every future generative model
call (router, naive, local, global map/reduce).

The Phase 4 audit found that the actually-transmitted messages were never
saved -- only the response. This module exists so that never happens
again: it logs the EXACT message list passed to the client (not a
reconstruction built afterward from other saved data), its SHA-256 hash,
the model id and call parameters, the raw response, usage, finish_reason,
duration, and any error.

``question_id``, a type label, and a gold answer must never appear inside
``messages`` -- those belong in ``local_metadata``, which this module
keeps in a clearly separate field and never passes to ``raw_caller``.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

HASH_ALGORITHM = "sha256"
HASH_ENCODING = "utf-8"


def hash_messages(messages: list[dict[str, str]]) -> str:
    """Hash of the deterministic JSON serialization of the exact message
    list (role/content pairs, in order) that is about to be sent."""
    canonical = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode(HASH_ENCODING)).hexdigest()


@dataclass(frozen=True)
class CallParams:
    model: str
    temperature: float
    max_tokens: int
    response_format: dict | None
    max_retries: int = 0

    def to_json(self) -> dict:
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": self.response_format,
            "max_retries": self.max_retries,
        }


@dataclass(frozen=True)
class CallLogEntry:
    messages: list[dict[str, str]]
    messages_sha256: str
    params: CallParams
    raw_response: str | None
    returned_model: str | None
    usage_prompt_tokens: int | str
    usage_completion_tokens: int | str
    finish_reason: str | None
    duration_seconds: float
    error: str | None
    local_metadata: dict[str, Any]

    def to_json(self) -> dict:
        return {
            "messages": self.messages,
            "messages_sha256": self.messages_sha256,
            "hash_algorithm": HASH_ALGORITHM,
            "hash_encoding": HASH_ENCODING,
            "params": self.params.to_json(),
            "raw_response": self.raw_response,
            "returned_model": self.returned_model,
            "usage_prompt_tokens": self.usage_prompt_tokens,
            "usage_completion_tokens": self.usage_completion_tokens,
            "finish_reason": self.finish_reason,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "local_metadata": self.local_metadata,
        }


# raw_caller(messages, params) -> an object with .content, .response_metadata
# (dict incl. token_usage/finish_reason/model_name), .usage_metadata -- the
# same shape langchain's AIMessage already has (matches
# global_search.ModelResponse's source shape before conversion).
RawCaller = Callable[[list[dict[str, str]], CallParams], Any]


def logged_call(
    messages: list[dict[str, str]], params: CallParams, raw_caller: RawCaller,
    *, local_metadata: dict[str, Any] | None = None,
) -> CallLogEntry:
    """Call ``raw_caller`` with exactly ``messages``/``params`` and log
    exactly what was sent and what came back. Never reconstructs the
    messages afterward -- the same list object that was handed to
    ``raw_caller`` is what gets logged."""
    metadata = dict(local_metadata or {})
    started = time.monotonic()
    try:
        response = raw_caller(messages, params)
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - started
        return CallLogEntry(
            messages=messages, messages_sha256=hash_messages(messages), params=params,
            raw_response=None, returned_model=None,
            usage_prompt_tokens="unknown", usage_completion_tokens="unknown",
            finish_reason=None, duration_seconds=round(elapsed, 3),
            error=f"{type(exc).__name__}: {exc}", local_metadata=metadata,
        )
    elapsed = time.monotonic() - started
    usage = getattr(response, "usage_metadata", None) or {}
    response_metadata = getattr(response, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage", {})
    return CallLogEntry(
        messages=messages, messages_sha256=hash_messages(messages), params=params,
        raw_response=getattr(response, "content", None),
        returned_model=response_metadata.get("model_name"),
        usage_prompt_tokens=usage.get("input_tokens", token_usage.get("prompt_tokens", "unknown")),
        usage_completion_tokens=usage.get("output_tokens", token_usage.get("completion_tokens", "unknown")),
        finish_reason=response_metadata.get("finish_reason"),
        duration_seconds=round(elapsed, 3),
        error=None, local_metadata=metadata,
    )


def save_log_entry(path: Path, entry: CallLogEntry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry.to_json(), ensure_ascii=False, indent=1), encoding="utf-8")


def make_langchain_raw_caller(client_factory: Callable[[CallParams], Any]) -> RawCaller:
    """Adapts a langchain ChatOpenAI-style client to the RawCaller shape.

    ``client_factory(params)`` must return an object with an ``.invoke``
    method taking a list of langchain message objects. This function
    converts the plain {"role", "content"} dicts in ``messages`` to
    SystemMessage/HumanMessage just before the call -- the dicts logged by
    ``logged_call`` are still the plain, JSON-serializable ones.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    role_to_message = {"system": SystemMessage, "user": HumanMessage}

    def call(messages: list[dict[str, str]], params: CallParams) -> Any:
        client = client_factory(params)
        lc_messages = [role_to_message[m["role"]](content=m["content"]) for m in messages]
        return client.invoke(lc_messages)

    return call
