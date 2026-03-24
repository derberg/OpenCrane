"""Keyword-based search (BM25) over rag-chunks.json.

Provides lightweight keyword search to complement vector search in Milvus.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Iterable

try:
    from rank_bm25 import BM25Okapi
except Exception as exc:  # pragma: no cover - import guard
    BM25Okapi = None  # type: ignore

logger = logging.getLogger(__name__)


def _simple_tokenize(text: str) -> List[str]:
    # Lowercase and split on non-alphanumeric
    return [t for t in re.split(r"[^a-zA-Z0-9_]+", text.lower()) if t]


@dataclass
class KeywordDoc:
    chunk_id: str
    content: str
    source_file: str
    chunk_type: str
    metadata_json: str


class KeywordSearchService:
    """BM25-based keyword search over chunks.

    Index is built lazily from rag-chunks.json or injected data for tests.
    """

    def __init__(self, chunks: Optional[List[Dict]] = None, chunks_path: Optional[Path] = None):
        self._bm25: Optional[BM25Okapi] = None
        self._docs: List[KeywordDoc] = []
        self._tokenized_corpus: List[List[str]] = []
        self._chunks = chunks
        self._chunks_path = chunks_path or Path(os.environ.get("AI_DOCS_CHUNKS_FILE", ".opencrane/chunks.json"))

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
                chunk_type = ch.get("chunk_type", "")
                metadata = ch.get("metadata") or {}
                metadata_json = json.dumps(metadata, ensure_ascii=False)
                docs.append(KeywordDoc(chunk_id, content, source_file, chunk_type, metadata_json))
            except Exception:  # pragma: no cover - skip malformed
                continue

        tokenized = [_simple_tokenize(d.content) for d in docs]
        self._bm25 = BM25Okapi(tokenized)
        self._docs = docs
        self._tokenized_corpus = tokenized
        self._loaded = True

    def search(
        self,
        query: str,
        limit: int = 5,
        chunk_types: Optional[List[str]] = None,
        source_files: Optional[List[str]] = None,
        metadata_contains: Optional[List[str]] = None,
    ) -> List[Dict]:
        self._load()

        assert self._bm25 is not None  # for type checkers
        tokens = _simple_tokenize(query)
        scores = self._bm25.get_scores(tokens)

        # Rank indices by score
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

        def _passes_filters(doc: KeywordDoc) -> bool:
            if chunk_types and doc.chunk_type not in set(chunk_types):
                return False
            if source_files and doc.source_file not in set(source_files):
                return False
            if metadata_contains:
                meta = doc.metadata_json
                for term in metadata_contains:
                    if str(term) not in meta:
                        return False
            return True

        results: List[Dict] = []
        for i in ranked:
            doc = self._docs[i]
            if not _passes_filters(doc):
                continue
            results.append({
                "chunk_id": doc.chunk_id,
                "content": doc.content,
                "source_file": doc.source_file,
                "chunk_type": doc.chunk_type,
                "metadata_json": doc.metadata_json,
                # Use a unified key name for score compatibility with vector results
                "distance": float(scores[i]),
            })
            if len(results) >= limit:
                break

        return results
