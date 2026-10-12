"""Keyword-based search (BM25) over rag-chunks.json.

Provides lightweight keyword search to complement vector search in Milvus.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Dict, Optional, Iterable, Tuple

from opencrane.shared.config import get_config

try:
    from rank_bm25 import BM25Okapi
except Exception as exc:  # pragma: no cover - import guard
    BM25Okapi = None  # type: ignore

logger = logging.getLogger(__name__)


def _simple_tokenize(text: str) -> List[str]:
    # Lowercase and split on non-alphanumeric
    return [t for t in re.split(r"[^a-zA-Z0-9_]+", text.lower()) if t]


# A run of ASCII alphanumerics, optionally joined by single ".", "-" or "_"
# characters that sit between alphanumerics. Joiners at the edges ("5.4.1." at
# the end of a sentence, "GTP-" before a line break) are not part of the match.
_IDENTIFIER_RE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
_JOINER_RE = re.compile(r"[._-]")


def _identifier_tokenize(text: str) -> List[str]:
    """Tokenize while keeping technical identifiers intact.

    Each compound such as ``5.4.1``, ``29.244``, ``v1.2.3``, ``gtp-u``,
    ``sx-based`` or ``get_yaml_definition`` is emitted as one token, followed
    by its distinct parts (``gtp-u`` -> ``gtp-u``, ``gtp``, ``u``), so a query
    for ``gtp`` still matches ``GTP-U`` while a query for ``GTP-U`` ranks exact
    occurrences above documents that only mention ``GTP``. Parts are
    de-duplicated per compound, so one occurrence adds at most 1 to each term
    frequency. Plain words produce the same token as the simple tokenizer.
    """
    tokens: List[str] = []
    for match in _IDENTIFIER_RE.findall(text.lower()):
        tokens.append(match)
        if _JOINER_RE.search(match):
            tokens.extend(dict.fromkeys(_JOINER_RE.split(match)))
    return tokens


_TOKENIZERS = {
    "simple": _simple_tokenize,
    "identifier": _identifier_tokenize,
}


def _resolve_tokenizer(name: Optional[str] = None) -> Callable[[str], List[str]]:
    """Return the BM25 tokenizer selected by ``name`` or ``BM25_TOKENIZER``."""
    if name is None:
        name = get_config().bm25_tokenizer
    key = name.strip().lower()
    if key not in _TOKENIZERS:
        raise ValueError(f"Unknown BM25_TOKENIZER {name!r}; expected one of: {', '.join(_TOKENIZERS)}")
    return _TOKENIZERS[key]


@dataclass
class KeywordDoc:
    chunk_id: str
    content: str
    source_file: str
    source_name: str
    chunk_type: str
    metadata_json: str
    token_count: int = 0


class KeywordSearchService:
    """BM25-based keyword search over chunks.

    Index is built lazily on first search, from rag-chunks.json or injected data
    for tests, and then reused. A file-backed index is rebuilt only when the
    chunks file changes (mtime or size); an injected ``chunks`` list is built once.
    """

    def __init__(self, chunks: Optional[List[Dict]] = None, chunks_path: Optional[Path] = None):
        self._bm25: Optional[BM25Okapi] = None
        self._docs: List[KeywordDoc] = []
        self._tokenized_corpus: List[List[str]] = []
        self._chunks = chunks
        self._chunks_path = chunks_path or Path(os.environ.get("AI_DOCS_CHUNKS_FILE", ".opencrane/chunks.json"))
        # Resolved once so documents and queries always share the same tokenizer
        self._tokenize = _resolve_tokenizer()
        # Signature of the source the current index was built from; None = not built.
        self._source_signature: Optional[Tuple] = None
        # Serialises build/rebuild: hybrid search runs the keyword arm in an
        # executor thread, so concurrent first queries must not build twice or
        # observe a half-swapped index.
        self._lock = threading.Lock()

    @property
    def index_resident(self) -> bool:
        """True once the BM25 index has been built and is held in memory."""
        return self._bm25 is not None

    def _current_signature(self) -> Tuple:
        if self._chunks is not None:
            return ("injected",)
        st = self._chunks_path.stat()
        return (str(self._chunks_path), st.st_mtime_ns, st.st_size)

    def _ensure_index(self) -> Tuple[BM25Okapi, List[KeywordDoc]]:
        """Build the index if missing or stale; return a consistent (bm25, docs) pair."""
        with self._lock:
            signature = self._current_signature()
            if self._bm25 is None or signature != self._source_signature:
                self._load()
                self._source_signature = signature
            return self._bm25, self._docs

    def _load(self) -> None:
        raw = self._chunks if self._chunks is not None else json.loads(self._chunks_path.read_text(encoding="utf-8"))

        docs: List[KeywordDoc] = []
        for idx, ch in enumerate(raw):
            try:
                # chunk_id may not exist in rag-chunks.json; fallback to synthetic id
                chunk_id = ch.get("chunk_id") or f"doc_{idx}"
                content = ch.get("content", "")
                # Convert non-string content to string for tokenization
                if isinstance(content, (dict, list)):
                    content = json.dumps(content, ensure_ascii=False)
                elif not isinstance(content, str):
                    content = str(content)
                source_file = ch.get("source_file", "")
                source_name = ch.get("source_name") or ""
                chunk_type = ch.get("chunk_type", "")
                metadata = ch.get("metadata") or {}
                metadata_json = json.dumps(metadata, ensure_ascii=False)
                token_count = ch.get("token_count") or 0
                docs.append(KeywordDoc(chunk_id, content, source_file, source_name, chunk_type, metadata_json, token_count))
            except Exception:  # pragma: no cover - skip malformed
                continue

        tokenized = [self._tokenize(d.content) for d in docs]
        self._bm25 = BM25Okapi(tokenized)
        self._docs = docs
        self._tokenized_corpus = tokenized

    def search(
        self,
        query: str,
        limit: int = 5,
        chunk_types: Optional[List[str]] = None,
        source_files: Optional[List[str]] = None,
        source_names: Optional[List[str]] = None,
        metadata_contains: Optional[List[str]] = None,
    ) -> List[Dict]:
        bm25, docs = self._ensure_index()

        tokens = self._tokenize(query)
        scores = bm25.get_scores(tokens)

        # Rank indices by score
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

        def _passes_filters(doc: KeywordDoc) -> bool:
            if chunk_types and doc.chunk_type not in set(chunk_types):
                return False
            if source_files and doc.source_file not in set(source_files):
                return False
            if source_names and doc.source_name not in set(source_names):
                return False
            if metadata_contains:
                meta = doc.metadata_json
                for term in metadata_contains:
                    if str(term) not in meta:
                        return False
            return True

        results: List[Dict] = []
        for i in ranked:
            doc = docs[i]
            if not _passes_filters(doc):
                continue
            results.append({
                "chunk_id": doc.chunk_id,
                "content": doc.content,
                "source_file": doc.source_file,
                "source_name": doc.source_name,
                "chunk_type": doc.chunk_type,
                "metadata_json": doc.metadata_json,
                "token_count": doc.token_count,
                # Use a unified key name for score compatibility with vector results
                "distance": float(scores[i]),
            })
            if len(results) >= limit:
                break

        return results
