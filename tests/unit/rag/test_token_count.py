import pytest
from pathlib import Path
from unittest.mock import patch, mock_open
from datetime import datetime, timezone
from opencrane.rag.token_count import TokenSummary, TokenReport, count_tokens_in_file, generate_report, write_report_to_markdown, main
from opencrane.shared.config import get_config
from opencrane.shared.utils.token_counter import get_token_count, get_tokenizer


class TestTokenSummary:
    def test_creation(self):
        summary = TokenSummary("test", 100, 5)
        assert summary.folder_name == "test"
        assert summary.token_count == 100
        assert summary.file_count == 5


class TestTokenReport:
    def test_creation(self):
        summaries = [TokenSummary("a", 10, 1), TokenSummary("b", 20, 2)]
        report = TokenReport(summaries, 30, datetime(2023, 1, 1), "/path")
        assert report.summaries == summaries
        assert report.total_tokens == 30
        assert report.generated_at == datetime(2023, 1, 1)
        assert report.source_directory == "/path"


class TestCountTokensInFile:
    def test_text_file(self):
        with patch("builtins.open", mock_open(read_data="Hello world")):
            with patch("tiktoken.get_encoding") as mock_enc:
                mock_enc.return_value.encode.return_value = ["token1", "token2"]
                result = count_tokens_in_file(Path("test.txt"))
                assert result == 2

    def test_binary_file(self):
        with patch("builtins.open", side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, "invalid")):
            result = count_tokens_in_file(Path("binary.bin"))
            assert result == 0

    def test_missing_file(self):
        with patch("builtins.open", side_effect=OSError):
            result = count_tokens_in_file(Path("missing.txt"))
            assert result == 0


class TestGenerateReport:
    def test_nonexistent_directory(self, tmp_path):
        report = generate_report(tmp_path / "does_not_exist")
        assert report.summaries == []
        assert report.total_tokens == 0
        assert report.source_directory == str(tmp_path / "does_not_exist")

    def test_with_folders(self, tmp_path):
        # Create test structure matching llmstxt/ directory layout
        # source1/ with projects
        source1_dir = tmp_path / "source1"
        source1_dir.mkdir()
        (source1_dir / "project1").mkdir()
        (source1_dir / "project1" / "llms-full.txt").write_text("hello project1")
        (source1_dir / "project2").mkdir()
        (source1_dir / "project2" / "llms-full.txt").write_text("world project2")
        
        # source2/ with root llms-full.txt only
        source2_dir = tmp_path / "source2"
        source2_dir.mkdir()
        (source2_dir / "llms-full.txt").write_text("combined source2")
        
        # Add a regular file (not directory) to test continue path
        (tmp_path / "regular-file.txt").write_text("should be skipped")

        with patch("tiktoken.get_encoding") as mock_enc:
            mock_enc.return_value.encode.return_value = ["token"]
            report = generate_report(tmp_path)
            
            # Should have: source1/project1, source1/project2, source2 (3 summaries)
            # regular-file.txt should be skipped
            # Note: all-projects is NOT in summaries, it's in write_report_to_markdown
            assert len(report.summaries) == 3
            
            # Verify structure
            assert report.summaries[0].folder_name == "source1/project1"
            assert report.summaries[1].folder_name == "source1/project2"
            assert report.summaries[2].folder_name == "source2"
            
            # Total should be sum (project1 + project2 + source2 = 3)
            assert report.total_tokens == 3

    def test_with_three_level_folders(self, tmp_path):
        """Test counting tokens in three-level directory structure (source/project/subproject)."""
        # Create test structure with subfolders
        source_dir = tmp_path / "source1"
        source_dir.mkdir()
        
        # project1 with direct files
        project1 = source_dir / "project1"
        project1.mkdir()
        (project1 / "llms-full.txt").write_text("project1 content")
        
        # project2 with subfolders
        project2 = source_dir / "project2"
        project2.mkdir()
        (project2 / "llms-full.txt").write_text("project2 root")
        
        subfolder1 = project2 / "subfolder1"
        subfolder1.mkdir()
        (subfolder1 / "llms-full.txt").write_text("subfolder1 content")
        
        subfolder2 = project2 / "subfolder2"
        subfolder2.mkdir()
        (subfolder2 / "llms-full.txt").write_text("subfolder2 content")

        with patch("tiktoken.get_encoding") as mock_enc:
            mock_enc.return_value.encode.return_value = ["token"]
            report = generate_report(tmp_path)
            
            # Should have: source1/project1, source1/project2, source1/project2/subfolder1, source1/project2/subfolder2
            assert len(report.summaries) == 4
            
            # Verify structure includes subfolders
            folder_names = [s.folder_name for s in report.summaries]
            assert "source1/project1" in folder_names
            assert "source1/project2" in folder_names
            assert "source1/project2/subfolder1" in folder_names
            assert "source1/project2/subfolder2" in folder_names
            
            # Total should be sum: project1 (1) + project2 root (1) + subfolder1 (1) + subfolder2 (1) = 4
            # Each llms-full.txt is counted exactly once, no double-counting
            assert report.total_tokens == 4


    def test_root_combined_file_counted(self, tmp_path):
        """A base-level llms-full.txt (all-projects combined) is counted as total."""
        # Base-level combined file present.
        (tmp_path / "llms-full.txt").write_text("combined all projects")

        # A source dir so the loop runs; total must come from the root combined file.
        source1 = tmp_path / "source1"
        source1.mkdir()
        (source1 / "llms-full.txt").write_text("source1 content")

        with patch("tiktoken.get_encoding") as mock_enc:
            mock_enc.return_value.encode.return_value = ["token"]
            report = generate_report(tmp_path)

            # Total is taken from the root combined file (1 token), not summed
            # from the per-source files.
            assert report.total_tokens == 1
            # The per-source summary is still recorded.
            assert any(s.folder_name == "source1" for s in report.summaries)


class TestWriteReportToMarkdown:
    def test_write_report(self, tmp_path):
        summaries = [TokenSummary("test", 100, 5)]
        report = TokenReport(summaries, 100, datetime(2023, 1, 1, 10, 30, tzinfo=timezone.utc), "/source")
        output_file = tmp_path / "subdir" / "report.md"

        write_report_to_markdown(report, output_file)

        content = output_file.read_text()
        assert "# Token Count Summary" in content
        assert "[test](test/llms-full.txt)" in content
        assert "| Folder | Tokens |" in content
        assert "**Total**" not in content

    def test_write_report_nested_folder_name(self, tmp_path):
        """A summary whose folder_name contains a slash exercises the nested-path branch."""
        summaries = [TokenSummary("src/proj", 42, 1)]
        report = TokenReport(summaries, 42, datetime(2023, 1, 1, tzinfo=timezone.utc), "/source")
        output_file = tmp_path / "report.md"

        write_report_to_markdown(report, output_file)

        content = output_file.read_text()
        assert "[src/proj](src/proj/llms-full.txt)" in content


class TestMain:
    def test_main_success(self, tmp_path, capsys):
        """main() generates a report and writes it to the output file."""
        source_dir = tmp_path / "llmstxt"
        source_dir.mkdir()
        (source_dir / "src1").mkdir()
        (source_dir / "src1" / "llms-full.txt").write_text("hello")
        output_file = tmp_path / "README.md"

        with patch("tiktoken.get_encoding") as mock_enc:
            mock_enc.return_value.encode.return_value = ["token"]
            main(source_dir=source_dir, output_file=output_file)

        assert output_file.exists()
        captured = capsys.readouterr()
        assert f"Report written to {output_file}" in captured.out

    def test_main_handles_exception_and_exits(self, capsys):
        """main() prints an error and exits non-zero when report generation fails."""
        with patch(
            "opencrane.rag.token_count.generate_report",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main(source_dir=Path("whatever"), output_file=Path("out.md"))

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error generating report: boom" in captured.err


class TestConfig:
    def test_config_has_token_fields(self):
        config = get_config()
        assert hasattr(config, 'token_source_dir')
        assert hasattr(config, 'token_output_file')
        assert hasattr(config, 'token_encoding')


class TestTokenCounter:
    def test_get_token_count(self):
        """Test token counting with mocked tiktoken."""
        with patch("tiktoken.get_encoding") as mock_get_encoding:
            mock_encoding = mock_get_encoding.return_value
            mock_encoding.encode.return_value = ["token1", "token2", "token3"]
            
            result = get_token_count("some text")
            assert result == 3
            mock_get_encoding.assert_called_once_with("cl100k_base")

    def test_get_tokenizer(self):
        """Test getting tokenizer encoding."""
        with patch("tiktoken.get_encoding") as mock_get_encoding:
            mock_encoding = mock_get_encoding.return_value
            
            result = get_tokenizer()
            assert result == mock_encoding
            mock_get_encoding.assert_called_once_with("cl100k_base")