"""Regression tests for init, compose template and CLI output errors.

Covers the generated compose file pointing at the container file `init`
actually wrote, the collection env var the templates set, the compose
command `serve` prints, the MCP Inspector URL `inspect` prints, and the
llms-full.txt location `build` checks.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

import opencrane.cli as cli
from opencrane.cli import main as cli_main
from opencrane.templates import DOCKER_COMPOSE, DOCKERFILE


@pytest.fixture()
def runner():
    return CliRunner()


def _compose_dockerfile(path: Path) -> str:
    compose = yaml.safe_load(path.read_text())
    return compose["services"]["opencrane-mcp"]["build"]["dockerfile"]


# === init: compose points at the written container file ===

@pytest.mark.unit
def test_init_podman_compose_points_at_containerfile(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_main, ["init", "--no-add", "--podman"])
    assert result.exit_code == 0
    opencrane_dir = tmp_path / ".opencrane"
    dockerfile = _compose_dockerfile(opencrane_dir / "docker-compose.yml")
    assert dockerfile == ".opencrane/Containerfile"
    # The build context is the project root, so the path must resolve there.
    assert (tmp_path / dockerfile).exists()
    assert not (opencrane_dir / "Dockerfile").exists()


@pytest.mark.unit
def test_init_docker_compose_points_at_dockerfile(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_main, ["init", "--no-add"])
    assert result.exit_code == 0
    dockerfile = _compose_dockerfile(tmp_path / ".opencrane" / "docker-compose.yml")
    assert dockerfile == ".opencrane/Dockerfile"
    assert (tmp_path / dockerfile).exists()


@pytest.mark.unit
def test_docker_compose_renders_requested_file_name():
    from opencrane.templates import docker_compose

    assert "dockerfile: .opencrane/Containerfile" in docker_compose("Containerfile")
    assert docker_compose() == DOCKER_COMPOSE
    assert "dockerfile: .opencrane/Dockerfile" in DOCKER_COMPOSE


# === templates: collection env var the code actually reads ===

@pytest.mark.unit
def test_templates_set_milvus_collection_env_var(monkeypatch):
    from opencrane.shared.config import Config

    assert "COLLECTION_NAME" not in DOCKERFILE
    assert "COLLECTION_NAME" not in DOCKER_COMPOSE
    # Both the index stage and the runtime stage must name the same collection.
    assert DOCKERFILE.count("ENV MILVUS_COLLECTION=opencrane_chunks") == 2
    compose = yaml.safe_load(DOCKER_COMPOSE)
    env = compose["services"]["opencrane-mcp"]["environment"]
    assert env["MILVUS_COLLECTION"] == "opencrane_chunks"

    # The variable the templates set is the one the code reads.
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    assert Config().milvus_collection == "opencrane_chunks"


# === serve: printed compose command works from the project root ===

@pytest.mark.unit
def test_serve_stdio_prints_compose_file_path(runner):
    server_mod = MagicMock()
    with patch.object(cli, "load_config"), \
         patch("asyncio.run"), \
         patch.dict(sys.modules, {"opencrane.mcp.server": server_mod}):
        result = runner.invoke(cli_main, ["serve"])
    assert result.exit_code == 0
    assert "docker-compose -f .opencrane/docker-compose.yml up --build" in result.output
    assert "podman-compose -f .opencrane/docker-compose.yml up --build" in result.output


# === inspect: URL of the pinned MCP Inspector web UI ===

@pytest.mark.unit
def test_inspect_prints_inspector_default_port(runner, monkeypatch):
    monkeypatch.delenv("CLIENT_PORT", raising=False)
    completed = MagicMock(returncode=0)
    with patch("shutil.which", return_value="/usr/bin/npx"), \
         patch("subprocess.run", return_value=completed):
        result = runner.invoke(cli_main, ["inspect"])
    assert result.exit_code == 0
    assert "http://localhost:6274" in result.output
    assert "5173" not in result.output


@pytest.mark.unit
def test_inspect_prints_client_port_override(runner, monkeypatch):
    monkeypatch.setenv("CLIENT_PORT", "7000")
    completed = MagicMock(returncode=0)
    with patch("shutil.which", return_value="/usr/bin/npx"), \
         patch("subprocess.run", return_value=completed):
        result = runner.invoke(cli_main, ["inspect"])
    assert result.exit_code == 0
    assert "http://localhost:7000" in result.output


# === build: honours AI_DOCS_LLMSTXT_DIR when checking for output ===

@pytest.mark.unit
def test_build_uses_llmstxt_dir_env_var(runner, tmp_path, monkeypatch):
    """llms-full.txt written under AI_DOCS_LLMSTXT_DIR -> build continues."""
    monkeypatch.chdir(tmp_path)
    llms_dir = tmp_path / "custom-llms"
    llms_dir.mkdir()
    (llms_dir / "llms-full.txt").write_text("# Doc\n\ncontent\n")
    monkeypatch.setenv("AI_DOCS_LLMSTXT_DIR", str(llms_dir))

    chunk_main = MagicMock()
    with patch.object(cli, "load_config", return_value=MagicMock()), \
         patch("opencrane.rag.fetch_docs.main"), \
         patch("opencrane.rag.generate_llms_txt.generate_outputs"), \
         patch("opencrane.rag.chunker.main", chunk_main), \
         patch("opencrane.rag.generate_embeddings.main"), \
         patch("opencrane.mcp.init_vector_db.main"):
        result = runner.invoke(cli_main, ["build"])
    assert result.exit_code == 0, result.output
    assert "Nothing to process" not in result.output
    chunk_main.assert_called_once()


@pytest.mark.unit
def test_build_env_var_dir_without_output_stops(runner, tmp_path, monkeypatch):
    """Default dir has output but AI_DOCS_LLMSTXT_DIR points elsewhere -> stop."""
    monkeypatch.chdir(tmp_path)
    default_dir = tmp_path / ".opencrane" / "llmstxt"
    default_dir.mkdir(parents=True)
    (default_dir / "llms-full.txt").write_text("# Stale\n")
    monkeypatch.setenv("AI_DOCS_LLMSTXT_DIR", str(tmp_path / "empty-llms"))

    chunk_main = MagicMock()
    with patch.object(cli, "load_config", return_value=MagicMock()), \
         patch("opencrane.rag.fetch_docs.main"), \
         patch("opencrane.rag.generate_llms_txt.generate_outputs"), \
         patch("opencrane.rag.chunker.main", chunk_main):
        result = runner.invoke(cli_main, ["build"])
    assert result.exit_code == 0
    assert "Nothing to process" in result.output
    chunk_main.assert_not_called()


def test_runtime_image_uses_the_embedding_model_it_downloaded():
    """The runtime stage sets EMBEDDING_MODEL, so the server encodes queries with
    the model the build baked in, not the default."""
    from opencrane.templates import DOCKERFILE

    runtime = DOCKERFILE.split("# Stage 4", 1)[1]
    assert "COPY --from=settings /build/image.env /app/image.env" in runtime
    assert ". /app/image.env && exec opencrane serve" in runtime


# === init: README build command names the written container file ===

@pytest.mark.unit
def test_init_podman_readme_builds_from_containerfile(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_main, ["init", "--no-add", "--podman"])
    assert result.exit_code == 0
    readme_text = (tmp_path / ".opencrane" / "README.md").read_text()
    assert "podman build -t {REGISTRY}/opencrane-mcp:latest -f .opencrane/Containerfile ." in readme_text
    assert "-f .opencrane/Dockerfile" not in readme_text


@pytest.mark.unit
def test_init_docker_readme_builds_from_dockerfile(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_main, ["init", "--no-add"])
    assert result.exit_code == 0
    readme_text = (tmp_path / ".opencrane" / "README.md").read_text()
    assert "docker build -t {REGISTRY}/opencrane-mcp:latest -f .opencrane/Dockerfile ." in readme_text
    assert "Containerfile ." not in readme_text


# === init --extensions: config.yaml loads the generated file ===

@pytest.mark.unit
def test_init_extensions_enables_extensions_key(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_main, ["init", "--no-add", "--extensions"])
    assert result.exit_code == 0
    config = yaml.safe_load((tmp_path / ".opencrane" / "config.yaml").read_text())
    assert config["extensions"] == "extensions.py"


@pytest.mark.unit
def test_init_without_extensions_keeps_key_commented(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_main, ["init", "--no-add"])
    assert result.exit_code == 0
    text = (tmp_path / ".opencrane" / "config.yaml").read_text()
    assert "# extensions: extensions.py" in text
    assert "extensions" not in yaml.safe_load(text)


@pytest.mark.unit
def test_init_extensions_hints_when_config_exists(runner, tmp_path, monkeypatch):
    """An existing config.yaml is never overwritten, so init tells the user
    to add the key that loads the new extensions.py."""
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli_main, ["init", "--no-add"])
    result = runner.invoke(cli_main, ["init", "--no-add", "--extensions"])
    assert result.exit_code == 0
    assert "extensions: extensions.py" in result.output
    config = yaml.safe_load((tmp_path / ".opencrane" / "config.yaml").read_text())
    assert "extensions" not in config


@pytest.mark.unit
def test_init_extensions_no_hint_when_config_loads_extensions(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli_main, ["init", "--no-add", "--extensions"])
    result = runner.invoke(cli_main, ["init", "--no-add", "--extensions"])
    assert result.exit_code == 0
    assert "To load extensions.py" not in result.output
