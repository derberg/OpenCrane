import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch
from opencrane.rag.token_count import main
from opencrane.shared.config import Config


class TestTokenCountEndToEnd:
    """Integration tests for end-to-end token count generation."""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary source and output directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir)
            source_dir = base_path / "source"
            output_dir = base_path / "output"
            source_dir.mkdir()
            output_dir.mkdir()
            yield source_dir, output_dir

    def test_token_count_with_sample_files(self, temp_dirs, capsys):
        """Test end-to-end token counting with sample files."""
        source_dir, output_dir = temp_dirs
        output_file = output_dir / "README.md"

        # Create source directories with llms-full.txt files matching actual structure
        # source1/ with projects
        source1_dir = source_dir / "source1"
        source1_dir.mkdir()
        (source1_dir / "project1").mkdir()
        (source1_dir / "project1" / "llms-full.txt").write_text("Hello world from project1")
        (source1_dir / "project2").mkdir()
        (source1_dir / "project2" / "llms-full.txt").write_text("This is a test from project2")

        # source2/ with root llms-full.txt only
        source2_dir = source_dir / "source2"
        source2_dir.mkdir()
        (source2_dir / "llms-full.txt").write_text("Root combined text from source2")

        # Create a mock config
        mock_config = Config(
            token_source_dir=source_dir,
            token_output_file=output_file,
            token_encoding="cl100k_base"
        )

        # Patch get_config to return our temp config
        with patch('opencrane.rag.token_count.get_config', return_value=mock_config), \
             patch('tiktoken.get_encoding') as mock_enc, \
             patch('sys.argv', ['token_count.py']):
            # Mock token encoding to return fixed counts
            mock_enc.return_value.encode.side_effect = lambda text: ["token"] * len(text.split())

            # Run the main function (simulating CLI)
            main()

        # Check output
        captured = capsys.readouterr()
        assert "Report written to" in captured.out

        # Check the generated README
        assert output_file.exists()
        content = output_file.read_text()
        assert "# Token Count Summary" in content
        assert "all-projects" in content
        assert "source1/project1" in content
        assert "source1/project2" in content
        assert "source2" in content  # root llms-full.txt
        assert "Tokens" in content

    def test_token_count_empty_directory(self, temp_dirs, capsys):
        """Test token count with empty source directory."""
        source_dir, output_dir = temp_dirs
        output_file = output_dir / "README.md"

        mock_config = Config(
            token_source_dir=source_dir,
            token_output_file=output_file,
            token_encoding="cl100k_base"
        )

        with patch('opencrane.rag.token_count.get_config', return_value=mock_config), \
             patch('sys.argv', ['token_count.py']):
            main()

        captured = capsys.readouterr()
        assert "Report written to" in captured.out

        content = output_file.read_text()
        assert "# Token Count Summary" in content
        assert "**Total**" not in content
        assert "Tokens" in content

    def test_token_count_error_handling(self, temp_dirs, capsys):
        """Test error handling in main function."""
        source_dir, output_dir = temp_dirs

        # Patch get_config to raise an exception
        with patch('opencrane.rag.token_count.get_config', side_effect=Exception("Test error")), \
             patch('sys.argv', ['token_count.py']), \
             pytest.raises(SystemExit):
            main()

        captured = capsys.readouterr()
        assert "Error generating report: Test error" in captured.err