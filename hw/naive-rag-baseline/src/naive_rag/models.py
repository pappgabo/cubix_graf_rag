"""Factory helpers for the chat model and the embeddings.

Provider is selected via settings.llm_provider ("openai" or "ollama"),
so the rest of the pipeline stays provider-agnostic.
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from .config import get_settings


def get_chat_model(*, streaming: bool = False) -> BaseChatModel:
    s = get_settings()
    if s.llm_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=s.chat_model,
            temperature=0,
            streaming=streaming,
            api_key=s.openai_api_key,
        )
    if s.llm_provider == "ollama":
        from langchain_ollama import ChatOllama  # optional dependency
        return ChatOllama(
            model=s.ollama_chat_model,
            base_url=s.ollama_base_url,
            temperature=0,
        )
    raise ValueError(f"Unknown llm_provider: {s.llm_provider!r}")


def get_embeddings() -> Embeddings:
    s = get_settings()
    if s.llm_provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(
            model=s.embedding_model,
            api_key=s.openai_api_key,
        )
    if s.llm_provider == "ollama":
        from langchain_ollama import OllamaEmbeddings  # optional dependency
        return OllamaEmbeddings(
            model=s.ollama_embedding_model,
            base_url=s.ollama_base_url,
        )
    raise ValueError(f"Unknown llm_provider: {s.llm_provider!r}")
