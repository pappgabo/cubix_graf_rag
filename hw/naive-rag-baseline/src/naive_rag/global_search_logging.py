"""Logging adapter for global_search's already-injected ``call_fn``
(``ModelCall = Callable[[str, str, int], ModelResponse]`` -- see
``global_search.py``'s ``process_one_map``/``process_one_reduce``, both of
which take ``call_fn`` as a parameter, not a hardcoded client).

``global_search.py`` is not modified. This module provides a
``ModelCall``-compatible function that logs the exact system/user text
sent and the exact response, then converts the result back into
``global_search.ModelResponse`` so the existing orchestration
(``run_phase4``, ``run_question``, ...) keeps working unchanged.

Known limitation (not solved here, would need to modify global_search.py):
``ModelCall``'s signature is ``(system, user, max_tokens) -> ModelResponse``
-- it carries no question id or community path. This wrapper can
therefore only distinguish calls by a sequential counter, not by
question/community; attaching that identifying metadata at the log level
would require call_fn to carry it, which means changing the call sites in
``global_search.py`` (``process_one_map``/``process_one_reduce``) -- out
of scope for this change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .call_logging import CallParams, logged_call, save_log_entry
from .global_search import MODEL, ModelResponse


def _default_client_factory(settings: Any):
    def factory(call_params: CallParams):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=call_params.model, temperature=call_params.temperature,
            max_retries=call_params.max_retries, max_tokens=call_params.max_tokens,
            api_key=settings.openai_api_key,
            model_kwargs={"response_format": call_params.response_format},
        )

    return factory


def make_logged_call_fn(
    settings: Any, *, log_dir: Path | None = None, prefix: str = "global",
    client_factory=None,
):
    """``settings`` must expose ``openai_api_key`` (e.g.
    ``naive_rag.config.get_settings()``), unchanged from how
    ``global_search.make_openai_caller()`` already reads it.

    ``client_factory(call_params) -> client-with-.invoke`` is dependency
    injection for tests (a fake client); it defaults to building a real
    ``ChatOpenAI`` with the exact given parameters."""
    factory = client_factory or _default_client_factory(settings)
    counter = {"n": 0}

    def raw_caller(messages: list[dict[str, str]], call_params: CallParams) -> Any:
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = factory(call_params)
        lc_messages = [SystemMessage(content=messages[0]["content"]), HumanMessage(content=messages[1]["content"])]
        return llm.invoke(lc_messages)

    def call(system_prompt: str, user_message: str, max_tokens: int) -> ModelResponse:
        counter["n"] += 1
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}]
        params = CallParams(
            model=MODEL, temperature=0, max_tokens=max_tokens,
            response_format={"type": "json_object"}, max_retries=0,
        )
        entry = logged_call(messages, params, raw_caller, local_metadata={"call_index": counter["n"]})
        if log_dir is not None:
            save_log_entry(log_dir / f"{prefix}-log-{counter['n']:04d}.json", entry)
        if entry.error:
            raise RuntimeError(entry.error)
        return ModelResponse(
            content=entry.raw_response,
            returned_model=entry.returned_model,
            usage_prompt_tokens=entry.usage_prompt_tokens,
            usage_completion_tokens=entry.usage_completion_tokens,
            finish_reason=entry.finish_reason,
        )

    return call
