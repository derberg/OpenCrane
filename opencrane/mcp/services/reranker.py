"""Optional reranking stage for ``search_docs``.

A reranker reorders the final candidates of a semantic, keyword, or hybrid
search. The server then cuts the list to ``limit``.

Protocol: a reranker is either an object with a ``rerank`` method or a plain
callable, both with the signature::

    (query: str, candidates: list[dict]) -> list[dict]

Each candidate is a search-result dict from the search backends. It carries
``chunk_id``, ``content`` (a string; YAML chunks are JSON strings), ``chunk_type``,
``source_file``, ``source_name``, ``metadata_json``, and ``distance`` (the
pre-rerank score, higher is better). The reranker returns the candidates to
keep, best first. It may rescore them by setting ``distance`` (shown
as ``Score`` in results) and may drop candidates.

Register a custom reranker on ``OpenCraneConfig.reranker``, or set the
``RERANKER_MODEL`` environment variable to use the built-in :class:`CrossEncoderReranker`.
"""

import logging
import threading
from typing import Any

import yaml

from opencrane.shared.config import get_config, remote_code_error, resolve_trust_remote_code

logger = logging.getLogger(__name__)


def candidate_text(candidate: dict) -> str:
    """Return the text of a search candidate as a string.

    Search backends always return ``content`` as a string. The dict/list branch
    is defensive: it dumps structured content as YAML if a caller passes it.
    """
    content = candidate.get("content", "")
    if isinstance(content, (dict, list)):
        return yaml.dump(content, default_flow_style=False, allow_unicode=True)
    return str(content)


class CrossEncoderReranker:
    """Reference reranker that scores (query, chunk) pairs with a sentence-transformers CrossEncoder.

    The model loads lazily on the first ``rerank`` call, like the embedding
    model, so configuring it does not slow down server startup.
    """

    def __init__(self, model_name: str, batch_size: int = 16):
        self.model_name = model_name
        self.batch_size = batch_size
        self.model: Any = None
        # Searches rerank in executor threads; without the lock, concurrent
        # first searches would each load their own copy of the model.
        self._load_lock = threading.Lock()
        # Concurrent searches share one model. Scoring one batch at a time
        # keeps a model whose code caches state between forward passes (as
        # nomic-bert does for its rotary tensors) from corrupting that state.
        self._predict_lock = threading.Lock()

    def _load_model(self):
        with self._load_lock:
            if self.model is None:
                from sentence_transformers import CrossEncoder

                trust_remote_code = resolve_trust_remote_code(
                    self.model_name, get_config().reranker_trust_remote_code
                )
                logger.info(f"Loading reranker model: {self.model_name} (trust_remote_code={trust_remote_code})")
                # CPU, matching the embedding service default (avoids MPS memory issues on macOS).
                try:
                    self.model = CrossEncoder(self.model_name, device="cpu", trust_remote_code=trust_remote_code)
                except Exception as e:
                    hinted = remote_code_error(e, trust_remote_code, "RERANKER_TRUST_REMOTE_CODE")
                    if hinted is None:
                        raise
                    raise hinted from e
                logger.info("Reranker model loaded successfully (using CPU)")
        return self.model

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        """Score every candidate against *query* and return them sorted by that score."""
        if not candidates:
            return []
        model = self._load_model()
        pairs = [(query, candidate_text(c)) for c in candidates]
        with self._predict_lock:
            scores = model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)
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
    list, must not break search. The function logs the error as a warning and
    returns the unreranked candidates in fused or backend order, cut to *limit*.
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
