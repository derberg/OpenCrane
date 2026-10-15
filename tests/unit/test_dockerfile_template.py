"""The generated Dockerfile bakes the optional reranker model into the offline image."""
import os
import re
import shutil
import subprocess

import pytest

from opencrane.templates import DOCKER_COMPOSE, DOCKERFILE


def _model_download_script() -> str:
    """Return the shell body of the model-stage RUN instruction."""
    stage = DOCKERFILE.split("FROM deps AS model", 1)[1].split("# Stage 3", 1)[0]
    run = stage.split("RUN --mount=type=cache,target=/root/.cache/huggingface", 1)[1]
    return re.sub(r"\\\n", "\n", run).strip()


def _run_download(tmp_path, reranker_model: str) -> list[str]:
    """Run the download step with a python3 stub that records each call."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    log = tmp_path / "calls.log"
    stub = bin_dir / "python3"
    stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$2" >> "{log}"\n')
    stub.chmod(0o755)
    script = _model_download_script().replace(
        "mkdir -p /build/hf_cache && cp -r /root/.cache/huggingface /build/hf_cache/", "true"
    ).replace(". /build/image.env && ", "")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "EMBEDDING_MODEL": "embed/model",
        "RERANKER_MODEL": reranker_model,
    }
    subprocess.run(["sh", "-ec", script], env=env, check=True, capture_output=True)
    return log.read_text().splitlines() if log.exists() else []


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_reranker_model_is_downloaded_only_when_set(tmp_path):
    without = _run_download(tmp_path / "off", "")
    assert len(without) == 1 and "SentenceTransformer('embed/model'" in without[0]

    with_reranker = _run_download(tmp_path / "on", "cross-encoder/test")
    assert len(with_reranker) == 2
    assert "CrossEncoder('cross-encoder/test'" in with_reranker[1]


@pytest.mark.unit
def test_runtime_image_and_compose_pass_reranker_model():
    runtime = DOCKERFILE.split("# Stage 4", 1)[1]
    assert "ARG RERANKER_MODEL=" in runtime
    assert "ENV RERANKER_MODEL=${RERANKER_MODEL}" in runtime
    assert 'RERANKER_MODEL: "${RERANKER_MODEL:-}"' in DOCKER_COMPOSE
