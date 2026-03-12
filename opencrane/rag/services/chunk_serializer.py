"""Chunk serialization for RAG-ready output."""

import json
from typing import List
from pathlib import Path
from opencrane.shared.models.chunk import Chunk


class ChunkSerializer:
    """Serializes chunks to JSON with deterministic ordering."""

    @staticmethod
    def serialize_chunks(chunks: List[Chunk], output_path: Path) -> None:
        """Serialize chunks to JSON file with deterministic ordering."""
        # Convert to dicts
        chunk_dicts = [chunk.model_dump() for chunk in chunks]

        # Sort for deterministic output
        # Use line_start if available, otherwise fall back to chunk_type and token_count
        chunk_dicts.sort(key=lambda x: (
            x['source_file'],
            x.get('line_start') if x.get('line_start') is not None else float('inf'),
            x['chunk_type']
        ))

        # Write with sorted keys for determinism
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(chunk_dicts, f, indent=2, sort_keys=True, ensure_ascii=False)

    @staticmethod
    def deserialize_chunks(input_path: Path) -> List[Chunk]:
        """Deserialize chunks from JSON file."""
        with open(input_path, 'r', encoding='utf-8') as f:
            chunk_dicts = json.load(f)

        return [Chunk(**chunk_dict) for chunk_dict in chunk_dicts]