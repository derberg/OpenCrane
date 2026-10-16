"""EMBEDDING_DTYPE applies even to a model whose code ignores the dtype load kwarg."""

import logging
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch

from opencrane import visualize as viz
from opencrane.mcp.services.embeddings import EmbeddingService, cast_to_dtype

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_encoder_env(monkeypatch):
    for name in ("EMBEDDING_DTYPE", "EMBEDDING_DEVICE", "EMBEDDING_MAX_SEQ_LENGTH", "AI_DOCS_EMBEDDINGS_BACKEND"):
        monkeypatch.delenv(name, raising=False)


def _float32_module():
    """A model that stays float32 whatever dtype it was asked to load in, like nomic's remote code."""
    return torch.nn.Linear(4, 2)


@pytest.mark.parametrize("dtype", ["bfloat16", "float16"])
def test_cast_to_dtype_casts_the_weights(dtype):
    model = _float32_module()
    assert cast_to_dtype(model, dtype) == dtype
    assert all(p.dtype == getattr(torch, dtype) for p in model.parameters())


def test_cast_to_dtype_applies_float32_too():
    """A checkpoint stored in another precision still ends up in float32."""
    model = torch.nn.Linear(4, 2).to(torch.bfloat16)
    assert cast_to_dtype(model, "float32") == "float32"
    assert next(model.parameters()).dtype == torch.float32


def test_cast_to_dtype_with_a_model_that_has_no_parameter_list():
    model = MagicMock()
    model.parameters.return_value = 42
    assert cast_to_dtype(model, "float16") == "float16"
    model.to.assert_called_once_with(torch.float16)


def test_cast_to_dtype_without_parameters_reports_the_setting():
    model = MagicMock()
    model.parameters.return_value = iter([])
    assert cast_to_dtype(model, "bfloat16") == "bfloat16"
    model.to.assert_called_once_with(torch.bfloat16)


@patch("opencrane.mcp.services.embeddings.SentenceTransformer")
def test_service_casts_a_model_that_ignored_the_dtype_and_logs_the_real_dtype(st, monkeypatch, caplog):
    monkeypatch.setenv("EMBEDDING_DTYPE", "bfloat16")
    model = _float32_module()
    st.return_value = model

    with caplog.at_level(logging.INFO, logger="opencrane.mcp.services.embeddings"):
        EmbeddingService("nomic-ai/nomic-embed-text-v1.5")

    assert next(model.parameters()).dtype == torch.bfloat16
    assert "dtype=bfloat16" in caplog.text


@patch("opencrane.mcp.services.embeddings.SentenceTransformer")
def test_service_logs_the_loaded_dtype_not_the_setting(st, monkeypatch, caplog):
    monkeypatch.setenv("EMBEDDING_DTYPE", "bfloat16")
    model = MagicMock()
    model.parameters.return_value = iter([torch.zeros(1, dtype=torch.float16)])
    st.return_value = model

    with caplog.at_level(logging.INFO, logger="opencrane.mcp.services.embeddings"):
        EmbeddingService("some/model")

    assert "dtype=float16" in caplog.text


def test_visualize_casts_the_model(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DTYPE", "bfloat16")
    model = MagicMock()
    model.parameters.return_value = iter([])
    model.encode.return_value = np.array([[0.1, 0.2]], dtype=np.float32)
    with patch.object(viz, "_require") as req:
        req.side_effect = lambda name, *args: {"numpy": np}.get(name, MagicMock())
        with patch("sentence_transformers.SentenceTransformer", return_value=model):
            out = viz.encode_paragraph("dummy-model", "hello")
    model.to.assert_called_once_with(torch.bfloat16)
    assert out.dtype == np.float32
