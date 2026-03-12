"""Tests for generate_embeddings entry point."""

import json
from unittest.mock import MagicMock, patch, mock_open
import pytest
from opencrane.rag.generate_embeddings import main


class TestGenerateEmbeddings:
    """Test cases for generate_embeddings entry point."""

    @patch('opencrane.rag.generate_embeddings.setup_logging')
    @patch('opencrane.rag.generate_embeddings.EmbeddingService')
    @patch('builtins.open', new_callable=mock_open, read_data='[{"content": "test"}]')
    @patch('os.path.exists', return_value=True)
    def test_main_success(self, mock_exists, mock_file, mock_service_class, mock_logging):
        """Test successful embedding generation."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        # Mock embeddings result
        mock_embeddings = MagicMock()
        mock_embeddings.model_dump.return_value = {"embeddings": [{"vector": [0.1]}]}
        mock_service.generate_embeddings.return_value = mock_embeddings
        
        main()
        
        mock_logging.assert_called_once()
        mock_service.generate_embeddings.assert_called_once()
        mock_service.save_embeddings.assert_called_once()

    @patch('opencrane.rag.generate_embeddings.setup_logging')
    @patch('opencrane.rag.generate_embeddings.Path')
    def test_main_missing_chunks_file(self, mock_path, mock_logging):
        """Test error when chunks file is missing."""
        mock_chunks = MagicMock()
        mock_chunks.exists.return_value = False
        mock_path.return_value = mock_chunks
        
        with pytest.raises(SystemExit) as exc_info:
            main()
        
        assert exc_info.value.code == 1

    @patch('opencrane.rag.generate_embeddings.setup_logging')
    @patch('opencrane.rag.generate_embeddings.EmbeddingService')
    @patch('builtins.open', new_callable=mock_open, read_data='[{"content": "test"}]')
    @patch('os.path.exists', return_value=True)
    def test_main_service_error(self, mock_exists, mock_file, mock_service_class, mock_logging):
        """Test error handling when service fails."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.generate_embeddings.side_effect = Exception("Service error")
        
        with pytest.raises(Exception, match="Service error"):
            main()
