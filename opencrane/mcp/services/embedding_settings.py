"""Resolve the embedding model and query prompt the MCP server serves with.

``opencrane index`` records the model and prompts that built the collection
(see ``MilvusService.embedding_metadata``). Queries must be embedded the same
way, or search returns poor results without any error. For each of
``EMBEDDING_MODEL`` and ``EMBEDDING_QUERY_PROMPT``:

- unset: the value recorded in the index wins;
- set to the recorded value: used as is;
- set to a different value: :class:`EmbeddingSettingsMismatch` is raised, so the
  server refuses to serve instead of returning poor results.

An empty ``EMBEDDING_QUERY_PROMPT`` is an explicit "no prompt", so it counts as
set. An empty ``EMBEDDING_MODEL`` names no model and counts as unset.

A collection built before the settings were recorded falls back to the env
values and their defaults, as before.
"""

import logging
import os
from dataclasses import dataclass
from typing import Dict, Optional

from opencrane.shared.config import get_config

logger = logging.getLogger(__name__)

SOURCE_ENV = "env"
SOURCE_INDEX = "index"
SOURCE_DEFAULT = "default"


class EmbeddingSettingsMismatch(RuntimeError):
    """An env var names a different model or query prompt than the index recorded."""


@dataclass(frozen=True)
class EmbeddingSettings:
    """The model and query prompt in use, and where each came from."""

    model: str
    model_source: str
    query_prompt: str
    query_prompt_source: str
    document_prompt: str = ""

    def as_dict(self) -> Dict[str, str]:
        """Return the settings for the health report."""
        return {
            "model": self.model,
            "model_source": self.model_source,
            "query_prompt": self.query_prompt,
            "query_prompt_source": self.query_prompt_source,
        }


def _query_prompt_env() -> Optional[str]:
    """``EMBEDDING_QUERY_PROMPT`` with ``\\n`` unescaped, or ``None`` when unset."""
    value = os.getenv("EMBEDDING_QUERY_PROMPT")
    return None if value is None else value.replace("\\n", "\n")


def _resolve(name: str, env_value: Optional[str], recorded: Optional[str], default: str) -> tuple[str, str]:
    """Return ``(value, source)`` for one setting, raising on a conflict.

    ``env_value`` is ``None`` when the variable is unset.
    """
    if recorded is None:
        return (env_value, SOURCE_ENV) if env_value is not None else (default, SOURCE_DEFAULT)
    if env_value is None or env_value == recorded:
        return recorded, SOURCE_INDEX
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
            "using EMBEDDING_MODEL and EMBEDDING_QUERY_PROMPT. Rebuild it with "
            "'DROP_EXISTING=true opencrane index' so the server picks them up from the index."
        )
    metadata = metadata or {}
    model, model_source = _resolve(
        "EMBEDDING_MODEL",
        os.getenv("EMBEDDING_MODEL") or None,
        metadata.get("model"),
        config.embedding_model,
    )
    query_prompt, query_prompt_source = _resolve(
        "EMBEDDING_QUERY_PROMPT",
        _query_prompt_env(),
        metadata.get("query_prompt"),
        "",
    )
    return EmbeddingSettings(
        model=model,
        model_source=model_source,
        query_prompt=query_prompt,
        query_prompt_source=query_prompt_source,
        document_prompt=metadata.get("document_prompt", config.embedding_document_prompt),
    )


__all__ = [
    "EmbeddingSettings",
    "EmbeddingSettingsMismatch",
    "resolve_embedding_settings",
]
