"""Logging adapter for local_search()'s already-injected ``answer_fn``
(local_search.py:1037 -- ``answer_fn`` is a parameter, not hardcoded).

``local_search.py`` is not modified. Today's wiring
(``local_search.py:1200``, inside ``main()``) builds
``answer_fn=lambda prompt: chat.invoke(prompt).content`` directly; this
module supplies a logging-wrapped replacement with the exact same
observable behaviour (same return value for the same input), to be passed
to ``local_search()`` from a new call site instead. Using it still
requires a new entry point that calls ``local_search()`` directly (not
``local_search.main()``, which builds its own unlogged ``answer_fn`` and
is out of scope to modify here).

Does not change the model, temperature, context budget, or any other
local-search setting -- it wraps whatever already-configured chat client
it is given.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .call_logging import CallParams, logged_call, save_log_entry


def _client_params(chat_client: Any) -> CallParams:
    return CallParams(
        model=getattr(chat_client, "model_name", None) or getattr(chat_client, "model", "unknown"),
        temperature=getattr(chat_client, "temperature", "unknown"),
        max_tokens=getattr(chat_client, "max_tokens", None),
        response_format=None,
        max_retries=getattr(chat_client, "max_retries", 0),
    )


def make_logged_answer_fn(
    chat_client: Any, *, log_dir: Path | None = None, question_id: str | None = None,
) -> Callable[[str], str]:
    """``local_search()`` calls ``answer_fn(prompt: str)`` with a single
    string (the fully rendered prompt), not a message list -- so the
    logged "messages" here is exactly that string, wrapped as one user
    message. Nothing is reconstructed: this is the literal prompt
    ``local_search()`` built and is about to send."""
    params = _client_params(chat_client)

    def raw_caller(messages: list[dict[str, str]], call_params: CallParams) -> Any:
        return chat_client.invoke(messages[0]["content"])

    def answer_fn(prompt: str) -> str:
        messages = [{"role": "user", "content": prompt}]
        local_metadata = {"question_id": question_id} if question_id else {}
        entry = logged_call(messages, params, raw_caller, local_metadata=local_metadata)
        if log_dir is not None:
            save_log_entry(log_dir / f"local-log-{question_id or 'unknown'}.json", entry)
        if entry.error:
            raise RuntimeError(entry.error)
        return entry.raw_response

    return answer_fn
