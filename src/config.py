"""Central configuration: environment settings plus LangChain model factories.

Only this module instantiates provider classes (``ChatGroq`` /
``ChatGoogleGenerativeAI`` / ``HuggingFaceEmbeddings``). Everything else asks for
a model via :func:`chat_model`, :func:`router_model`, or :func:`embeddings`.

There is no local LLM fallback by design: if both hosted providers are
unreachable, the call raises and the caller surfaces the error.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.runnables import Runnable

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
CACHE_DIR = REPO_ROOT / "cache"

PROVIDERS = ("groq", "google")
EMBED_DIM = 384  # BAAI/bge-small-en-v1.5


class Settings(BaseSettings):
    """Loaded from ``.env`` (see ``.env.example``); env vars override."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # datastores
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "meridian-dev"
    postgres_dsn: str = (
        "postgresql+psycopg://meridian:meridian-dev@localhost:5432/meridian"
    )

    # llm providers
    llm_provider: str = "groq"  # primary; the other in PROVIDERS is the fallback
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_router_model: str = "llama-3.1-8b-instant"
    google_api_key: str = ""
    google_model: str = "gemini-2.0-flash"

    # embeddings (local)
    embed_model: str = "BAAI/bge-small-en-v1.5"

    # generation params
    temperature: float = 0.0
    max_output_tokens: int = 4096
    router_max_tokens: int = 512

    # logging
    log_level: str = "INFO"

    @property
    def psycopg_dsn(self) -> str:
        """DSN without the SQLAlchemy-style ``+psycopg`` driver tag."""
        return self.postgres_dsn.replace("postgresql+psycopg://", "postgresql://")


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


# --------------------------------------------------------------------------- #
# LLM cache
# --------------------------------------------------------------------------- #
_cache_ready = False


def configure_llm_cache() -> None:
    """Enable the on-disk SQLite LLM cache (idempotent).

    Deterministic prompts (extraction) then cost nothing on re-run. Delete the
    ``cache/`` directory to force a rebuild.
    """
    global _cache_ready
    if _cache_ready:
        return
    from langchain_community.cache import SQLiteCache
    from langchain_core.globals import set_llm_cache

    CACHE_DIR.mkdir(exist_ok=True)
    set_llm_cache(SQLiteCache(database_path=str(CACHE_DIR / "llm.db")))
    _cache_ready = True


# --------------------------------------------------------------------------- #
# Model factories
# --------------------------------------------------------------------------- #
def build_chat_model(provider: str, *, router: bool = False) -> "BaseChatModel":
    """Build a single provider's chat model (no fallback).

    Args:
        provider: One of :data:`PROVIDERS`.
        router: Use the smaller/cheaper model and a tighter token budget.

    Returns:
        A configured LangChain chat model.

    Raises:
        ValueError: If ``provider`` is unknown.
    """
    max_tokens = settings.router_max_tokens if router else settings.max_output_tokens

    if provider == "groq":
        from langchain_groq import ChatGroq

        model = settings.groq_router_model if router else settings.groq_model
        return ChatGroq(
            model=model,
            api_key=settings.groq_api_key or "unset",
            temperature=settings.temperature,
            max_tokens=max_tokens,
        )

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=settings.google_model,
            google_api_key=settings.google_api_key or "unset",
            temperature=settings.temperature,
            max_output_tokens=max_tokens,
        )

    raise ValueError(f"unknown LLM provider: {provider!r} (expected one of {PROVIDERS})")


def _ordered_providers() -> list[str]:
    primary = settings.llm_provider
    if primary not in PROVIDERS:
        raise ValueError(f"LLM_PROVIDER={primary!r} must be one of {PROVIDERS}")
    return [primary, *(p for p in PROVIDERS if p != primary)]


def chat_model(
    structured: type[BaseModel] | None = None, *, router: bool = False
) -> "Runnable":
    """Primary chat model with automatic fallback to the other provider.

    Args:
        structured: If given, bind this Pydantic model as the response schema
            (``with_structured_output``); ``invoke`` then returns an instance.
        router: Use the router model / token budget.

    Returns:
        A runnable. ``.invoke(str | messages)`` returns an ``AIMessage`` (or a
        ``structured`` instance). Falls back provider-to-provider on error.
    """
    configure_llm_cache()
    models: list[Runnable] = [
        build_chat_model(p, router=router) for p in _ordered_providers()
    ]
    if structured is not None:
        models = [m.with_structured_output(structured) for m in models]
    primary, *rest = models
    return primary.with_fallbacks(rest) if rest else primary


def router_model(structured: type[BaseModel] | None = None) -> "Runnable":
    """Chat model tuned for the question router (small model, short output)."""
    return chat_model(structured, router=True)


@functools.lru_cache
def embeddings():
    """Local sentence-transformers embeddings (``bge-small``, 384-dim, cached)."""
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=settings.embed_model,
        encode_kwargs={"normalize_embeddings": True},
    )
