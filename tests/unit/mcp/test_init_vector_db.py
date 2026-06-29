"""Tests for init_vector_db entry point."""

import json
from unittest.mock import MagicMock, patch, mock_open
import pytest
from opencrane.mcp.init_vector_db import main


class TestInitVectorDb:
    """Test cases for init_vector_db entry point."""

    @patch('opencrane.mcp.init_vector_db.setup_logging')
    @patch('opencrane.mcp.init_vector_db.MilvusService')
    @patch('opencrane.mcp.init_vector_db.EmbeddingService')
    @patch('builtins.open', new_callable=mock_open, read_data='[{"content": "test", "chunk_type": "prose", "source_file": "test.md", "token_count": 10, "line_start": 1, "metadata": {}}]')
    @patch('opencrane.mcp.init_vector_db.Path')
    def test_main_success(self, mock_path, mock_file, mock_embedding_class, mock_milvus_class, mock_logging):
        """Test successful vector DB initialization."""
        mock_path.return_value.exists.return_value = True
        # Mock embedding service
        mock_embedding_service = MagicMock()
        mock_embedding_class.return_value = mock_embedding_service
        mock_embeddings = MagicMock()
        mock_embeddings.embeddings = [
            MagicMock(chunk_id="test_id", vector=[0.1] * 768)
        ]
        mock_embedding_service.load_embeddings.return_value = mock_embeddings
        
        # Mock Milvus service
        mock_milvus = MagicMock()
        mock_milvus_class.return_value = mock_milvus
        # Test case: collection doesn't exist yet
        mock_milvus.client.has_collection.return_value = False
        mock_milvus.get_collection_stats.return_value = {"row_count": 1}
        
        main()
        
        mock_logging.assert_called_once()
        mock_milvus.client.has_collection.assert_called_once()
        mock_milvus.create_collection.assert_called_once()
        mock_milvus.insert_chunks.assert_called_once()
        mock_milvus.client.flush.assert_called_once()
        mock_milvus.load_collection.assert_called_once()

    @patch('opencrane.mcp.init_vector_db.setup_logging')
    @patch('opencrane.mcp.init_vector_db.MilvusService')
    @patch('opencrane.mcp.init_vector_db.EmbeddingService')
    @patch('builtins.open', new_callable=mock_open, read_data='[{"content": "test"}]')
    @patch('opencrane.mcp.init_vector_db.Path')
    def test_main_collection_already_populated(self, mock_path, mock_file, mock_embedding_class, mock_milvus_class, mock_logging):
        """Test when collection already exists and is populated."""
        mock_path.return_value.exists.return_value = True
        # Mock embedding service
        mock_embedding_service = MagicMock()
        mock_embedding_class.return_value = mock_embedding_service
        
        # Mock Milvus service
        mock_milvus = MagicMock()
        mock_milvus_class.return_value = mock_milvus
        mock_milvus.client.has_collection.return_value = True
        mock_milvus.get_collection_stats.return_value = {"row_count": 65}
        
        main()
        
        # Should skip initialization
        mock_milvus.create_collection.assert_not_called()
        mock_milvus.insert_chunks.assert_not_called()

    @patch('opencrane.mcp.init_vector_db.setup_logging')
    @patch('opencrane.mcp.init_vector_db.MilvusService')
    @patch('opencrane.mcp.init_vector_db.EmbeddingService')
    @patch('builtins.open', new_callable=mock_open, read_data='[{"content": "test", "chunk_type": "prose", "source_file": "test.md", "token_count": 10, "line_start": 1, "metadata": {}}]')
    @patch('opencrane.mcp.init_vector_db.Path')
    def test_main_collection_exists_empty(self, mock_path, mock_file, mock_embedding_class, mock_milvus_class, mock_logging):
        """Test when collection exists but is empty."""
        mock_path.return_value.exists.return_value = True
        # Mock embedding service
        mock_embedding_service = MagicMock()
        mock_embedding_class.return_value = mock_embedding_service
        mock_embeddings = MagicMock()
        mock_embeddings.embeddings = [
            MagicMock(chunk_id="test_id", vector=[0.1] * 768)
        ]
        mock_embedding_service.load_embeddings.return_value = mock_embeddings
        
        # Mock Milvus service
        mock_milvus = MagicMock()
        mock_milvus_class.return_value = mock_milvus
        mock_milvus.client.has_collection.return_value = True
        mock_milvus.get_collection_stats.return_value = {"row_count": 0}
        
        main()
        
        # Should drop and recreate
        mock_milvus.client.drop_collection.assert_called_once()
        mock_milvus.create_collection.assert_called_once()

    @patch('opencrane.mcp.init_vector_db.setup_logging')
    @patch('opencrane.mcp.init_vector_db.Path')
    def test_main_missing_chunks_file(self, mock_path, mock_logging):
        """Test error when chunks file is missing."""
        mock_chunks = MagicMock()
        mock_chunks.exists.return_value = False
        mock_embeddings = MagicMock()
        mock_embeddings.exists.return_value = True
        
        def path_side_effect(arg):
            if 'chunks' in str(arg):
                return mock_chunks
            return mock_embeddings
        
        mock_path.side_effect = path_side_effect
        
        with pytest.raises(SystemExit) as exc_info:
            main()
        
        assert exc_info.value.code == 1

    @patch('opencrane.mcp.init_vector_db.setup_logging')
    @patch('opencrane.mcp.init_vector_db.Path')
    def test_main_missing_embeddings_file(self, mock_path, mock_logging):
        """Test error when embeddings file is missing."""
        mock_chunks = MagicMock()
        mock_chunks.exists.return_value = True
        mock_embeddings = MagicMock()
        mock_embeddings.exists.return_value = False
        
        def path_side_effect(arg):
            if 'chunks' in str(arg):
                return mock_chunks
            return mock_embeddings
        
        mock_path.side_effect = path_side_effect
        
        with pytest.raises(SystemExit) as exc_info:
            main()
        
        assert exc_info.value.code == 1

    @patch('opencrane.mcp.init_vector_db.setup_logging')
    @patch('opencrane.mcp.init_vector_db.MilvusService')
    @patch('opencrane.mcp.init_vector_db.EmbeddingService')
    @patch('builtins.open', new_callable=mock_open, read_data='[{"content": "test", "chunk_type": "prose", "source_file": "test.md", "token_count": 10, "line_start": 1, "metadata": {}}]')
    @patch('opencrane.mcp.init_vector_db.Path')
    def test_main_milvus_error(self, mock_path, mock_file, mock_embedding_class, mock_milvus_class, mock_logging):
        """Test error handling when Milvus fails."""
        mock_path.return_value.exists.return_value = True
        # Mock embedding service
        mock_embedding_service = MagicMock()
        mock_embedding_class.return_value = mock_embedding_service
        mock_embeddings = MagicMock()
        mock_embeddings.embeddings = [
            MagicMock(chunk_id="test_id", vector=[0.1] * 768)
        ]
        mock_embedding_service.load_embeddings.return_value = mock_embeddings
        
        # Mock Milvus service with error
        mock_milvus = MagicMock()
        mock_milvus_class.return_value = mock_milvus
        mock_milvus.client.has_collection.return_value = False
        mock_milvus.insert_chunks.side_effect = Exception("Milvus error")
        
        with pytest.raises(Exception, match="Milvus error"):
            main()
