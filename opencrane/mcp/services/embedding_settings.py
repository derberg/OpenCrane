"""Resolve the embedding model and query prompt the MCP server serves with.

``opencrane index`` records the model and the effective prompts that built the
collection (see ``MilvusService.embedding_metadata``). Queries must be embedded
the same way, or search returns poor results without any error. For each of
``EMBEDDING_MODEL`` and ``EMBEDDING_QUERY_PROMPT``:

- unset: the value recorded in the index wins;
- set to the recorded value: used as is;
- set to a different value: :class:`EmbeddingSettingsMismatch` is raised, so the
  server refuses to serve instead of returning poor results.

An empty ``EMBEDDING_QUERY_PROMPT`` is an explicit "no prompt", so it counts as
set. An empty ``EMBEDDING_MODEL`` names no model and counts as unset.

Without a recorded value (a collection built before the settings were
recorded), the model falls back to ``EMBEDDING_MODEL`` or its default, and the
prompts to ``embedding_prompts.resolve_prompt``: the model's own prompts, then
``KNOWN_MODEL_PROMPTS``.
"""

import dataclasses
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from opencrane.shared.config import get_config
from opencrane.shared.utils.embedding_prompts import resolve_document_prompt, resolve_query_prompt

logger = logging.getLogger(__name__)

SOURCE_ENV = "env"
SOURCE_INDEX = "index"
SOURCE_DEFAULT = "default"


class EmbeddingSettingsMismatch(RuntimeError):
    """An env var names a different model or query prompt than the index recorded."""


@dataclass(frozen=True)
class EmbeddingSettings:
    """The model and prompts in use, and where each came from."""

    model: str
    model_source: str
    query_prompt: str
    query_prompt_source: str
    document_prompt: str = ""
    document_prompt_source: str = SOURCE_DEFAULT

    def as_dict(self) -> Dict[str, str]:
        """Return the settings for the health report."""
        return {
            "model": self.model,
            "model_source": self.model_source,
            "query_prompt": self.query_prompt,
            "query_prompt_source": self.query_prompt_source,
        }


def _check(name: str, env_value: Optional[str], recorded: str) -> str:
    """Return ``recorded``, or raise when ``env_value`` is set to something else."""
    if env_value is None or env_value == recorded:
        return recorded
    raise EmbeddingSettingsMismatch(
        f"{name} is {env_value!r} but the index was built with {recorded!r}. "
        f"Either unset {name} (or set it to {recorded!r}) so the server uses the "
        f"indexed value, or rebuild the index with the new value: "
        f"'opencrane embed --force' then 'DROP_EXISTING=true opencrane index'."
    )


def resolve_embedding_settings(metadata: Optional[Dict]) -> EmbeddingSettings:
    """Combine the env with the settings recorded in the index.

    Args:
        metadata: ``MilvusService.embedding_metadata()``, or ``None`` for a
            collection that has no recorded settings.

    Raises:
        EmbeddingSettingsMismatch: an env var is set and differs from the
            recorded value.
    """
    config = get_config()
    if metadata is None:
        logger.warning(
            "The collection does not record its embedding model and query prompt; "
            "using EMBEDDING_MODEL and EMBEDDING_QUERY_PROMPT or the model's defaults. "
            "Rebuild it with 'DROP_EXISTING=true opencrane index' so the server "
            "picks them up from the index."
        )
    metadata = metadata or {}

    env_model = os.getenv("EMBEDDING_MODEL") or None
    if "model" in metadata:
        model, model_source = _check("EMBEDDING_MODEL", env_model, metadata["model"]), SOURCE_INDEX
    else:
        model = env_model or config.embedding_model
        model_source = SOURCE_ENV if env_model else SOURCE_DEFAULT

    env_query = config.embedding_query_prompt
    if "query_prompt" in metadata:
        query_prompt = _check("EMBEDDING_QUERY_PROMPT", env_query, metadata["query_prompt"])
        query_prompt_source = SOURCE_INDEX
    elif env_query is not None:
        query_prompt, query_prompt_source = env_query, SOURCE_ENV
    else:
        query_prompt, query_prompt_source = resolve_query_prompt(model_name=model), SOURCE_DEFAULT

    if "document_prompt" in metadata:
        document_prompt, document_prompt_source = metadata["document_prompt"], SOURCE_INDEX
    else:
        document_prompt, document_prompt_source = resolve_document_prompt(model_name=model), SOURCE_DEFAULT

    return EmbeddingSettings(
        model=model,
        model_source=model_source,
        query_prompt=query_prompt,
        query_prompt_source=query_prompt_source,
        document_prompt=document_prompt,
        document_prompt_source=document_prompt_source,
    )


def with_model_prompts(settings: EmbeddingSettings, model: Any) -> EmbeddingSettings:
    """Re-resolve the prompts the index does not record, now that *model* is loaded.

    Before the model loads, its prompts come from the cached config file, which
    is missing on a first run. Values from the index or the env stay as they are.
    """
    changes = {}
    if settings.query_prompt_source == SOURCE_DEFAULT:
        changes["query_prompt"] = resolve_query_prompt(model, settings.model)
    if settings.document_prompt_source == SOURCE_DEFAULT:
        changes["document_prompt"] = resolve_document_prompt(model, settings.model)
    return dataclasses.replace(settings, **changes) if changes else settings


__all__ = [
    "EmbeddingSettings",
    "EmbeddingSettingsMismatch",
    "resolve_embedding_settings",
    "with_model_prompts",
]
