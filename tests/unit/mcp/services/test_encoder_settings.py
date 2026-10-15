"""Tests for the env-backed encoder settings (dtype, device, batch size, max length, remote code)."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch

from opencrane.mcp.services import embeddings as embeddings_module
from opencrane.mcp.services.embeddings import EmbeddingService, encoder_model_kwargs
from opencrane.mcp.services.reranker import CrossEncoderReranker
from opencrane.shared.config import Config, resolve_trust_remote_code

ENCODER_VARS = (
    "EMBEDDING_DTYPE",
    "EMBEDDING_DEVICE",
    "EMBEDDING_BATCH_SIZE",
    "EMBEDDING_MAX_SEQ_LENGTH",
    "EMBEDDING_TRUST_REMOTE_CODE",
    "RERANKER_TRUST_REMOTE_CODE",
    "AI_DOCS_EMBEDDINGS_BACKEND",
)


@pytest.fixture(autouse=True)
def _clean_encoder_env(monkeypatch):
    for name in ENCODER_VARS:
        monkeypatch.delenv(name, raising=False)


pytestmark = pytest.mark.unit


# --- Config parsing --------------------------------------------------------


def test_config_encoder_defaults():
    config = Config()
    assert config.embedding_dtype == "float32"
    assert config.embedding_device == "cpu"
    assert config.embedding_batch_size == 8
    assert config.embedding_max_seq_length == 0
    assert config.embedding_trust_remote_code is None
    assert config.reranker_trust_remote_code is None


def test_config_encoder_values_from_env(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DTYPE", " BFloat16 ")
    monkeypatch.setenv("EMBEDDING_DEVICE", "cuda:1")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "32")
    monkeypatch.setenv("EMBEDDING_MAX_SEQ_LENGTH", "2048")
    monkeypatch.setenv("EMBEDDING_TRUST_REMOTE_CODE", "TRUE")
    monkeypatch.setenv("RERANKER_TRUST_REMOTE_CODE", "false")
    config = Config()
    assert config.embedding_dtype == "bfloat16"
    assert config.embedding_device == "cuda:1"
    assert config.embedding_batch_size == 32
    assert config.embedding_max_seq_length == 2048
    assert config.embedding_trust_remote_code is True
    assert config.reranker_trust_remote_code is False


@pytest.mark.parametrize("value, expected", [
    ("", None), ("auto", None), ("1", True), ("yes", True), ("0", False), ("no", False),
])
def test_trust_remote_code_env_spellings(monkeypatch, value, expected):
    monkeypatch.setenv("EMBEDDING_TRUST_REMOTE_CODE", value)
    assert Config().embedding_trust_remote_code is expected


@pytest.mark.parametrize("name, value, message", [
    ("EMBEDDING_DTYPE", "int8", "EMBEDDING_DTYPE must be one of float32, bfloat16, float16"),
    ("EMBEDDING_BATCH_SIZE", "0", "EMBEDDING_BATCH_SIZE must be at least 1"),
    ("EMBEDDING_BATCH_SIZE", "eight", "EMBEDDING_BATCH_SIZE must be an integer"),
    ("EMBEDDING_MAX_SEQ_LENGTH", "-1", "EMBEDDING_MAX_SEQ_LENGTH must be at least 0"),
    ("EMBEDDING_TRUST_REMOTE_CODE", "maybe", "EMBEDDING_TRUST_REMOTE_CODE must be true, false"),
    ("RERANKER_TRUST_REMOTE_CODE", "sure", "RERANKER_TRUST_REMOTE_CODE must be true, false"),
])
def test_invalid_encoder_values_name_the_variable(monkeypatch, name, value, message):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=message):
        Config()


# --- trust_remote_code auto rule -------------------------------------------


@pytest.mark.parametrize("model, setting, expected", [
    ("nomic-ai/nomic-embed-text-v1.5", None, True),
    ("nomic-ai/nomic-embed-text-v1", None, True),
    ("Qwen/Qwen3-Embedding-0.6B", None, False),
    ("./local/nomic-ai/model", None, False),
    ("nomic-ai/nomic-embed-text-v1.5", False, False),
    ("Qwen/Qwen3-Embedding-0.6B", True, True),
])
def test_resolve_trust_remote_code(model, setting, expected):
    assert resolve_trust_remote_code(model, setting) is expected


# --- EmbeddingService --------------------------------------------------------


@patch("opencrane.mcp.services.embeddings.SentenceTransformer")
def test_default_nomic_model_trusts_remote_code(st):
    EmbeddingService("nomic-ai/nomic-embed-text-v1.5")
    st.assert_called_once_with("nomic-ai/nomic-embed-text-v1.5", trust_remote_code=True, device="cpu")


@patch("opencrane.mcp.services.embeddings.SentenceTransformer")
def test_explicit_settings_reach_the_model(st, monkeypatch):
    monkeypatch.setenv("EMBEDDING_DTYPE", "bfloat16")
    monkeypatch.setenv("EMBEDDING_DEVICE", "mps")
    monkeypatch.setenv("EMBEDDING_MAX_SEQ_LENGTH", "512")
    monkeypatch.setenv("EMBEDDING_TRUST_REMOTE_CODE", "false")
    model = MagicMock()
    model.max_seq_length = 32768
    st.return_value = model

    service = EmbeddingService("nomic-ai/nomic-embed-text-v1.5")

    st.assert_called_once_with(
        "nomic-ai/nomic-embed-text-v1.5",
        trust_remote_code=False,
        device="mps",
        model_kwargs={embeddings_module._dtype_kwarg_name(): torch.bfloat16},
    )
    assert service.model.max_seq_length == 512


@patch("opencrane.mcp.services.embeddings.SentenceTransformer")
def test_max_seq_length_zero_keeps_model_default(st):
    model = MagicMock()
    model.max_seq_length = 8192
    st.return_value = model
    EmbeddingService("some/model")
    assert model.max_seq_length == 8192


@patch("opencrane.mcp.services.embeddings.SentenceTransformer")
def test_batch_size_and_float32_vectors(st, monkeypatch):
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "3")
    model = MagicMock()
    model.encode.return_value = np.array([[0.5, 0.25]], dtype=np.float16)
    st.return_value = model

    result = EmbeddingService("some/model").generate_embeddings(
        [{"content": "x", "chunk_id": "c1", "source_file": "a.md", "chunk_type": "prose"}]
    )

    assert model.encode.call_args.kwargs["batch_size"] == 3
    assert result.embeddings[0].vector == [0.5, 0.25]
    assert all(type(v) is float for v in result.embeddings[0].vector)


def test_encoder_model_kwargs():
    assert encoder_model_kwargs("float32") == {}
    with patch.object(embeddings_module, "_dtype_kwarg_name", return_value="dtype"):
        assert encoder_model_kwargs("float16") == {"model_kwargs": {"dtype": torch.float16}}


@pytest.mark.parametrize("version, expected", [
    ("4.55.4", "torch_dtype"),
    ("4.56.0", "dtype"),
    ("5.0.0", "dtype"),
])
def test_dtype_kwarg_name_follows_transformers_version(version, expected):
    with patch("transformers.__version__", version):
        assert embeddings_module._dtype_kwarg_name() == expected


# --- CrossEncoderReranker ---------------------------------------------------


@pytest.mark.parametrize("model, env, expected", [
    ("cross/model", None, False),
    ("nomic-ai/some-reranker", None, True),
    ("cross/model", "true", True),
])
def test_reranker_trust_remote_code(monkeypatch, model, env, expected):
    if env is not None:
        monkeypatch.setenv("RERANKER_TRUST_REMOTE_CODE", env)
    with patch("sentence_transformers.CrossEncoder") as ce:
        CrossEncoderReranker(model)._load_model()
    ce.assert_called_once_with(model, device="cpu", trust_remote_code=expected)
