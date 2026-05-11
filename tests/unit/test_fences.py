"""Tests for opencrane.fences.inline_file handler."""

import json
from pathlib import Path

import pytest

from opencrane.fences import inline_file


@pytest.fixture
def project_dir(tmp_path):
    return tmp_path


@pytest.fixture
def md_file(project_dir):
    f = project_dir / "docs" / "index.md"
    f.parent.mkdir()
    f.touch()
    return f


def test_inline_json_file(project_dir, md_file):
    spec = {"openapi": "3.0.0", "info": {"title": "Test"}}
    json_file = project_dir / "docs" / "api.json"
    json_file.write_text(json.dumps(spec))

    result = inline_file("api.json", md_file, project_dir, "myproject")

    assert "```json" in result
    assert '"openapi"' in result


def test_inline_yaml_file(project_dir, md_file):
    yaml_file = project_dir / "docs" / "spec.yaml"
    yaml_file.write_text("openapi: 3.0.0\ninfo:\n  title: Test\n")

    result = inline_file("spec.yaml", md_file, project_dir, "myproject")

    assert "```yaml" in result
    assert "openapi: 3.0.0" in result


def test_missing_file_returns_comment(project_dir, md_file):
    result = inline_file("nonexistent.json", md_file, project_dir, "myproject")

    assert "```json" in result
    assert "# Source missing" in result


def test_path_outside_project_returns_comment(project_dir, md_file):
    result = inline_file("../../etc/passwd", md_file, project_dir, "myproject")

    assert "# Source missing" in result


def test_injects_section_url_header(project_dir, md_file, monkeypatch):
    monkeypatch.setattr(
        "opencrane.fences.get_source_url",
        lambda rel, name: f"https://github.com/org/repo/blob/main/{rel}",
    )
    json_file = project_dir / "docs" / "api.json"
    json_file.write_text('{"openapi": "3.0.0"}')

    result = inline_file("api.json", md_file, project_dir, "myproject")

    assert result.startswith("### https://github.com/")


def test_no_url_when_source_mapping_missing(project_dir, md_file, monkeypatch):
    monkeypatch.setattr("opencrane.fences.get_source_url", lambda rel, name: None)
    json_file = project_dir / "docs" / "api.json"
    json_file.write_text('{"openapi": "3.0.0"}')

    result = inline_file("api.json", md_file, project_dir, "myproject")

    assert not result.startswith("###")
    assert "```json" in result
