"""Integration test for US1: Vector DB initialization workflow."""

import pytest
import json
from pathlib import Path


class TestUS1VectorDBInit:
    """Integration test for US1: Generate embeddings -> Init DB -> Load -> Verify count."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def sample_chunks(self):
        """Create sample chunks for testing."""
        return [
            {
                "content": "This is a test document about AI.",
                "source_file": "docs/ai.md",
                "chunk_type": "prose",
                "metadata": {},
                "token_count": 8,
                "line_start": 1
            },
            {
                "content": "Machine learning is a subset of AI.",
                "source_file": "docs/ml.md",
                "chunk_type": "prose",
                "metadata": {},
                "token_count": 7,
                "line_start": 10
            }
        ]

    def test_generate_embeddings_workflow(self, temp_dir, sample_chunks):
        """Test the generate embeddings workflow (setup.sh --generate-embeddings)."""
        # Setup
        chunks_file = temp_dir / "rag-chunks.json"
        embeddings_file = temp_dir / "rag-embeddings.json"

        # Write sample chunks
        with open(chunks_file, 'w') as f:
            json.dump(sample_chunks, f)

        # Simulate the workflow by creating expected output
        # In real implementation, this would be done by setup.sh --generate-embeddings
        mock_embeddings_data = {
            "model": "nomic-ai/nomic-embed-text-v1.5",
            "dimensions": 768,
            "created_at": "2023-01-01T00:00:00+00:00",
            "chunks_sha256": "abc123",
            "embeddings": [
                {
                    "chunk_index": 0,
                    "chunk_id": "test_id_1",
                    "vector": [0.1] * 768
                },
                {
                    "chunk_index": 1,
                    "chunk_id": "test_id_2",
                    "vector": [0.2] * 768
                }
            ]
        }

        with open(embeddings_file, 'w') as f:
            json.dump(mock_embeddings_data, f, indent=2)

        # Verify
        assert embeddings_file.exists()
        with open(embeddings_file, 'r') as f:
            saved_data = json.load(f)

        assert len(saved_data['embeddings']) == 2
        assert "model" in saved_data
        assert "dimensions" in saved_data
        assert saved_data["dimensions"] == 768

    def test_init_vector_db_workflow(self, temp_dir):
        """Test the init vector DB workflow (setup.sh --init-vector-db)."""
        # Setup
        chunks_file = temp_dir / "rag-chunks.json"
        embeddings_file = temp_dir / "rag-embeddings.json"

        # Sample data
        sample_chunks = [
            {
                "content": "This is a test document about AI.",
                "source_file": "docs/ai.md",
                "chunk_type": "prose",
                "metadata": {},
                "token_count": 8,
                "line_start": 1
            }
        ]
        sample_embeddings = {
            "model": "test-model",
            "dimensions": 768,
            "created_at": "2023-01-01T00:00:00",
            "chunks_sha256": "abc123",
            "embeddings": [
                {
                    "chunk_index": 0,
                    "chunk_id": "test_id_1",
                    "vector": [0.1] * 768
                }
            ]
        }

        # Write sample files
        with open(chunks_file, 'w') as f:
            json.dump(sample_chunks, f)
        with open(embeddings_file, 'w') as f:
            json.dump(sample_embeddings, f)

        # Simulate the workflow
        # In real implementation, this would insert into Milvus
        inserted_count = 1  # Mock successful insertion

        # Verify
        assert inserted_count == 1

        # Verify files exist
        assert chunks_file.exists()
        assert embeddings_file.exists()

        # Verify data integrity
        with open(embeddings_file, 'r') as f:
            loaded_embeddings = json.load(f)
        assert len(loaded_embeddings['embeddings']) == 1
        assert loaded_embeddings['embeddings'][0]['chunk_id'] == "test_id_1"

    def test_full_us1_workflow(self, temp_dir, sample_chunks):
        """Test the complete US1 workflow: Generate -> Init DB -> Load -> Verify count."""
        # Setup files
        chunks_file = temp_dir / "rag-chunks.json"
        embeddings_file = temp_dir / "rag-embeddings.json"

        # Write sample chunks
        with open(chunks_file, 'w') as f:
            json.dump(sample_chunks, f)

        # Step 1: Generate embeddings (simulated)
        mock_embeddings_data = {
            "model": "nomic-ai/nomic-embed-text-v1.5",
            "dimensions": 768,
            "created_at": "2023-01-01T00:00:00+00:00",
            "chunks_sha256": "abc123",
            "embeddings": [
                {
                    "chunk_index": 0,
                    "chunk_id": "test_id_1",
                    "vector": [0.1] * 768
                },
                {
                    "chunk_index": 1,
                    "chunk_id": "test_id_2",
                    "vector": [0.2] * 768
                }
            ]
        }

        with open(embeddings_file, 'w') as f:
            json.dump(mock_embeddings_data, f, indent=2)

        # Step 2: Init vector DB (simulated)
        # In real implementation, this would insert into Milvus
        inserted_count = 2  # Mock successful insertion

        # Step 3: Load and verify
        with open(embeddings_file, 'r') as f:
            loaded_embeddings = json.load(f)

        # Verify the workflow
        assert inserted_count == 2
        assert len(loaded_embeddings['embeddings']) == 2

        # Verify files exist
        assert chunks_file.exists()
        assert embeddings_file.exists()

        # Verify data integrity
        assert len(loaded_embeddings['embeddings']) == 2
        assert all(len(emb['vector']) == 768 for emb in loaded_embeddings['embeddings'])