"""Task prompts for asymmetric embedding models.

Many retrieval models are trained with different prompts for documents and
queries (nomic-embed-text-v1.5: ``search_document: `` / ``search_query: ``;
Qwen3-Embedding: bare documents, ``Instruct: <task>\\nQuery: <query>`` queries).
Both prompts come from env-backed settings and default to empty, which encodes
text exactly as given.
"""

import logging
from typing import Optional

from opencrane.shared.config import get_config

logger = logging.getLogger(__name__)

QUERY_PLACEHOLDER = "{query}"


def format_document(text: str, prompt: Optional[str] = None) -> str:
    """Prepend the document prompt (``EMBEDDING_DOCUMENT_PROMPT``) to *text*."""
    if prompt is None:
        prompt = get_config().embedding_document_prompt
    return prompt + text


def format_query(query: str, template: Optional[str] = None) -> str:
    """Apply the query prompt (``EMBEDDING_QUERY_PROMPT``) to *query*.

    A template containing ``{query}`` has it replaced by the query; any other
    value is used as a prefix.
    """
    if template is None:
        template = get_config().embedding_query_prompt
    if QUERY_PLACEHOLDER in template:
        return template.replace(QUERY_PLACEHOLDER, query)
    return template + query


def warn_if_inconsistent() -> None:
    """Log a warning when the configured prompts look mismatched.

    A document prompt with no query prompt almost always means the corpus was
    encoded for an asymmetric model while queries are encoded bare.
    """
    config = get_config()
    if config.embedding_document_prompt and not config.embedding_query_prompt:
        logger.warning(
            "EMBEDDING_DOCUMENT_PROMPT is set but EMBEDDING_QUERY_PROMPT is empty; "
            "the server encodes queries with no prompt"
        )


__all__ = ["QUERY_PLACEHOLDER", "format_document", "format_query", "warn_if_inconsistent"]
