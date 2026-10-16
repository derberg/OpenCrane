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
    read_embeddings_header,
    render_env_file,
)
from opencrane.shared.models.vector_chunk import EmbeddingRecord, EmbeddingsFile
from opencrane.templates import DOCKER_COMPOSE, DOCKERFILE

pytestmark = pytest.mark.unit

_BUILD_ARGS = (
    "EMBEDDING_MODEL",
    "EMBEDDING_QUERY_PROMPT",
    "EMBEDDING_DOCUMENT_PROMPT",
    "EMBEDDING_TRUST_REMOTE_CODE",
    "EMBEDDING_DTYPE",
    "EMBEDDING_DEVICE",
    "RERANKER_MODEL",
    "RERANKER_TRUST_REMOTE_CODE",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Start each test with no build args in the env."""
    for name in _BUILD_ARGS:
        monkeypatch.delenv(name, raising=False)


def _write_embeddings(path, model="org/recorded-model", records=3, **fields):
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
        **fields,
    )
    path.write_text(json.dumps(data.model_dump(), indent=2))
    return path


# === reading the header of embeddings.json ===

def test_reads_header_from_embeddings_file(tmp_path):
    path = _write_embeddings(tmp_path / "embeddings.json", query_prompt="search_query: ")
    header = read_embeddings_header(path)
    assert header["model"] == "org/recorded-model"
    assert header["query_prompt"] == "search_query: "
    assert "embeddings" not in header


def test_reads_header_of_large_file(tmp_path, monkeypatch):
    path = _write_embeddings(tmp_path / "embeddings.json", records=200)
    monkeypatch.setattr(container_env, "_HEADER_BYTES", 1024)
    assert path.stat().st_size > 1024
    assert read_embeddings_header(path)["model"] == "org/recorded-model"


def test_reads_header_of_compact_file(tmp_path):
    path = tmp_path / "embeddings.json"
    path.write_text(json.dumps({"model": 'a\\b"c', "embeddings": []}))
    assert read_embeddings_header(path) == {"model": 'a\\b"c'}


def test_missing_header_gives_none_and_unreadable_header_raises(tmp_path, monkeypatch):
    assert read_embeddings_header(tmp_path / "missing.json") is None
    no_list = tmp_path / "no_list.json"
    no_list.write_text('{"model": "x"}')
    assert read_embeddings_header(no_list) == {"model": "x"}
    broken = tmp_path / "broken.json"
    broken.write_text('{"model": "x" "y", "embeddings": []}')
    with pytest.raises(ContainerEnvError, match="cannot be parsed"):
        read_embeddings_header(broken)


# === choosing the model ===

def test_model_comes_from_embeddings_when_build_arg_unset_or_empty(tmp_path, monkeypatch):
    path = _write_embeddings(tmp_path / "embeddings.json")
    assert build_settings(path)["EMBEDDING_MODEL"] == "org/recorded-model"
    monkeypatch.setenv("EMBEDDING_MODEL", "")
    assert build_settings(path)["EMBEDDING_MODEL"] == "org/recorded-model"


def test_matching_build_arg_is_accepted(tmp_path, monkeypatch):
    path = _write_embeddings(tmp_path / "embeddings.json")
    monkeypatch.setenv("EMBEDDING_MODEL", "org/recorded-model")
    assert build_settings(path)["EMBEDDING_MODEL"] == "org/recorded-model"


def test_different_build_arg_fails_because_the_server_would_refuse(tmp_path, monkeypatch):
    path = _write_embeddings(tmp_path / "embeddings.json")
    monkeypatch.setenv("EMBEDDING_MODEL", "org/other")
    with pytest.raises(ContainerEnvError, match="refuses to serve an index with another model"):
        build_settings(path)


def test_build_arg_alone_is_enough(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "org/given")
    assert build_settings(tmp_path / "missing.json")["EMBEDDING_MODEL"] == "org/given"


def test_no_build_arg_and_no_embeddings_fails_clearly(tmp_path):
    with pytest.raises(ContainerEnvError, match="opencrane embed"):
        build_settings(tmp_path / "missing.json")


# === trust_remote_code, from the shared rule ===

@pytest.mark.parametrize(
    "model,setting,expected",
    [
        ("nomic-ai/nomic-embed-text-v1.5", None, "true"),
        ("nomic-ai/nomic-embed-text-v1.5", "auto", "true"),
        ("BAAI/bge-small-en-v1.5", None, "false"),
        ("BAAI/bge-small-en-v1.5", "true", "true"),
        ("nomic-ai/nomic-embed-text-v1.5", "false", "false"),
    ],
)
def test_embedding_trust_remote_code(tmp_path, monkeypatch, model, setting, expected):
    path = _write_embeddings(tmp_path / "embeddings.json", model=model)
    if setting is not None:
        monkeypatch.setenv("EMBEDDING_TRUST_REMOTE_CODE", setting)
    assert build_settings(path)["EMBEDDING_TRUST_REMOTE_CODE"] == expected


def test_invalid_trust_remote_code_fails_the_build(tmp_path, monkeypatch, capsys):
    path = _write_embeddings(tmp_path / "embeddings.json")
    monkeypatch.setenv("EMBEDDING_TRUST_REMOTE_CODE", "maybe")
    assert container_env.main([str(path), str(tmp_path / "image.env")]) == 1
    assert "EMBEDDING_TRUST_REMOTE_CODE" in capsys.readouterr().err


def test_reranker_trust_remote_code_is_set_only_with_a_reranker(tmp_path, monkeypatch):
    path = _write_embeddings(tmp_path / "embeddings.json")
    monkeypatch.setenv("RERANKER_TRUST_REMOTE_CODE", "true")
    assert "RERANKER_TRUST_REMOTE_CODE" not in build_settings(path)
    monkeypatch.setenv("RERANKER_MODEL", "cross-encoder/x")
    assert build_settings(path)["RERANKER_TRUST_REMOTE_CODE"] == "true"
    monkeypatch.delenv("RERANKER_TRUST_REMOTE_CODE")
    assert build_settings(path)["RERANKER_TRUST_REMOTE_CODE"] == "false"
    monkeypatch.setenv("RERANKER_MODEL", "nomic-ai/reranker")
    assert build_settings(path)["RERANKER_TRUST_REMOTE_CODE"] == "true"


# === query prompt and runtime-only settings ===

def test_unset_query_prompt_stays_unset(tmp_path):
    path = _write_embeddings(tmp_path / "embeddings.json", query_prompt="search_query: ")
    assert build_settings(path) == {
        "EMBEDDING_MODEL": "org/recorded-model",
        "EMBEDDING_TRUST_REMOTE_CODE": "false",
    }


def test_matching_query_prompt_is_forwarded(tmp_path, monkeypatch):
    path = _write_embeddings(tmp_path / "embeddings.json", query_prompt="search_query: ")
    monkeypatch.setenv("EMBEDDING_QUERY_PROMPT", "search_query: ")
    assert build_settings(path)["EMBEDDING_QUERY_PROMPT"] == "search_query: "


def test_different_query_prompt_fails_including_empty(tmp_path, monkeypatch):
    path = _write_embeddings(tmp_path / "embeddings.json", query_prompt="search_query: ")
    for value in ("query: ", ""):
        monkeypatch.setenv("EMBEDDING_QUERY_PROMPT", value)
        with pytest.raises(ContainerEnvError, match="another query prompt"):
            build_settings(path)


def test_query_prompt_is_forwarded_when_embeddings_record_none(tmp_path, monkeypatch):
    path = tmp_path / "embeddings.json"
    path.write_text(json.dumps({"model": "org/m", "embeddings": []}))
    monkeypatch.setenv("EMBEDDING_QUERY_PROMPT", "")
    settings = build_settings(path)
    assert settings["EMBEDDING_QUERY_PROMPT"] == ""
    assert "EMBEDDING_QUERY_PROMPT=''" in render_env_file(settings)


def test_dtype_and_device_are_forwarded_only_when_set(tmp_path, monkeypatch):
    path = _write_embeddings(tmp_path / "embeddings.json")
    monkeypatch.setenv("EMBEDDING_DEVICE", "")
    settings = build_settings(path)
    assert "EMBEDDING_DTYPE" not in settings and "EMBEDDING_DEVICE" not in settings
    monkeypatch.setenv("EMBEDDING_DTYPE", "bfloat16")
    monkeypatch.setenv("EMBEDDING_DEVICE", "cuda")
    settings = build_settings(path)
    assert settings["EMBEDDING_DTYPE"] == "bfloat16"
    assert settings["EMBEDDING_DEVICE"] == "cuda"


def test_invalid_dtype_fails_the_build(tmp_path, monkeypatch, capsys):
    path = _write_embeddings(tmp_path / "embeddings.json")
    monkeypatch.setenv("EMBEDDING_DTYPE", "int4")
    assert container_env.main([str(path), str(tmp_path / "image.env")]) == 1
    assert "EMBEDDING_DTYPE" in capsys.readouterr().err


# === the env file ===

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


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_env_file_leaves_an_unset_prompt_unset(tmp_path):
    path = _write_embeddings(tmp_path / "embeddings.json", query_prompt="search_query: ")
    env_file = tmp_path / "image.env"
    assert container_env.main([str(path), str(env_file)]) == 0
    assert _source(env_file, 'printf "%s" "${EMBEDDING_QUERY_PROMPT-unset}"', {}) == "unset"


def test_main_writes_env_file(tmp_path, monkeypatch, capsys):
    path = _write_embeddings(
        tmp_path / "embeddings.json", model="nomic-ai/nomic-embed-text-v1.5", query_prompt="search_query: "
    )
    out = tmp_path / "out" / "image.env"
    monkeypatch.setenv("EMBEDDING_QUERY_PROMPT", "search_query: ")

    assert container_env.main([str(path), str(out)]) == 0
    text = out.read_text()
    assert "EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5;" in text
    assert "EMBEDDING_TRUST_REMOTE_CODE=true;" in text
    assert "EMBEDDING_QUERY_PROMPT='search_query: ';" in text
    assert "EMBEDDING_DOCUMENT_PROMPT" not in text
    assert "EMBEDDING_MODEL='nomic-ai/nomic-embed-text-v1.5'" in capsys.readouterr().out


def test_main_fails_without_model(tmp_path, capsys):
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
        "EMBEDDING_DTYPE",
        "EMBEDDING_DEVICE",
        "RERANKER_MODEL",
        "RERANKER_TRUST_REMOTE_CODE",
    ):
        assert f"ARG {name}=" in settings
    assert "EMBEDDING_DOCUMENT_PROMPT" not in DOCKERFILE
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
        "EMBEDDING_QUERY_PROMPT",
        "EMBEDDING_TRUST_REMOTE_CODE",
        "EMBEDDING_DTYPE",
        "EMBEDDING_DEVICE",
        "RERANKER_TRUST_REMOTE_CODE",
    ):
        # A bare key: compose passes the variable only when the shell sets it.
        assert name in args and args[name] is None
    assert "EMBEDDING_DOCUMENT_PROMPT" not in DOCKER_COMPOSE
    # An empty runtime value would mean "no prompt", so the runtime entry is a
    # bare key too, and the model is never forced at run time.
    environment = compose["environment"]
    assert environment["EMBEDDING_QUERY_PROMPT"] is None
    assert "EMBEDDING_MODEL" not in environment


def test_prompt_build_args_have_no_default():
    settings = DOCKERFILE.split("FROM deps AS settings", 1)[1].split("FROM deps AS model", 1)[0]
    assert "ARG EMBEDDING_QUERY_PROMPT\n" in settings
