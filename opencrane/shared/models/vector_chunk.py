"""Pydantic models for vectorized chunks and embeddings."""

from typing import List, Optional
from pydantic import BaseModel, Field
import hashlib

# Output size of the default embedding model (nomic-embed-text-v1.5). Only a
# fallback: indexes take their vector dimension from the embeddings file, so
# models of any size work.
DEFAULT_EMBEDDING_DIM = 768


class EmbeddingRecord(BaseModel):
    """Represents a single embedding record in rag-embeddings.json."""

    chunk_index: int = Field(..., description="Index into rag-chunks.json")
    chunk_id: str = Field(..., description="Deterministic ID for the chunk")
    vector: List[float] = Field(..., description="Embedding vector (length set by the embedding model)")


class EmbeddingsFile(BaseModel):
    """Represents the structure of rag-embeddings.json."""

    model: str = Field(..., description="Embedding model used")
    dimensions: int = Field(..., description="Vector dimensions")
    created_at: str = Field(..., description="ISO-8601 creation timestamp")
    chunks_sha256: str = Field(..., description="SHA-256 of rag-chunks.json used")
    document_prompt: str = Field("", description="Document prompt prepended to each chunk before encoding")
    embeddings: List[EmbeddingRecord] = Field(..., description="List of embedding records")


def _str_or_none(value):
    """Return ``value`` when it is a string, otherwise ``None``."""
    return value if isinstance(value, str) else None


class VectorChunk(BaseModel):
    """Represents a chunk with its vector for Milvus indexing."""

    chunk_id: str = Field(..., description="Deterministic chunk ID")
    embedding: List[float] = Field(..., description="Embedding vector")
    content: str = Field(..., description="Chunk content")
    source_file: str = Field(..., description="Source file path")
    source_name: Optional[str] = Field(None, description="Source identifier from config.yaml (e.g., 'MicrosoftDocs/microsoft-style-guide')")
    chunk_type: str = Field(..., description="Chunk type")
    metadata_json: Optional[str] = Field(None, description="JSON string of metadata")
    token_count: int = Field(..., description="Token count")
    line_start: Optional[int] = Field(None, description="Starting line number")
    list_id: Optional[str] = Field(None, description="list_id from metadata (list_item chunks)")
    table_id: Optional[str] = Field(None, description="table_id from metadata (table_row chunks)")
    clause_id: Optional[str] = Field(None, description="clause_id from metadata (prose chunks)")
    parent_chunk_id: Optional[str] = Field(None, description="parent_chunk_id from metadata (prose chunks)")

    @classmethod
    def from_chunk_and_embedding(cls, chunk, embedding_record):
        """Create VectorChunk from Chunk and EmbeddingRecord."""
        import json

        # Serialize dict/list content to JSON string for storage
        content_str = chunk.content
        if isinstance(chunk.content, (dict, list)):
            content_str = json.dumps(chunk.content)

        metadata = getattr(chunk, "metadata", None) or {}

        return cls(
            chunk_id=embedding_record.chunk_id,
            embedding=embedding_record.vector,
            content=content_str,
            source_file=chunk.source_file,
            source_name=getattr(chunk, "source_name", None),
            chunk_type=chunk.chunk_type,
            metadata_json=json.dumps(chunk.metadata) if chunk.metadata else None,
            token_count=chunk.token_count,
            line_start=chunk.line_start,
            # A custom chunk type may carry these keys with any value; only a
            # string fits the id columns, so other values stay in metadata_json.
            list_id=_str_or_none(metadata.get("list_id")),
            table_id=_str_or_none(metadata.get("table_id")),
            clause_id=_str_or_none(metadata.get("clause_id")),
            parent_chunk_id=_str_or_none(metadata.get("parent_chunk_id")),
        )


def generate_chunk_id(source_file: str, chunk_type: str, line_start: Optional[int], content: str) -> str:
    """Generate deterministic chunk ID."""
    key = f"{source_file}\n{chunk_type}\n{line_start or ''}\n{content}"
    return hashlib.sha256(key.encode()).hexdigest()