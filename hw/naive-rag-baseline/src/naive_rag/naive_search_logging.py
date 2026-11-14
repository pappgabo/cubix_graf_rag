"""Logging adapter for NaiveRAG's new, optional ``chat_call`` injection
point (``rag.py::NaiveRAG.__init__``).

``rag.py`` itself only gained the injection point; the actual logging
wrapper lives here, as a separate, new module. Passing ``chat_call=None``
(the default) leaves NaiveRAG's behaviour exactly as before.

Does not change the model, temperature, or any other setting: it wraps
whatever already-configured chat client it is given (e.g. the project's
own ``get_chat_model()``) and logs the call around it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .call_logging import CallParams, logged_call, save_log_entry

_ROLE_FROM_LC_TYPE = {"system": "system", "human": "user", "ai": "assistant"}


def _message_to_dict(message: Any) -> dict[str, str]:
    """Exact role/content extraction from the langchain message object that
    is actually about to be sent -- not a reconstruction."""
    role = _ROLE_FROM_LC_TYPE.get(getattr(message, "type", ""), getattr(message, "type", "user"))
    return {"role": role, "content": message.content}


def _client_params(chat_client: Any) -> CallParams:
    """Best-effort introspection of the already-configured client; does not
    change any of its settings."""
    return CallParams(
        model=getattr(chat_client, "model_name", None) or getattr(chat_client, "model", "unknown"),
        temperature=getattr(chat_client, "temperature", "unknown"),
        max_tokens=getattr(chat_client, "max_tokens", None),
        response_format=None,
        max_retries=getattr(chat_client, "max_retries", 0),
    )


def make_logged_chat_call(
    chat_client: Any, *, log_dir: Path | None = None, question_id: str | None = None,
) -> Callable[[list], str]:
    """Returns a function matching NaiveRAG's ``chat_call`` signature
    (``Callable[[list[BaseMessage]], str]``) that logs the exact messages
    sent to ``chat_client.invoke`` and the exact response received."""
    params = _client_params(chat_client)

    def raw_caller(messages: list[dict[str, str]], call_params: CallParams) -> Any:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        role_cls = {"system": SystemMessage, "user": HumanMessage, "assistant": AIMessage}
        lc_messages = [role_cls[m["role"]](content=m["content"]) for m in messages]
        return chat_client.invoke(lc_messages)

    def chat_call(lc_messages: list) -> str:
        messages = [_message_to_dict(m) for m in lc_messages]
        local_metadata = {"question_id": question_id} if question_id else {}
        entry = logged_call(messages, params, raw_caller, local_metadata=local_metadata)
        if log_dir is not None:
            save_log_entry(log_dir / f"naive-log-{question_id or 'unknown'}.json", entry)
        if entry.error:
            raise RuntimeError(entry.error)
        return entry.raw_response

    return chat_call
