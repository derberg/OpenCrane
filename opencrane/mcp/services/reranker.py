"""Optional reranking stage for ``search_docs``.

A reranker reorders the final candidate list of a search (after semantic,
keyword or hybrid fusion) before it is cut to ``limit``.

Protocol: a reranker is either an object with a ``rerank`` method or a plain
callable, both with the signature::

    (query: str, candidates: list[dict]) -> list[dict]

Each candidate is a search-result dict as produced by the backends: it carries
``chunk_id``, ``content`` (str, or dict/list for YAML chunks), ``chunk_type``,
``source_file``, ``source_name``, ``metadata_json`` and ``distance`` (the
pre-rerank score, higher is better). The reranker returns the candidates it
wants to keep, best first. It may rescore them by setting ``distance`` (shown
as ``Score`` in results) and may drop candidates; the server cuts the returned
list to ``limit``.

Register a custom reranker on ``OpenCraneConfig.reranker``, or set the
``RERANKER_MODEL`` env var to use the built-in :class:`CrossEncoderReranker`.
"""

import logging
import threading
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def candidate_text(candidate: dict) -> str:
    """Return the text of a search candidate as a string (YAML-dumps dict/list content)."""
    content = candidate.get("content", "")
    if isinstance(content, (dict, list)):
        return yaml.dump(content, default_flow_style=False, allow_unicode=True)
    return str(content)


class CrossEncoderReranker:
    """Reference reranker scoring (query, chunk) pairs with a sentence-transformers CrossEncoder.

    The model is loaded lazily on the first ``rerank`` call, like the embedding
    model, so configuring it does not slow down server startup.
    """

    def __init__(self, model_name: str, batch_size: int = 16):
        self.model_name = model_name
        self.batch_size = batch_size
        self.model: Any = None
        # Searches rerank in executor threads; without the lock, concurrent
        # first searches would each load their own copy of the model.
        self._load_lock = threading.Lock()

    def _load_model(self):
        with self._load_lock:
            if self.model is None:
                from sentence_transformers import CrossEncoder

                logger.info(f"Loading reranker model: {self.model_name}")
                # CPU, matching the embedding service (avoids MPS memory issues on macOS).
                self.model = CrossEncoder(self.model_name, device="cpu", trust_remote_code=True)
                logger.info("Reranker model loaded successfully (using CPU)")
        return self.model

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        """Score every candidate against *query* and return them sorted by that score."""
        if not candidates:
            return []
        model = self._load_model()
        scores = model.predict(
            [(query, candidate_text(c)) for c in candidates],
            batch_size=self.batch_size,
            show_progress_bar=False,
        )
        rescored = []
        for candidate, score in zip(candidates, scores):
            out = dict(candidate)
            out["distance"] = float(score)
            rescored.append(out)
        rescored.sort(key=lambda r: r["distance"], reverse=True)
        return rescored


def apply_reranker(reranker, query: str, candidates: list[dict], limit: int) -> list[dict]:
    """Run *reranker* over *candidates* and cut the result to *limit*.

    Failure policy: a reranker that raises, or returns something other than a
    list, must not take search down. The error is logged as a warning and the
    unreranked candidates (already in fused/backend order) are returned, cut to
    *limit*. That is exactly what search returns without a reranker.
    """
    try:
        rerank = getattr(reranker, "rerank", reranker)
        reranked = rerank(query, list(candidates))
        if not isinstance(reranked, list):
            raise TypeError(f"reranker returned {type(reranked).__name__}, expected list")
    except Exception as exc:
        logger.warning(f"Reranker failed, returning unreranked results: {exc}")
        return candidates[:limit]
    return reranked[:limit]


__all__ = ["CrossEncoderReranker", "apply_reranker", "candidate_text"]
