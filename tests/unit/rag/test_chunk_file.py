"""Unit tests for chunker CLI."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from opencrane.rag.chunker import main


class TestChunkFileCLI:
    """Test the chunker CLI."""

    @patch('opencrane.rag.chunker.ChunkSerializer.serialize_chunks')
    @patch('opencrane.rag.chunker.FileProcessor')
    def test_main_success(self, mock_processor, mock_serialize, tmp_path):
        """Test main function with valid args."""
        from opencrane.shared.models.chunk import Chunk

        # Create the input file so the early-exit check passes
        input_dir = tmp_path / "input_dir"
        input_dir.mkdir()
        (input_dir / "llms-full.txt").write_text("# test")
        output_file = tmp_path / "output.json"

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

        main(llmstxt_dir=input_dir, chunks_file=output_file)

        # Assert processor called with the correct path
        mock_processor.assert_called_once()
        mock_proc_instance.process_file.assert_called_once_with(input_dir / 'llms-full.txt')

        # Assert serializer called
        mock_serialize.assert_called_once_with([test_chunk], output_file)

    @patch('opencrane.rag.chunker.FileProcessor')
    def test_main_processor_error(self, mock_processor, tmp_path):
        """Test main function with processor error."""
        # Create the input file so the early-exit check passes
        input_dir = tmp_path / "input_dir"
        input_dir.mkdir()
        (input_dir / "llms-full.txt").write_text("# test")
        output_file = tmp_path / "output.json"

        mock_proc_instance = MagicMock()
        mock_proc_instance.process_file.side_effect = Exception("Processing error")
        mock_processor.return_value = mock_proc_instance

        with pytest.raises(SystemExit):
            main(llmstxt_dir=input_dir, chunks_file=output_file)

    def test_main_skips_when_no_input_file(self, tmp_path, capsys):
        """Chunker should warn and return when llms-full.txt doesn't exist."""
        chunks_file = tmp_path / "chunks.json"
        main(llmstxt_dir=tmp_path, chunks_file=chunks_file)
        captured = capsys.readouterr()
        assert "skipping" in captured.err.lower()
        assert not chunks_file.exists()
