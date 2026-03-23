"""Tests for the source addition module and CLI commands."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from opencrane.add_source import add_github_source, add_llmstxt_source
from click.testing import CliRunner
from opencrane.cli import main as cli_main


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """Create a minimal workspace with .opencrane directory."""
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "sources.yaml").write_text("sources: {}\n")
    (opencrane_dir / "llmstxt").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


# === add_source module tests ===

@pytest.mark.unit
def test_add_github_source(workspace):
    add_github_source(
        name="my-docs/repo",
        github_url="https://github.com/org/repo",
        docs_path="docs",
        docs_url="",
    )
    sources = yaml.safe_load((workspace / ".opencrane" / "sources.yaml").read_text())
    entry = sources["sources"]["my-docs/repo"]
    assert entry["github_url"] == "https://github.com/org/repo"
    assert entry["docs_path"] == "docs"
    assert entry["manual"] is True


@pytest.mark.unit
def test_add_github_source_with_docs_url(workspace):
    add_github_source(
        name="my-docs/repo",
        github_url="https://github.com/org/repo",
        docs_path="docs",
        docs_url="https://docs.example.com",
    )
    sources = yaml.safe_load((workspace / ".opencrane" / "sources.yaml").read_text())
    assert sources["sources"]["my-docs/repo"]["docs_url"] == "https://docs.example.com"


@pytest.mark.unit
def test_add_llmstxt_source_from_local_file(workspace):
    local_file = workspace / "my-llms.txt"
    local_file.write_text("# My project docs\n\nContent here.")
    add_llmstxt_source(name="my-project", location=str(local_file))
    dest = workspace / ".opencrane" / "llmstxt" / "my-project" / "llms-full.txt"
    assert dest.exists()
    assert "My project docs" in dest.read_text()


@pytest.mark.unit
def test_add_llmstxt_source_from_url(workspace):
    mock_content = b"# Downloaded docs\n\nContent from URL."
    with patch("opencrane.add_source.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = mock_content
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response
        add_llmstxt_source(name="remote-project", location="https://example.com/llms-full.txt")
    dest = workspace / ".opencrane" / "llmstxt" / "remote-project" / "llms-full.txt"
    assert dest.exists()
    assert "Downloaded docs" in dest.read_text()


@pytest.mark.unit
def test_add_llmstxt_source_local_file_not_found(workspace):
    with pytest.raises(FileNotFoundError):
        add_llmstxt_source(name="bad", location="/nonexistent/file.txt")


# === CLI add command tests ===

@pytest.mark.unit
def test_cli_add_github_source(workspace):
    runner = CliRunner()
    result = runner.invoke(cli_main, ["add"], input="1\nhttps://github.com/org/repo\ndocs\n\norg/repo\nn\n")
    assert result.exit_code == 0
    assert "Added" in result.output
    sources = yaml.safe_load((workspace / ".opencrane" / "sources.yaml").read_text())
    assert "org/repo" in sources["sources"]


@pytest.mark.unit
def test_cli_add_llmstxt_source(workspace):
    local_file = workspace / "docs.txt"
    local_file.write_text("# Docs content")
    runner = CliRunner()
    result = runner.invoke(cli_main, ["add"], input=f"2\nmy-project\n{local_file}\nn\n")
    assert result.exit_code == 0
    assert (workspace / ".opencrane" / "llmstxt" / "my-project" / "llms-full.txt").exists()


@pytest.mark.unit
def test_cli_add_multiple_sources(workspace):
    file_a = workspace / "a.txt"
    file_a.write_text("# A")
    file_b = workspace / "b.txt"
    file_b.write_text("# B")
    runner = CliRunner()
    result = runner.invoke(cli_main, ["add"], input=f"2\nproject-a\n{file_a}\ny\n2\nproject-b\n{file_b}\nn\n")
    assert result.exit_code == 0
    assert (workspace / ".opencrane" / "llmstxt" / "project-a" / "llms-full.txt").exists()
    assert (workspace / ".opencrane" / "llmstxt" / "project-b" / "llms-full.txt").exists()


@pytest.mark.unit
def test_cli_add_without_opencrane_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli_main, ["add"])
    assert result.exit_code == 1
    assert "opencrane init" in result.output.lower()


@pytest.mark.unit
def test_cli_add_github_error_handling(workspace):
    runner = CliRunner()
    with patch("opencrane.add_source._get_mapping", side_effect=Exception("test error")):
        result = runner.invoke(cli_main, ["add"], input="1\nhttps://github.com/org/repo\ndocs\n\norg/repo\nn\n")
    assert result.exit_code == 0  # Should not crash


@pytest.mark.unit
def test_cli_add_llmstxt_file_not_found(workspace):
    runner = CliRunner()
    result = runner.invoke(cli_main, ["add"], input="2\nmy-project\n/nonexistent/file.txt\nn\n")
    assert result.exit_code == 0  # Should not crash


# === CLI init integration tests ===

@pytest.mark.unit
def test_init_offers_to_add_sources(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli_main, ["init"], input="n\n")
    assert result.exit_code == 0
    assert "add documentation sources" in result.output.lower() or "add sources" in result.output.lower()
    assert (tmp_path / ".opencrane" / "sources.yaml").exists()


@pytest.mark.unit
def test_init_with_add_sources(tmp_path, monkeypatch):
    local_file = tmp_path / "my-docs.txt"
    local_file.write_text("# Init test docs")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli_main, ["init"], input=f"y\n2\ninit-project\n{local_file}\nn\n")
    assert result.exit_code == 0
    assert (tmp_path / ".opencrane" / "llmstxt" / "init-project" / "llms-full.txt").exists()


@pytest.mark.unit
def test_init_no_add_flag_skips_prompt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli_main, ["init", "--no-add"])
    assert result.exit_code == 0
    assert (tmp_path / ".opencrane" / "sources.yaml").exists()
    assert "opencrane add" in result.output.lower() or "next steps" in result.output.lower()
