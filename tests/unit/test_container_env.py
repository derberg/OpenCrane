"""The image build resolves the embedding model from embeddings.json, so the
model in the image, the index and the server cannot drift apart."""
import json
import shutil
import subprocess

import pytest
import yaml

from opencrane import container_env
from opencrane.container_env import (
    ContainerEnvError,
    build_settings,
    read_embeddings_model,
    render_env_file,
    resolve_embedding_model,
    resolve_trust_remote_code,
)
from opencrane.shared.models.vector_chunk import EmbeddingRecord, EmbeddingsFile
from opencrane.templates import DOCKER_COMPOSE, DOCKERFILE

pytestmark = pytest.mark.unit


def _write_embeddings(path, model="org/recorded-model", records=3):
    """Write an embeddings file the way ``opencrane embed`` does."""
    data = EmbeddingsFile(
        model=model,
        dimensions=4,
        created_at="2026-01-01T00:00:00+00:00",
        chunks_sha256="abc",
        document_prompt="search_document: ",
        embeddings=[
            EmbeddingRecord(chunk_index=i, chunk_id=f"c{i}", vector=[0.1, 0.2, 0.3, 0.4])
            for i in range(records)
        ],
    )
    path.write_text(json.dumps(data.model_dump(), indent=2))
    return path


# === reading the model from embeddings.json ===

def test_reads_model_from_embeddings_file(tmp_path):
    path = _write_embeddings(tmp_path / "embeddings.json")
    assert read_embeddings_model(path) == "org/recorded-model"


def test_reads_model_from_header_of_large_file(tmp_path, monkeypatch):
    path = _write_embeddings(tmp_path / "embeddings.json", records=200)
    monkeypatch.setattr(container_env, "_HEADER_BYTES", 128)
    assert path.stat().st_size > 128
    assert read_embeddings_model(path) == "org/recorded-model"


def test_reads_escaped_model_name(tmp_path):
    path = tmp_path / "embeddings.json"
    path.write_text(json.dumps({"model": 'a\\b"c', "embeddings": []}))
    assert read_embeddings_model(path) == 'a\\b"c'


def test_missing_file_or_field_gives_no_model(tmp_path):
    assert read_embeddings_model(tmp_path / "missing.json") is None
    no_field = tmp_path / "no_field.json"
    no_field.write_text('{"dimensions": 4}')
    assert read_embeddings_model(no_field) is None
    empty = tmp_path / "empty.json"
    empty.write_text('{"model": ""}')
    assert read_embeddings_model(empty) is None


# === choosing the model ===

def test_model_comes_from_embeddings_when_build_arg_empty(tmp_path):
    path = _write_embeddings(tmp_path / "embeddings.json")
    assert resolve_embedding_model("", path) == "org/recorded-model"


def test_explicit_build_arg_wins_and_warns_on_mismatch(tmp_path, capsys):
    path = _write_embeddings(tmp_path / "embeddings.json")
    assert resolve_embedding_model("org/other", path) == "org/other"
    assert "differs from the model org/recorded-model" in capsys.readouterr().err


def test_matching_build_arg_does_not_warn(tmp_path, capsys):
    path = _write_embeddings(tmp_path / "embeddings.json")
    assert resolve_embedding_model("org/recorded-model", path) == "org/recorded-model"
    assert capsys.readouterr().err == ""


def test_build_arg_alone_is_enough(tmp_path):
    assert resolve_embedding_model("org/given", tmp_path / "missing.json") == "org/given"


def test_no_build_arg_and_no_embeddings_fails_clearly(tmp_path):
    with pytest.raises(ContainerEnvError, match="opencrane embed"):
        resolve_embedding_model("", tmp_path / "missing.json")


# === trust_remote_code ===

@pytest.mark.parametrize(
    "model,setting,expected",
    [
        ("nomic-ai/nomic-embed-text-v1.5", "", True),
        ("nomic-ai/nomic-embed-text-v1.5", "auto", True),
        ("BAAI/bge-small-en-v1.5", "", False),
        ("BAAI/bge-small-en-v1.5", " AUTO ", False),
        ("BAAI/bge-small-en-v1.5", "yes", True),
        ("BAAI/bge-small-en-v1.5", "true", True),
        ("BAAI/bge-small-en-v1.5", "1", True),
        ("nomic-ai/nomic-embed-text-v1.5", "false", False),
        ("nomic-ai/nomic-embed-text-v1.5", "no", False),
    ],
)
def test_trust_remote_code(model, setting, expected):
    assert resolve_trust_remote_code(model, setting) is expected


def test_invalid_trust_remote_code_fails():
    with pytest.raises(ContainerEnvError, match="EMBEDDING_TRUST_REMOTE_CODE"):
        resolve_trust_remote_code("org/model", "maybe")
    with pytest.raises(ContainerEnvError, match="RERANKER_TRUST_REMOTE_CODE"):
        resolve_trust_remote_code("org/model", "on", "RERANKER_TRUST_REMOTE_CODE")


def test_reranker_trust_remote_code_is_set_only_with_a_reranker(tmp_path):
    path = _write_embeddings(tmp_path / "embeddings.json")
    assert "RERANKER_TRUST_REMOTE_CODE" not in build_settings({"RERANKER_TRUST_REMOTE_CODE": "true"}, path)
    assert build_settings({"RERANKER_MODEL": "nomic-ai/reranker"}, path)["RERANKER_TRUST_REMOTE_CODE"] == "true"
    assert build_settings({"RERANKER_MODEL": "cross-encoder/x"}, path)["RERANKER_TRUST_REMOTE_CODE"] == "false"
    assert (
        build_settings(
            {"RERANKER_MODEL": "cross-encoder/x", "RERANKER_TRUST_REMOTE_CODE": "true"}, path
        )["RERANKER_TRUST_REMOTE_CODE"]
        == "true"
    )


# === settings and env file ===

def test_settings_forward_only_set_prompts(tmp_path):
    path = _write_embeddings(tmp_path / "embeddings.json")
    settings = build_settings({"EMBEDDING_QUERY_PROMPT": "search_query: "}, path)
    assert settings == {
        "EMBEDDING_MODEL": "org/recorded-model",
        "EMBEDDING_TRUST_REMOTE_CODE": "false",
        "EMBEDDING_QUERY_PROMPT": "search_query: ",
    }


def test_prompt_set_to_empty_is_forwarded_as_no_prompt(tmp_path):
    path = _write_embeddings(tmp_path / "embeddings.json")
    settings = build_settings({"EMBEDDING_QUERY_PROMPT": "", "EMBEDDING_MODEL": ""}, path)
    assert settings["EMBEDDING_QUERY_PROMPT"] == ""
    assert settings["EMBEDDING_MODEL"] == "org/recorded-model"
    assert "EMBEDDING_DOCUMENT_PROMPT" not in settings
    assert "EMBEDDING_QUERY_PROMPT=''" in render_env_file(settings)


def _source(env_file, script, env):
    """Source *env_file* in a POSIX shell, then run *script*."""
    result = subprocess.run(
        ["sh", "-ec", f'. "{env_file}"; {script}'],
        env={"PATH": "/usr/bin:/bin", **env},
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_env_file_sets_unset_variables_and_keeps_runtime_values(tmp_path):
    prompt = "Instruct: it's $HOME `x`\\nQuery: {query}"
    env_file = tmp_path / "image.env"
    env_file.write_text(render_env_file({"EMBEDDING_MODEL": "org/m", "EMBEDDING_QUERY_PROMPT": prompt}))
    show = 'printf "%s|%s" "$EMBEDDING_MODEL" "${EMBEDDING_QUERY_PROMPT-unset}"'

    # Unset at run time: the baked values apply, exactly as given.
    assert _source(env_file, show, {}) == f"org/m|{prompt}"
    # Set at run time, even to empty: the run-time value wins.
    assert _source(env_file, show, {"EMBEDDING_MODEL": "org/x", "EMBEDDING_QUERY_PROMPT": ""}) == "org/x|"
    # Exported, so child processes such as the server see them.
    assert _source(env_file, "sh -c 'printf %s \"$EMBEDDING_MODEL\"'", {}) == "org/m"


def test_main_writes_env_file(tmp_path, monkeypatch, capsys):
    path = _write_embeddings(tmp_path / "embeddings.json", model="nomic-ai/nomic-embed-text-v1.5")
    out = tmp_path / "out" / "image.env"
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_TRUST_REMOTE_CODE", raising=False)
    monkeypatch.setenv("EMBEDDING_QUERY_PROMPT", "search_query: ")
    monkeypatch.delenv("EMBEDDING_DOCUMENT_PROMPT", raising=False)

    assert container_env.main([str(path), str(out)]) == 0
    text = out.read_text()
    assert "EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5;" in text
    assert "EMBEDDING_TRUST_REMOTE_CODE=true;" in text
    assert "EMBEDDING_QUERY_PROMPT='search_query: ';" in text
    assert "EMBEDDING_DOCUMENT_PROMPT" not in text
    assert "EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5" in capsys.readouterr().out


def test_main_fails_without_model(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    out = tmp_path / "image.env"
    assert container_env.main([str(tmp_path / "missing.json"), str(out)]) == 1
    assert "ERROR: Cannot determine the embedding model" in capsys.readouterr().err
    assert not out.exists()


def test_main_usage(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["container_env"])
    assert container_env.main() == 2
    assert "usage:" in capsys.readouterr().err


# === the generated Dockerfile and compose file use the settings ===

def test_dockerfile_resolves_settings_from_embeddings():
    settings = DOCKERFILE.split("FROM deps AS settings", 1)[1].split("FROM deps AS model", 1)[0]
    assert "ARG EMBEDDING_MODEL=\n" in settings
    for name in (
        "EMBEDDING_TRUST_REMOTE_CODE",
        "RERANKER_MODEL",
        "RERANKER_TRUST_REMOTE_CODE",
    ):
        assert f"ARG {name}=" in settings
    assert "python3 -m opencrane.container_env .opencrane/embeddings.json /build/image.env" in settings
    # No stage outside the settings stage declares the embedding build args.
    assert DOCKERFILE.count("ARG EMBEDDING_MODEL") == 1
    assert "nomic-ai/nomic-embed-text-v1.5" not in DOCKERFILE


def test_dockerfile_download_index_and_runtime_share_the_settings():
    model = DOCKERFILE.split("FROM deps AS model", 1)[1].split("# Stage 3", 1)[0]
    assert ". /build/image.env && " in model
    assert "trust_remote_code='${EMBEDDING_TRUST_REMOTE_CODE}' == 'true'" in model
    assert "trust_remote_code='${RERANKER_TRUST_REMOTE_CODE}' == 'true'" in model
    assert "trust_remote_code=True" not in DOCKERFILE
    milvus = DOCKERFILE.split("FROM deps AS milvus", 1)[1].split("# Stage 4", 1)[0]
    assert ". /build/image.env && opencrane index" in milvus
    runtime = DOCKERFILE.split("# Stage 4", 1)[1]
    assert "ENV EMBEDDING_" not in runtime
    assert "ENV TRANSFORMERS_OFFLINE=1" in runtime


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_entrypoint_sources_settings_and_passes_arguments(tmp_path):
    entrypoint_line = next(line for line in DOCKERFILE.splitlines() if line.startswith("ENTRYPOINT"))
    argv = json.loads(entrypoint_line[len("ENTRYPOINT "):])
    assert argv[:2] == ["/bin/sh", "-c"]
    env_file = tmp_path / "image.env"
    env_file.write_text(render_env_file({"EMBEDDING_MODEL": "org/m"}))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "opencrane"
    stub.write_text('#!/bin/sh\nprintf "%s " "$EMBEDDING_MODEL" "$@"\n')
    stub.chmod(0o755)
    script = argv[2].replace("/app/image.env", str(env_file))
    result = subprocess.run(
        ["sh", "-c", script, *argv[3:], "--port", "9000"],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == "org/m serve --transport http --port 9000 "


def test_compose_passes_settings_only_when_the_shell_sets_them():
    compose = yaml.safe_load(DOCKER_COMPOSE)["services"]["opencrane-mcp"]
    args = compose["build"]["args"]
    for name in (
        "EMBEDDING_MODEL",
        "EMBEDDING_TRUST_REMOTE_CODE",
        "EMBEDDING_QUERY_PROMPT",
        "EMBEDDING_DOCUMENT_PROMPT",
        "RERANKER_TRUST_REMOTE_CODE",
    ):
        # A bare key: compose passes the variable only when the shell sets it.
        assert name in args and args[name] is None
    # An empty runtime value would mean "no prompt", so the runtime entries are
    # bare keys too, and the model is never forced at run time.
    environment = compose["environment"]
    assert environment["EMBEDDING_QUERY_PROMPT"] is None
    assert environment["EMBEDDING_DOCUMENT_PROMPT"] is None
    assert "EMBEDDING_MODEL" not in environment


def test_prompt_build_args_have_no_default():
    settings = DOCKERFILE.split("FROM deps AS settings", 1)[1].split("FROM deps AS model", 1)[0]
    assert "ARG EMBEDDING_QUERY_PROMPT\n" in settings
    assert "ARG EMBEDDING_DOCUMENT_PROMPT\n" in settings
