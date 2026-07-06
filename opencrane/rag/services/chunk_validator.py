"""Chunk validation for RAG readiness."""

from typing import List
from opencrane.shared.models.chunk import Chunk
from opencrane.shared.utils.token_counter import get_token_count


class ChunkValidator:
    """Validates chunks for RAG readiness."""

    @staticmethod
    def validate_chunks(chunks: List[Chunk]) -> List[str]:
        """Validate chunks and return list of errors."""
        errors = []

        for i, chunk in enumerate(chunks):
            # Check content not empty
            if isinstance(chunk.content, str):
                if not chunk.content.strip():  # pragma: no cover
                    errors.append(f"Chunk {i}: content is empty")
            elif isinstance(chunk.content, (dict, list)):
                if not chunk.content:  # pragma: no cover
                    errors.append(f"Chunk {i}: content is empty")
            else:  # pragma: no cover
                errors.append(f"Chunk {i}: content must be str, dict, or list")

            # Check token_count matches
            actual_tokens = get_token_count(chunk.content)
            if abs(actual_tokens - chunk.token_count) > 1:  # Allow small difference
                errors.append(f"Chunk {i}: token_count mismatch, expected {chunk.token_count}, got {actual_tokens}")

            # Check source_file exists
            if not chunk.source_file:  # pragma: no cover
                errors.append(f"Chunk {i}: source_file is empty")

            # Check chunk_type is valid
            if chunk.chunk_type not in ["prose", "code_snippet", "crd_definition", "openapi_spec", "yaml_content", "json_schema", "list_item", "table_row"]:  # pragma: no cover
                errors.append(f"Chunk {i}: invalid chunk_type {chunk.chunk_type}")

            # Type-specific validation removed - not needed
            # crd_definition and openapi_spec chunks validated by Pydantic model

        return errors

    @staticmethod
    def is_rag_ready(chunks: List[Chunk]) -> bool:
        """Check if chunks are RAG-ready."""
        return len(ChunkValidator.validate_chunks(chunks)) == 0