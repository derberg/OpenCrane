"""Embedding service for generating vector embeddings from chunks."""

import logging
import os
import random
import yaml
from typing import List, Dict, Any, Union
from sentence_transformers import SentenceTransformer
from opencrane.shared.config import get_config
from opencrane.shared.models.vector_chunk import EmbeddingRecord, EmbeddingsFile, generate_chunk_id
import json
import hashlib
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating and managing embeddings."""

    def __init__(self, model_name: str = None):
        self.config = get_config()
        self.model_name = model_name or self.config.embedding_model
        self.backend = (os.environ.get("AI_DOCS_EMBEDDINGS_BACKEND") or "").strip().lower()
        self.model = None
        self._load_model()

    def _mock_vector(self, text: Union[str, Dict, List], dimensions: int) -> List[float]:
        """Generate a mock embedding vector from text, dict, or list."""
        # Convert dict/list to string for hashing
        if isinstance(text, (dict, list)):
            text = yaml.dump(text, default_flow_style=False, allow_unicode=True)
        
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest(), "big")
        rng = random.Random(seed)
        return [rng.random() for _ in range(dimensions)]

    def _load_model(self):
        """Load the embedding model."""
        logger.info(f"Loading embedding model: {self.model_name}")

        if self.backend == "mock" or self.model_name == "mock":
            self.model = None
            logger.info("Using mock embeddings backend (no model load)")
            return

        try:
            # Use CPU to avoid MPS memory issues on macOS
            self.model = SentenceTransformer(self.model_name, trust_remote_code=True, device='cpu')
            logger.info("Embedding model loaded successfully (using CPU)")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise

    def generate_embeddings(self, chunks: List[Dict[str, Any]]) -> EmbeddingsFile:
        """Generate embeddings for a list of chunks.

        Args:
            chunks: List of chunk dictionaries from rag-chunks.json

        Returns:
            EmbeddingsFile with all embeddings
        """
        logger.info(f"Generating embeddings for {len(chunks)} chunks")

        # Compute SHA-256 of chunks for integrity
        chunks_json = json.dumps(chunks, sort_keys=True)
        chunks_sha256 = hashlib.sha256(chunks_json.encode()).hexdigest()

        embeddings = []
        # Convert chunk content to strings (handle dict/list content from tree walkers)
        texts = []
        for chunk in chunks:
            content = chunk['content']
            if isinstance(content, (dict, list)):
                texts.append(yaml.dump(content, default_flow_style=False, allow_unicode=True))
            else:
                texts.append(content)

        try:
            if self.backend == "mock" or self.model_name == "mock":
                dimensions = 768
                vectors = [self._mock_vector(text, dimensions) for text in texts]
                logger.info(f"Generated {len(vectors)} mock vectors")
            else:
                if self.model is None:
                    raise RuntimeError("Embedding model is not loaded")

                # Encode in smaller batches to avoid memory issues
                batch_size = 8
                vectors = self.model.encode(texts, batch_size=batch_size, show_progress_bar=True)
                # Convert to list if needed (some models return numpy arrays)
                if hasattr(vectors, 'tolist'):
                    vectors = vectors.tolist()
                logger.info(f"Encoded {len(vectors)} vectors")
        except Exception as e:
            logger.error(f"Failed to encode texts: {e}")
            raise

        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            # Use the chunk_id from the chunk data instead of regenerating it
            # This preserves unique IDs generated during chunking (with collision handling)
            chunk_id = chunk.get('chunk_id')
            if not chunk_id:
                # Fallback to generation only if chunk_id is missing (shouldn't happen with current pipeline)
                logger.warning(f"Chunk at index {i} missing chunk_id, regenerating")
                chunk_id = generate_chunk_id(
                    chunk['source_file'],
                    chunk['chunk_type'],
                    chunk.get('line_start'),
                    chunk['content']
                )
            record = EmbeddingRecord(
                chunk_index=i,
                chunk_id=chunk_id,
                vector=vector
            )
            embeddings.append(record)

        embeddings_file = EmbeddingsFile(
            model=self.model_name,
            dimensions=len(vectors[0]) if vectors else 0,
            created_at=datetime.now(timezone.utc).isoformat(),
            chunks_sha256=chunks_sha256,
            embeddings=embeddings
        )

        logger.info(f"Generated embeddings file with {len(embeddings)} records")
        return embeddings_file

    def save_embeddings(self, embeddings_file: EmbeddingsFile, output_path: str):
        """Save embeddings to JSON file."""
        logger.info(f"Saving embeddings to {output_path}")
        with open(output_path, 'w') as f:
            json.dump(embeddings_file.model_dump(), f, indent=2)
        logger.info("Embeddings saved successfully")

    def load_embeddings(self, input_path: str) -> EmbeddingsFile:
        """Load embeddings from JSON file."""
        logger.info(f"Loading embeddings from {input_path}")
        with open(input_path, 'r') as f:
            data = json.load(f)
        embeddings_file = EmbeddingsFile(**data)
        logger.info(f"Loaded embeddings with {len(embeddings_file.embeddings)} records")
        return embeddings_file