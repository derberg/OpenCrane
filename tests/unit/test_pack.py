"""Tests for the pack module."""

from pathlib import Path
from unittest.mock import patch

import click
import pytest

from opencrane.pack import pack, _PEP508_NAME_RE


@pytest.fixture()
def pack_dir(tmp_path, monkeypatch):
    """Create a minimal workspace with required data files and chdir into it."""
    monkeypatch.chdir(tmp_path)
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "milvus.db").write_bytes(b"fake-milvus")
    (opencrane_dir / "chunks.json").write_text("[]")
    return tmp_path


# === Name validation ===


@pytest.mark.unit
@pytest.mark.parametrize("name", ["my-docs-mcp", "docs.mcp", "a1_test"])
def test_valid_names(name):
    assert _PEP508_NAME_RE.match(name) is not None


@pytest.mark.unit
@pytest.mark.parametrize("name", ["123-bad", "-bad", "bad name", ""])
def test_invalid_names(name):
    assert _PEP508_NAME_RE.match(name) is None


@pytest.mark.unit
def test_pack_raises_on_invalid_name(pack_dir):
    with pytest.raises(click.BadParameter, match="Invalid package name"):
        pack(name="123-bad")


# === Missing data files ===


@pytest.mark.unit
def test_missing_both_data_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".opencrane").mkdir()
    with pytest.raises(click.ClickException, match="Required data files not found"):
        pack(name="test-mcp")


@pytest.mark.unit
def test_missing_chunks_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "milvus.db").write_bytes(b"fake")
    with pytest.raises(click.ClickException, match="Required data files not found"):
        pack(name="test-mcp")


@pytest.mark.unit
def test_missing_milvus_db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    opencrane_dir = tmp_path / ".opencrane"
    opencrane_dir.mkdir()
    (opencrane_dir / "chunks.json").write_text("[]")
    with pytest.raises(click.ClickException, match="Required data files not found"):
        pack(name="test-mcp")


# === Successful pack (happy path) ===


@pytest.mark.unit
def test_successful_pack(pack_dir, monkeypatch):
    monkeypatch.setattr(
        "opencrane.pack.importlib.metadata.version", lambda _pkg: "0.1.0"
    )
    monkeypatch.setattr(
        "opencrane.pack.subprocess.run",
        lambda *args, **kwargs: None,
    )

    output_dir, wheel_path = pack(name="test-mcp", version="2.0.0")

    assert output_dir == Path(".opencrane/pack/test-mcp")
    assert output_dir.exists()

    # pyproject.toml contains both distribution name and module name
    pyproject = (output_dir / "pyproject.toml").read_text()
    assert "test-mcp" in pyproject
    assert "test_mcp" in pyproject

    # Module files
    assert (output_dir / "test_mcp" / "__init__.py").exists()
    main_py = (output_dir / "test_mcp" / "__main__.py").read_text()
    assert "MCP server" in main_py

    # Data files copied
    assert (output_dir / "test_mcp" / "data" / "milvus.db").exists()
    assert (output_dir / "test_mcp" / "data" / "chunks.json").exists()

    # README
    readme = (output_dir / "README.md").read_text()
    assert "test-mcp" in readme


# === Custom output path ===


@pytest.mark.unit
def test_custom_output_path(pack_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "opencrane.pack.importlib.metadata.version", lambda _pkg: "0.1.0"
    )
    monkeypatch.setattr(
        "opencrane.pack.subprocess.run",
        lambda *args, **kwargs: None,
    )

    custom_output = tmp_path / "custom-output"
    output_dir, _ = pack(name="test-mcp", output=custom_output)

    assert output_dir == custom_output
    assert (custom_output / "pyproject.toml").exists()
    assert (custom_output / "test_mcp" / "__init__.py").exists()


# === Module name derivation ===


@pytest.mark.unit
def test_module_name_from_hyphens(pack_dir, monkeypatch):
    monkeypatch.setattr(
        "opencrane.pack.importlib.metadata.version", lambda _pkg: "0.1.0"
    )
    monkeypatch.setattr(
        "opencrane.pack.subprocess.run",
        lambda *args, **kwargs: None,
    )

    output_dir, _ = pack(name="my-docs-mcp")
    assert (output_dir / "my_docs_mcp" / "__init__.py").exists()


@pytest.mark.unit
def test_module_name_from_dots(pack_dir, monkeypatch):
    monkeypatch.setattr(
        "opencrane.pack.importlib.metadata.version", lambda _pkg: "0.1.0"
    )
    monkeypatch.setattr(
        "opencrane.pack.subprocess.run",
        lambda *args, **kwargs: None,
    )

    output_dir, _ = pack(name="my.docs.mcp")
    assert (output_dir / "my_docs_mcp" / "__init__.py").exists()


# === metadata-schema.md handling ===


@pytest.mark.unit
def test_metadata_schema_from_docs_dir(pack_dir, monkeypatch):
    monkeypatch.setattr(
        "opencrane.pack.importlib.metadata.version", lambda _pkg: "0.1.0"
    )
    monkeypatch.setattr(
        "opencrane.pack.subprocess.run",
        lambda *args, **kwargs: None,
    )

    docs_dir = pack_dir / "docs"
    docs_dir.mkdir()
    (docs_dir / "metadata-schema.md").write_text("# Schema from docs")

    output_dir, _ = pack(name="test-mcp")
    schema = output_dir / "test_mcp" / "data" / "metadata-schema.md"
    assert schema.exists()
    assert "Schema from docs" in schema.read_text()


@pytest.mark.unit
def test_metadata_schema_from_opencrane_dir(pack_dir, monkeypatch):
    monkeypatch.setattr(
        "opencrane.pack.importlib.metadata.version", lambda _pkg: "0.1.0"
    )
    monkeypatch.setattr(
        "opencrane.pack.subprocess.run",
        lambda *args, **kwargs: None,
    )

    (pack_dir / ".opencrane" / "metadata-schema.md").write_text("# Schema from .opencrane")

    output_dir, _ = pack(name="test-mcp")
    schema = output_dir / "test_mcp" / "data" / "metadata-schema.md"
    assert schema.exists()
    assert "Schema from .opencrane" in schema.read_text()


@pytest.mark.unit
def test_metadata_schema_docs_takes_priority(pack_dir, monkeypatch):
    """docs/metadata-schema.md is checked first and takes priority."""
    monkeypatch.setattr(
        "opencrane.pack.importlib.metadata.version", lambda _pkg: "0.1.0"
    )
    monkeypatch.setattr(
        "opencrane.pack.subprocess.run",
        lambda *args, **kwargs: None,
    )

    docs_dir = pack_dir / "docs"
    docs_dir.mkdir()
    (docs_dir / "metadata-schema.md").write_text("# From docs")
    (pack_dir / ".opencrane" / "metadata-schema.md").write_text("# From .opencrane")

    output_dir, _ = pack(name="test-mcp")
    schema = output_dir / "test_mcp" / "data" / "metadata-schema.md"
    assert "From docs" in schema.read_text()


@pytest.mark.unit
def test_no_metadata_schema(pack_dir, monkeypatch):
    monkeypatch.setattr(
        "opencrane.pack.importlib.metadata.version", lambda _pkg: "0.1.0"
    )
    monkeypatch.setattr(
        "opencrane.pack.subprocess.run",
        lambda *args, **kwargs: None,
    )

    output_dir, _ = pack(name="test-mcp")
    assert not (output_dir / "test_mcp" / "data" / "metadata-schema.md").exists()


# === Wheel build failure (graceful) ===


@pytest.mark.unit
def test_wheel_build_failure_returns_none(pack_dir, monkeypatch):
    monkeypatch.setattr(
        "opencrane.pack.importlib.metadata.version", lambda _pkg: "0.1.0"
    )

    def _raise(*args, **kwargs):
        raise RuntimeError("build tool not found")

    monkeypatch.setattr("opencrane.pack.subprocess.run", _raise)

    output_dir, wheel_path = pack(name="test-mcp")
    assert output_dir.exists()
    assert wheel_path is None
