"""Unit tests for EmbeddingService."""

import pytest
from unittest.mock import Mock, patch, mock_open
from opencrane.mcp.services.embeddings import EmbeddingService, EmbeddingsFile
from opencrane.shared.models.vector_chunk import EmbeddingRecord


class TestEmbeddingService:
    """Test cases for EmbeddingService."""

    @patch.dict('os.environ', {'AI_DOCS_EMBEDDINGS_BACKEND': 'mock'}, clear=False)
    @patch('opencrane.mcp.services.embeddings.SentenceTransformer')
    def test_init_mock_backend_skips_model_load(self, mock_transformer):
        """Mock backend should not attempt to load SentenceTransformer."""
        service = EmbeddingService("any-model-name")
        mock_transformer.assert_not_called()
        assert service.backend == 'mock'
        assert service.model is None

    @patch.dict('os.environ', {'AI_DOCS_EMBEDDINGS_BACKEND': 'mock'}, clear=False)
    @patch('opencrane.mcp.services.embeddings.SentenceTransformer')
    def test_generate_embeddings_mock_backend(self, mock_transformer):
        """Mock backend generates deterministic vectors without model."""
        service = EmbeddingService("any-model-name")
        mock_transformer.assert_not_called()

        chunks = [
            {"content": "hello", "source_file": "a.md", "chunk_type": "prose", "line_start": 1},
            {"content": "hello", "source_file": "b.md", "chunk_type": "prose", "line_start": 2},
        ]
        result = service.generate_embeddings(chunks)

        assert result.dimensions == 768
        assert len(result.embeddings) == 2
        assert len(result.embeddings[0].vector) == 768
        # Same text -> same mock vector
        assert result.embeddings[0].vector == result.embeddings[1].vector

    @patch('opencrane.mcp.services.embeddings.SentenceTransformer')
    def test_init_loads_model(self, mock_transformer):
        """Test that init loads the model correctly."""
        mock_model = Mock()
        mock_transformer.return_value = mock_model

        service = EmbeddingService("test-model")

        mock_transformer.assert_called_once_with("test-model", trust_remote_code=True, device='cpu')
        assert service.model == mock_model

    @patch('opencrane.mcp.services.embeddings.SentenceTransformer')
    def test_init_model_load_failure(self, mock_transformer):
        """Test handling of model loading failure."""
        mock_transformer.side_effect = Exception("Model load failed")

        with pytest.raises(Exception, match="Model load failed"):
            EmbeddingService("test-model")

    @patch('opencrane.mcp.services.embeddings.datetime')
    @patch('opencrane.mcp.services.embeddings.SentenceTransformer')
    def test_generate_embeddings(self, mock_transformer, mock_datetime):
        """Test generating embeddings for chunks."""
        mock_model = Mock()
        mock_model.encode.return_value = [[0.1] * 768, [0.2] * 768]
        mock_transformer.return_value = mock_model
        mock_datetime.now.return_value = Mock()
        mock_datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"

        service = EmbeddingService()
        chunks = [
            {
                "content": "test content 1",
                "source_file": "file1.md",
                "chunk_type": "prose",
                "line_start": 1
            },
            {
                "content": "test content 2",
                "source_file": "file2.md",
                "chunk_type": "code",
                "line_start": None
            }
        ]

        result = service.generate_embeddings(chunks)

        assert isinstance(result, EmbeddingsFile)
        assert result.model == service.model_name
        assert result.dimensions == 768
        assert len(result.embeddings) == 2
        assert result.embeddings[0].chunk_index == 0
        assert result.embeddings[1].chunk_index == 1
        assert result.embeddings[0].vector == [0.1] * 768

        mock_model.encode.assert_called_once_with(
            ["test content 1", "test content 2"],
            batch_size=8,
            show_progress_bar=True
        )

    @patch('opencrane.mcp.services.embeddings.SentenceTransformer')
    @patch('builtins.open', new_callable=mock_open)
    @patch('json.dump')
    def test_save_embeddings(self, mock_json_dump, mock_file, mock_transformer):
        """Test saving embeddings to file."""
        mock_transformer.return_value = Mock()

        service = EmbeddingService()
        embeddings_file = EmbeddingsFile(
            model="test-model",
            dimensions=768,
            created_at="2023-01-01T00:00:00Z",
            chunks_sha256="abc123",
            embeddings=[]
        )

        service.save_embeddings(embeddings_file, "test.json")

        mock_file.assert_called_once_with("test.json", 'w')
        mock_json_dump.assert_called_once()

    @patch('opencrane.mcp.services.embeddings.SentenceTransformer')
    @patch('builtins.open', new_callable=mock_open)
    @patch('json.load')
    def test_load_embeddings(self, mock_json_load, mock_file, mock_transformer):
        """Test loading embeddings from file."""
        mock_transformer.return_value = Mock()
        mock_json_load.return_value = {
            "model": "test-model",
            "dimensions": 768,
            "created_at": "2023-01-01T00:00:00Z",
            "chunks_sha256": "abc123",
            "embeddings": []
        }

        service = EmbeddingService()
        result = service.load_embeddings("test.json")

        assert isinstance(result, EmbeddingsFile)
        assert result.model == "test-model"
        mock_file.assert_called_once_with("test.json", 'r')
        mock_json_load.assert_called_once()

    @patch('opencrane.mcp.services.embeddings.SentenceTransformer')
    def test_generate_embeddings_encode_failure(self, mock_transformer):
        """Test handling of encoding failure."""
        mock_model = Mock()
        mock_model.encode.side_effect = Exception("Encoding failed")
        mock_transformer.return_value = mock_model

        service = EmbeddingService()
        chunks = [{"content": "test", "source_file": "f.md", "chunk_type": "prose"}]

        with pytest.raises(Exception, match="Encoding failed"):
            service.generate_embeddings(chunks)

    @patch('opencrane.mcp.services.embeddings.SentenceTransformer')
    def test_generate_embeddings_raises_if_model_missing(self, mock_transformer):
        """Non-mock backend should raise if model is unexpectedly None."""
        mock_transformer.return_value = Mock()
        service = EmbeddingService("test-model")
        service.backend = ""  # ensure non-mock path
        service.model = None

        chunks = [{"content": "x", "source_file": "f.md", "chunk_type": "prose", "line_start": 1}]
        with pytest.raises(RuntimeError, match="Embedding model is not loaded"):
            service.generate_embeddings(chunks)

    @patch('opencrane.mcp.services.embeddings.datetime')
    @patch('opencrane.mcp.services.embeddings.SentenceTransformer')
    def test_generate_embeddings_with_numpy_array(self, mock_transformer, mock_datetime):
        """Test generating embeddings when model returns numpy array."""
        import numpy as np
        mock_model = Mock()
        # Return numpy array with tolist() method
        mock_array = np.array([[0.1] * 768, [0.2] * 768])
        mock_model.encode.return_value = mock_array
        mock_transformer.return_value = mock_model
        mock_datetime.now.return_value = Mock()
        mock_datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"

        service = EmbeddingService()
        chunks = [
            {
                "content": "test content 1",
                "source_file": "file1.md",
                "chunk_type": "prose",
                "line_start": 1
            },
            {
                "content": "test content 2",
                "source_file": "file2.md",
                "chunk_type": "code_snippet",
                "line_start": 10
            }
        ]

        result = service.generate_embeddings(chunks)

        assert len(result.embeddings) == 2
        # Verify vectors were converted from numpy
        assert isinstance(result.embeddings[0].vector, list)