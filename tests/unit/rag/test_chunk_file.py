"""Unit tests for chunker CLI."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from opencrane.rag.chunker import main


class TestChunkFileCLI:
    """Test the chunker CLI."""

    @patch('opencrane.rag.chunker.ChunkSerializer.serialize_chunks')
    @patch('opencrane.rag.chunker.FileProcessor')
    def test_main_success(self, mock_processor, mock_serialize):
        """Test main function with valid args."""
        from opencrane.shared.models.chunk import Chunk

        # Mock the processor to return real Chunk objects
        mock_proc_instance = MagicMock()
        test_chunk = Chunk(
            content="test content",
            source_file="test.md",
            chunk_type="prose",
            metadata={
                "source_url": "https://github.com/org/repo/blob/main/file.md"
            },
            token_count=10
        )
        mock_proc_instance.process_file.return_value = [test_chunk]
        mock_processor.return_value = mock_proc_instance

        # Call main with env vars (main() reads paths from env, not sys.argv)
        with patch.dict('os.environ', {
            'AI_DOCS_LLMSTXT_DIR': 'input_dir',
            'AI_DOCS_CHUNKS_FILE': 'output.json',
        }):
            main()

        # Assert processor called with env-var derived path
        mock_processor.assert_called_once()
        mock_proc_instance.process_file.assert_called_once_with(Path('input_dir') / 'llms-full.txt')

        # Assert serializer called
        mock_serialize.assert_called_once_with([test_chunk], Path('output.json'))

    @patch('opencrane.rag.chunker.FileProcessor')
    def test_main_processor_error(self, mock_processor):
        """Test main function with processor error."""
        mock_proc_instance = MagicMock()
        mock_proc_instance.process_file.side_effect = Exception("Processing error")
        mock_processor.return_value = mock_proc_instance

        with patch.dict('os.environ', {
            'AI_DOCS_LLMSTXT_DIR': 'input_dir',
            'AI_DOCS_CHUNKS_FILE': 'output.json',
        }):
            with pytest.raises(SystemExit):
                main()
