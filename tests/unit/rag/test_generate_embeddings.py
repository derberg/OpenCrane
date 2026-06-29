"""Tests for generate_embeddings entry point."""

import json
from unittest.mock import MagicMock, patch, mock_open
import pytest
from opencrane.rag.generate_embeddings import (
    main,
    _chunks_sha256,
    _embeddings_up_to_date,
)


class TestGenerateEmbeddings:
    """Test cases for generate_embeddings entry point."""

    @patch('opencrane.rag.generate_embeddings.setup_logging')
    @patch('opencrane.rag.generate_embeddings.EmbeddingService')
    @patch('builtins.open', new_callable=mock_open, read_data='[{"content": "test"}]')
    @patch('opencrane.rag.generate_embeddings._embeddings_up_to_date', return_value=False)
    @patch('opencrane.rag.generate_embeddings.Path')
    def test_main_success(self, mock_path, mock_up_to_date, mock_file, mock_service_class, mock_logging):
        """Test successful embedding generation."""
        mock_path.return_value.exists.return_value = True

        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # Mock embeddings result
        mock_embeddings = MagicMock()
        mock_embeddings.embeddings = [{"vector": [0.1]}]
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
    @patch('opencrane.rag.generate_embeddings._embeddings_up_to_date', return_value=False)
    @patch('opencrane.rag.generate_embeddings.Path')
    def test_main_service_error(self, mock_path, mock_up_to_date, mock_file, mock_service_class, mock_logging):
        """Test error handling when service fails."""
        mock_path.return_value.exists.return_value = True

        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.generate_embeddings.side_effect = Exception("Service error")

        with pytest.raises(Exception, match="Service error"):
            main()

    def test_chunks_sha256(self, tmp_path):
        """_chunks_sha256 hashes the file content reproducibly."""
        import hashlib

        chunks_file = tmp_path / "chunks.json"
        content = b'[{"content": "hello"}]'
        chunks_file.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        assert _chunks_sha256(chunks_file) == expected

    def test_embeddings_up_to_date_missing_file(self, tmp_path):
        """Returns False when the embeddings file does not exist."""
        chunks_file = tmp_path / "chunks.json"
        chunks_file.write_bytes(b"[]")
        embeddings_file = tmp_path / "embeddings.json"

        assert _embeddings_up_to_date(chunks_file, embeddings_file) is False

    def test_embeddings_up_to_date_matching_hash(self, tmp_path):
        """Returns True when stored chunks_sha256 matches the current chunks file."""
        chunks_file = tmp_path / "chunks.json"
        chunks_file.write_bytes(b'[{"content": "x"}]')
        embeddings_file = tmp_path / "embeddings.json"
        embeddings_file.write_text(
            json.dumps({"chunks_sha256": _chunks_sha256(chunks_file)})
        )

        assert _embeddings_up_to_date(chunks_file, embeddings_file) is True

    def test_embeddings_up_to_date_mismatched_hash(self, tmp_path):
        """Returns False when the stored hash differs from the current chunks file."""
        chunks_file = tmp_path / "chunks.json"
        chunks_file.write_bytes(b'[{"content": "x"}]')
        embeddings_file = tmp_path / "embeddings.json"
        embeddings_file.write_text(json.dumps({"chunks_sha256": "deadbeef"}))

        assert _embeddings_up_to_date(chunks_file, embeddings_file) is False

    def test_embeddings_up_to_date_invalid_json(self, tmp_path):
        """Returns False when the embeddings file is not valid JSON (exception path)."""
        chunks_file = tmp_path / "chunks.json"
        chunks_file.write_bytes(b'[{"content": "x"}]')
        embeddings_file = tmp_path / "embeddings.json"
        embeddings_file.write_text("not-json{{{")

        assert _embeddings_up_to_date(chunks_file, embeddings_file) is False

    @patch('opencrane.rag.generate_embeddings.setup_logging')
    @patch('opencrane.rag.generate_embeddings.EmbeddingService')
    @patch('opencrane.rag.generate_embeddings._embeddings_up_to_date', return_value=True)
    @patch('opencrane.rag.generate_embeddings.Path')
    def test_main_skips_when_up_to_date(
        self, mock_path, mock_up_to_date, mock_service_class, mock_logging
    ):
        """main returns early (no embedding generation) when embeddings are up to date."""
        mock_path.return_value.exists.return_value = True

        main()

        mock_up_to_date.assert_called_once()
        mock_service_class.assert_not_called()

    @patch('opencrane.rag.generate_embeddings.setup_logging')
    @patch('opencrane.rag.generate_embeddings.EmbeddingService')
    @patch('builtins.open', new_callable=mock_open, read_data='[{"content": "test"}]')
    @patch('opencrane.rag.generate_embeddings._embeddings_up_to_date', return_value=True)
    @patch('opencrane.rag.generate_embeddings.Path')
    def test_main_force_bypasses_up_to_date(
        self, mock_path, mock_up_to_date, mock_file, mock_service_class, mock_logging
    ):
        """force=True regenerates even when embeddings are up to date."""
        mock_path.return_value.exists.return_value = True

        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_embeddings = MagicMock()
        mock_embeddings.embeddings = [{"vector": [0.1]}]
        mock_service.generate_embeddings.return_value = mock_embeddings

        main(force=True)

        mock_up_to_date.assert_not_called()
        mock_service.generate_embeddings.assert_called_once()
        mock_service.save_embeddings.assert_called_once()
