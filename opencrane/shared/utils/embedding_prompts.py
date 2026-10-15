"""Task prompts for asymmetric embedding models.

Many retrieval models are trained with different prompts for documents and
queries (nomic-embed-text-v1.5: ``search_document: `` / ``search_query: ``;
Qwen3-Embedding: bare documents, ``Instruct: <task>\\nQuery:`` queries).

Each prompt resolves in this order:

1. ``EMBEDDING_DOCUMENT_PROMPT`` / ``EMBEDDING_QUERY_PROMPT`` when set, even to
   an empty string, which means "no prompt".
2. The prompts the model ships in ``config_sentence_transformers.json``
   (``model.prompts`` once loaded).
3. :data:`KNOWN_MODEL_PROMPTS`, for models that need prompts but don't ship them.
4. Empty: the text is encoded as-is.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from opencrane.shared.config import get_config

logger = logging.getLogger(__name__)

QUERY_PLACEHOLDER = "{query}"

DOCUMENT = "document"
QUERY = "query"

# Keys a model's ``prompts`` dict may use for each kind, in order of preference.
_PROMPT_ALIASES: Dict[str, Tuple[str, ...]] = {
    DOCUMENT: ("document", "passage", "search_document"),
    QUERY: ("query", "search_query"),
}

# Models whose model card requires prompts that the model doesn't ship in
# config_sentence_transformers.json: (document prompt, query prompt).
KNOWN_MODEL_PROMPTS: Dict[str, Tuple[str, str]] = {
    "nomic-ai/nomic-embed-text-v1": ("search_document: ", "search_query: "),
    "nomic-ai/nomic-embed-text-v1.5": ("search_document: ", "search_query: "),
    "intfloat/e5-small-v2": ("passage: ", "query: "),
    "intfloat/e5-base-v2": ("passage: ", "query: "),
    "intfloat/e5-large-v2": ("passage: ", "query: "),
    "intfloat/multilingual-e5-small": ("passage: ", "query: "),
    "intfloat/multilingual-e5-base": ("passage: ", "query: "),
    "intfloat/multilingual-e5-large": ("passage: ", "query: "),
}

_ENV_VARS = {DOCUMENT: "EMBEDDING_DOCUMENT_PROMPT", QUERY: "EMBEDDING_QUERY_PROMPT"}
_ST_CONFIG_FILE = "config_sentence_transformers.json"


def read_model_prompts(model_name: str) -> Optional[Dict[str, Any]]:
    """Read the prompts a model ships, without loading the model.

    Looks in a local model directory, then in the Hugging Face cache (no
    network). Returns ``None`` when the config file is not available.
    """
    try:
        local = Path(model_name) / _ST_CONFIG_FILE
        if local.is_file():
            path = str(local)
        else:
            from huggingface_hub import try_to_load_from_cache

            path = try_to_load_from_cache(
                model_name, _ST_CONFIG_FILE, cache_dir=os.getenv("SENTENCE_TRANSFORMERS_HOME")
            )
            if not isinstance(path, str):
                return None
        with open(path, encoding="utf-8") as f:
            prompts = json.load(f).get("prompts")
    except Exception as e:  # invalid repo id, unreadable or malformed file
        logger.debug("Could not read prompts of %s: %s", model_name, e)
        return None
    return prompts if isinstance(prompts, dict) else None


def _model_prompt(prompts: Any, kind: str) -> str:
    """The first non-empty prompt of *kind* in a model's prompts dict, or ``""``."""
    if not isinstance(prompts, dict):
        return ""
    for key in _PROMPT_ALIASES[kind]:
        value = prompts.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def resolve_prompt(kind: str, model: Any = None, model_name: Optional[str] = None) -> str:
    """Resolve the effective *kind* (``"document"`` or ``"query"``) prompt.

    Args:
        kind: ``"document"`` or ``"query"``.
        model: A loaded SentenceTransformer; its ``prompts`` are used when given.
            Without it, the model's prompts are read from its config file.
        model_name: Model id for the file lookup and the known-model table;
            defaults to ``EMBEDDING_MODEL``.
    """
    config = get_config()
    explicit = config.embedding_document_prompt if kind == DOCUMENT else config.embedding_query_prompt
    if explicit is not None:
        return explicit
    if model_name is None:
        model_name = config.embedding_model
    prompts = getattr(model, "prompts", None) if model is not None else read_model_prompts(model_name)
    from_model = _model_prompt(prompts, kind)
    if from_model:
        return from_model
    known = KNOWN_MODEL_PROMPTS.get(model_name) if isinstance(model_name, str) else None
    if known:
        return known[0] if kind == DOCUMENT else known[1]
    return ""


def resolve_document_prompt(model: Any = None, model_name: Optional[str] = None) -> str:
    """Effective document prompt; see :func:`resolve_prompt`."""
    return resolve_prompt(DOCUMENT, model, model_name)


def resolve_query_prompt(model: Any = None, model_name: Optional[str] = None) -> str:
    """Effective query prompt; see :func:`resolve_prompt`."""
    return resolve_prompt(QUERY, model, model_name)


def format_document(text: str, prompt: Optional[str] = None) -> str:
    """Prepend the document prompt to *text* (resolved for ``EMBEDDING_MODEL`` when not given)."""
    if prompt is None:
        prompt = resolve_document_prompt()
    return prompt + text


def format_query(
    query: str,
    template: Optional[str] = None,
    model: Any = None,
    model_name: Optional[str] = None,
) -> str:
    """Apply the query prompt to *query*.

    Without *template*, the prompt is resolved for *model* / *model_name*. A
    template containing ``{query}`` has it replaced by the query; any other
    value is used as a prefix.
    """
    if template is None:
        template = resolve_query_prompt(model, model_name)
    if QUERY_PLACEHOLDER in template:
        return template.replace(QUERY_PLACEHOLDER, query)
    return template + query


def warn_if_inconsistent(model: Any = None, model_name: Optional[str] = None) -> None:
    """Log a warning when the effective prompts look mismatched.

    A document prompt with no query prompt almost always means the corpus was
    encoded for an asymmetric model while queries are encoded bare, for example
    when only ``EMBEDDING_QUERY_PROMPT=""`` is set for a model with built-in prompts.
    """
    document_prompt = resolve_document_prompt(model, model_name)
    if document_prompt and not resolve_query_prompt(model, model_name):
        logger.warning(
            "The document prompt is %r but EMBEDDING_QUERY_PROMPT is empty; "
            "the server encodes queries with no prompt",
            document_prompt,
        )


__all__ = [
    "KNOWN_MODEL_PROMPTS",
    "QUERY_PLACEHOLDER",
    "format_document",
    "format_query",
    "read_model_prompts",
    "resolve_document_prompt",
    "resolve_prompt",
    "resolve_query_prompt",
    "warn_if_inconsistent",
]
