"""Startup, skip and recording rules for the embedding settings.

Covers the HTTP and stdio startup checks, the ``embed`` skip check, the settings
recorded for older embeddings files and collections, and model load errors.
"""

import json
import logging
from unittest.mock import AsyncMock, MagicMock, Mock, mock_open, patch

import pytest
from starlette.testclient import TestClient

from opencrane.mcp import http_server, server
from opencrane.mcp.init_vector_db import main as init_main
from opencrane.mcp.services.embedding_settings import (
    EmbeddingSettingsMismatch,
    resolve_embedding_settings,
)
from opencrane.mcp.services.milvus_client import MilvusService, milvus_lite_path
from opencrane.rag import generate_embeddings
from opencrane.rag.generate_embeddings import (
    _chunks_sha256,
    _effective_model,
    _embeddings_up_to_date,
    _sync_query_prompt,
)
from opencrane.shared.config import Config, remote_code_error

_DEFAULT_MODEL = "nomic-ai/nomic-embed-text-v1.5"
_RECORDED = {
    "model": "intfloat/e5-base-v2",
    "document_prompt": "passage: ",
    "query_prompt": "query: ",
    "dim": 768,
}


@pytest.fixture
def clean_env(monkeypatch):
    for name in (
        "EMBEDDING_MODEL",
        "EMBEDDING_QUERY_PROMPT",
        "EMBEDDING_DOCUMENT_PROMPT",
        "EMBEDDING_TRUST_REMOTE_CODE",
        "RERANKER_TRUST_REMOTE_CODE",
        "AI_DOCS_EMBEDDINGS_BACKEND",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def open_config(tmp_path, monkeypatch):
    """An empty config.yaml: one open endpoint at /mcp."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("", encoding="utf-8")
    monkeypatch.setenv("MAPPING_FILE", str(cfg))
    monkeypatch.setattr(http_server, "_services_ready", False)
    yield
    http_server._services_ready = False


# --- HTTP startup ----------------------------------------------------------


class TestHttpStartup:
    def test_health_is_ready_after_startup_without_mcp_request(self, open_config):
        payload = {"status": "healthy", "checks": {}}
        milvus = Mock(get_collection_stats=Mock(return_value={"row_count": 3}))
        app = http_server.build_asgi_app()
        with patch("opencrane.mcp.server.get_embeddings_service"), \
             patch("opencrane.mcp.server.get_milvus_service", return_value=milvus), \
             patch("opencrane.mcp.server.compute_health", new=AsyncMock(return_value=payload)):
            with TestClient(app) as client:
                response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_mismatch_fails_single_endpoint_startup(self, open_config):
        with patch(
            "opencrane.mcp.server.get_embeddings_service",
            side_effect=EmbeddingSettingsMismatch("EMBEDDING_MODEL is 'a'"),
        ):
            with pytest.raises(EmbeddingSettingsMismatch):
                with TestClient(http_server.build_asgi_app()):
                    pass  # pragma: no cover

    @pytest.mark.anyio
    async def test_main_exits_non_zero_when_server_did_not_start(self):
        uvicorn = Mock()
        uvicorn.Server.return_value = Mock(serve=AsyncMock(), started=False)
        with patch.dict("sys.modules", {"uvicorn": uvicorn}):
            with pytest.raises(SystemExit) as exc:
                await http_server.main()
        assert exc.value.code == 1

    @pytest.mark.anyio
    @pytest.mark.parametrize("config_yaml", [
        "",
        "auth:\n  public:\n    type: none\n  docs:\n    type: none\n",
    ])
    async def test_real_uvicorn_exits_non_zero_on_mismatch(self, config_yaml, tmp_path, monkeypatch, caplog):
        """Single- and multi-endpoint apps both stop the process on a mismatch."""
        cfg = tmp_path / "config.yaml"
        cfg.write_text(config_yaml, encoding="utf-8")
        monkeypatch.setenv("MAPPING_FILE", str(cfg))
        monkeypatch.setenv("MCP_HTTP_PORT", "0")
        monkeypatch.setenv("MCP_HTTP_HOST", "127.0.0.1")
        monkeypatch.setattr(http_server, "app", http_server.build_asgi_app())
        with patch(
            "opencrane.mcp.server.get_embeddings_service",
            side_effect=EmbeddingSettingsMismatch("EMBEDDING_MODEL is 'a'"),
        ):
            with pytest.raises(SystemExit) as exc:
                await http_server.main()
        assert exc.value.code not in (0, None)
        assert "EMBEDDING_MODEL is 'a'" in caplog.text


# --- stdio startup ---------------------------------------------------------


class TestStdioStartupCheck:
    def test_missing_lite_db_skips_check_without_creating_it(self, clean_env, tmp_path, caplog):
        db = tmp_path / "milvus.db"
        clean_env.setenv("MILVUS_DB_PATH", str(db))
        connect = Mock()
        clean_env.setattr(server, "get_milvus_service", connect)
        with caplog.at_level(logging.INFO):
            server.check_embedding_settings()
        connect.assert_not_called()
        assert not db.exists()
        assert "read on first use" in caplog.text

    def test_server_mode_connects_with_short_timeout(self, clean_env, caplog):
        clean_env.setenv("MILVUS_DB_PATH", "")
        clean_env.setattr(server, "_milvus_service", None)
        milvus = Mock(embedding_metadata=Mock(return_value=_RECORDED))
        with patch.object(server, "MilvusService", return_value=milvus) as milvus_class:
            with caplog.at_level(logging.INFO):
                server.check_embedding_settings()
        milvus_class.assert_called_once_with(connect_timeout=server._STARTUP_CONNECT_TIMEOUT)
        assert "'intfloat/e5-base-v2' (from index)" in caplog.text

    def test_unreadable_index_is_not_cached(self, clean_env, tmp_path, caplog):
        db = tmp_path / "milvus.db"
        db.touch()
        clean_env.setenv("MILVUS_DB_PATH", str(db))
        milvus = Mock(embedding_metadata=Mock(side_effect=Exception("collection not found")))
        clean_env.setattr(server, "get_milvus_service", lambda: milvus)
        with caplog.at_level(logging.INFO):
            server.check_embedding_settings()
        assert server._embedding_settings is None
        assert "collection not found" in caplog.text
        assert "(from index)" not in caplog.text


# --- stdio settings caching ------------------------------------------------


class TestSettingsAfterLateIndex:
    def test_service_switches_to_indexed_model_once_index_exists(self, clean_env):
        """A server started before 'opencrane index' picks up the indexed model."""
        milvus = Mock(embedding_metadata=Mock(side_effect=Exception("collection not found")))
        clean_env.setattr(server, "get_milvus_service", lambda: milvus)
        with patch.object(server, "EmbeddingService") as service_class:
            first = server.get_embeddings_service()
            assert server.get_embeddings_service() is first  # same model: reused
            assert service_class.call_args.kwargs == {"model_name": _DEFAULT_MODEL}
            assert server._embedding_settings is None

            milvus.embedding_metadata.side_effect = None
            milvus.embedding_metadata.return_value = _RECORDED
            service_class.return_value = Mock(model=None)
            second = server.get_embeddings_service()
        assert second is not first
        assert service_class.call_args.kwargs == {"model_name": "intfloat/e5-base-v2"}
        assert server.get_embedding_settings().model_source == "index"
        milvus.embedding_metadata.assert_called_with(raise_on_error=True)
        calls = milvus.embedding_metadata.call_count
        assert server.get_embeddings_service() is second  # cached: no further reads
        assert milvus.embedding_metadata.call_count == calls

    def test_mismatch_appears_once_index_exists(self, clean_env):
        clean_env.setenv("EMBEDDING_MODEL", "other/model")
        milvus = Mock(embedding_metadata=Mock(side_effect=Exception("collection not found")))
        clean_env.setattr(server, "get_milvus_service", lambda: milvus)
        assert server.get_embedding_settings().model == "other/model"
        milvus.embedding_metadata.side_effect = None
        milvus.embedding_metadata.return_value = _RECORDED
        with pytest.raises(EmbeddingSettingsMismatch):
            server.get_embedding_settings()


class TestMilvusMetadataErrors:
    @pytest.fixture
    def milvus(self):
        with patch("opencrane.mcp.services.milvus_client.MilvusClient") as client_class:
            client_class.return_value = Mock()
            yield MilvusService()

    def test_raise_on_error_raises_read_errors(self, milvus):
        milvus.client.describe_collection.side_effect = Exception("collection not found")
        assert milvus.embedding_metadata() is None
        with pytest.raises(Exception, match="collection not found"):
            milvus.embedding_metadata(raise_on_error=True)

    def test_raise_on_error_still_returns_none_without_metadata(self, milvus):
        milvus.client.describe_collection.return_value = {"description": "plain text"}
        assert milvus.embedding_metadata(raise_on_error=True) is None

    def test_connect_timeout_is_passed_to_the_client(self, monkeypatch):
        monkeypatch.setenv("MILVUS_DB_PATH", "")
        with patch("opencrane.mcp.services.milvus_client.MilvusClient") as client_class:
            MilvusService(connect_timeout=2.5)
        assert client_class.call_args.kwargs["timeout"] == 2.5

    @pytest.mark.parametrize("env, expected", [
        ({"MILVUS_DB_PATH": "/x/milvus.db"}, "/x/milvus.db"),
        ({"MILVUS_DB_PATH": ""}, None),
        ({"MILVUS_HOST": "milvus"}, None),
        ({}, ".opencrane/milvus.db"),
    ])
    def test_milvus_lite_path(self, monkeypatch, env, expected):
        monkeypatch.delenv("MILVUS_DB_PATH", raising=False)
        monkeypatch.delenv("MILVUS_HOST", raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        assert milvus_lite_path() == expected


# --- resolution of older indexes -------------------------------------------


class TestOlderIndexes:
    def test_document_prompt_without_query_prompt_gets_no_query_prompt(self, clean_env):
        settings = resolve_embedding_settings({"model": _DEFAULT_MODEL, "document_prompt": "", "dim": 768})
        assert (settings.query_prompt, settings.query_prompt_source) == ("", "legacy")

    def test_old_collection_keeps_env_prompts(self, clean_env):
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "q: ")
        clean_env.setenv("EMBEDDING_DOCUMENT_PROMPT", "d: ")
        settings = resolve_embedding_settings(None)
        assert (settings.query_prompt, settings.query_prompt_source) == ("q: ", "env")
        assert (settings.document_prompt, settings.document_prompt_source) == ("d: ", "env")

    def test_no_collection_yet_uses_model_defaults(self, clean_env):
        settings = resolve_embedding_settings({})
        assert (settings.query_prompt, settings.query_prompt_source) == ("search_query: ", "default")

    def test_no_collection_yet_uses_env_query_prompt(self, clean_env):
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "q: ")
        settings = resolve_embedding_settings({})
        assert (settings.query_prompt, settings.query_prompt_source) == ("q: ", "env")

    def test_empty_env_query_prompt_mismatch_points_at_compose_file(self, clean_env):
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "")
        with pytest.raises(EmbeddingSettingsMismatch, match="docker-compose.yml"):
            resolve_embedding_settings(_RECORDED)

    def test_other_query_prompt_mismatch_has_no_compose_hint(self, clean_env):
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "other: ")
        with pytest.raises(EmbeddingSettingsMismatch) as exc:
            resolve_embedding_settings(_RECORDED)
        assert "docker-compose.yml" not in str(exc.value)


# --- index step ------------------------------------------------------------

_CHUNKS = [{"content": "test", "chunk_type": "prose", "source_file": "test.md",
            "token_count": 10, "line_start": 1, "metadata": {}, "chunk_id": "c1"}]


def _old_embeddings_file(path):
    """An embeddings file from 0.33: no query_prompt field."""
    path.write_text(json.dumps({
        "model": _DEFAULT_MODEL,
        "dimensions": 4,
        "created_at": "2026-01-01T00:00:00+00:00",
        "chunks_sha256": "x",
        "document_prompt": "",
        "embeddings": [{"chunk_index": 0, "chunk_id": "c1", "vector": [0.1, 0.2, 0.3, 0.4]}],
    }))


class TestIndexStep:
    def _run(self, tmp_path):
        chunks = tmp_path / "chunks.json"
        chunks.write_text(json.dumps(_CHUNKS))
        embeddings = tmp_path / "embeddings.json"
        _old_embeddings_file(embeddings)
        milvus = MagicMock()
        milvus.client.has_collection.return_value = False
        with patch("opencrane.mcp.init_vector_db.setup_logging"), \
             patch("opencrane.mcp.init_vector_db.MilvusService", return_value=milvus), \
             patch("opencrane.mcp.services.embeddings.SentenceTransformer") as st:
            init_main(chunks, embeddings)
        return milvus, st

    def test_index_does_not_load_the_embedding_model(self, clean_env, tmp_path):
        clean_env.setenv("EMBEDDING_DEVICE", "cuda")
        milvus, st = self._run(tmp_path)
        st.assert_not_called()
        milvus.insert_chunks.assert_called_once()

    def test_old_embeddings_file_records_old_query_prompt_rule(self, clean_env, tmp_path):
        milvus, _ = self._run(tmp_path)
        recorded = milvus.create_collection.call_args.kwargs["embedding_metadata"]
        assert recorded["query_prompt"] == ""
        settings = resolve_embedding_settings(recorded)
        assert (settings.query_prompt, settings.query_prompt_source) == ("", "index")

    def test_old_embeddings_file_records_env_query_prompt(self, clean_env, tmp_path):
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "q: ")
        milvus, _ = self._run(tmp_path)
        assert milvus.create_collection.call_args.kwargs["embedding_metadata"]["query_prompt"] == "q: "


# --- embed step ------------------------------------------------------------


def _write_pair(tmp_path, **record):
    chunks = tmp_path / "chunks.json"
    chunks.write_bytes(b'[{"content": "x"}]')
    embeddings = tmp_path / "embeddings.json"
    embeddings.write_text(json.dumps({"chunks_sha256": _chunks_sha256(chunks), "document_prompt": "", **record}))
    return chunks, embeddings


class TestEmbedModel:
    def test_env_model_differs_from_recorded_reembeds(self, clean_env, tmp_path, caplog):
        clean_env.setenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
        chunks, embeddings = _write_pair(tmp_path, model="sentence-transformers/all-MiniLM-L6-v2")
        with caplog.at_level(logging.INFO):
            assert _embeddings_up_to_date(chunks, embeddings) is False
        assert "re-embedding with 'Qwen/Qwen3-Embedding-0.6B'" in caplog.text

    def test_env_model_equal_to_recorded_skips(self, clean_env, tmp_path):
        clean_env.setenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        chunks, embeddings = _write_pair(tmp_path, model="sentence-transformers/all-MiniLM-L6-v2")
        assert _embeddings_up_to_date(chunks, embeddings) is True

    def test_unset_env_keeps_recorded_model(self, clean_env, tmp_path):
        _, embeddings = _write_pair(tmp_path, model="sentence-transformers/all-MiniLM-L6-v2")
        assert _effective_model(embeddings) == "sentence-transformers/all-MiniLM-L6-v2"

    @pytest.mark.parametrize("env", [None, ""])
    def test_default_model_without_embeddings_file(self, clean_env, tmp_path, env):
        if env is not None:
            clean_env.setenv("EMBEDDING_MODEL", env)
        assert _effective_model(tmp_path / "missing.json") == _DEFAULT_MODEL

    @pytest.mark.parametrize("content", ["not json", "[1, 2]", '{"model": 3}', '{"model": ""}'])
    def test_unusable_recorded_model_falls_back_to_default(self, clean_env, tmp_path, content):
        path = tmp_path / "embeddings.json"
        path.write_text(content)
        assert _effective_model(path) == _DEFAULT_MODEL

    def test_forced_run_without_env_reembeds_with_recorded_model(self, clean_env, tmp_path):
        chunks, embeddings = _write_pair(tmp_path, model="sentence-transformers/all-MiniLM-L6-v2")
        with patch.object(generate_embeddings, "setup_logging"), \
             patch.object(generate_embeddings, "EmbeddingService") as service_class:
            generate_embeddings.main(chunks, embeddings, force=True)
        service_class.assert_called_once_with(model_name="sentence-transformers/all-MiniLM-L6-v2")


class TestSyncQueryPromptAtomic:
    def test_failed_write_keeps_original_file(self, clean_env, tmp_path):
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "query: ")
        path = tmp_path / "embeddings.json"
        original = json.dumps({"model": "m", "embeddings": []})
        path.write_text(original)
        with patch.object(generate_embeddings.json, "dump", side_effect=OSError("disk full")):
            _sync_query_prompt(path)
        assert path.read_text() == original
        assert list(tmp_path.iterdir()) == [path]

    def test_successful_write_leaves_no_temp_file(self, clean_env, tmp_path):
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "query: ")
        path = tmp_path / "embeddings.json"
        path.write_text(json.dumps({"model": "m"}))
        _sync_query_prompt(path)
        assert json.loads(path.read_text())["query_prompt"] == "query: "
        assert list(tmp_path.iterdir()) == [path]


def test_empty_embedding_model_env_uses_default(clean_env):
    clean_env.setenv("EMBEDDING_MODEL", "")
    assert Config().embedding_model == _DEFAULT_MODEL
    assert resolve_embedding_settings(None).model == _DEFAULT_MODEL


# --- remote code hint ------------------------------------------------------

_REMOTE_CODE_ERROR = ValueError(
    "The repository acme/model contains custom code which must be executed. "
    "Please pass the argument `trust_remote_code=True` to allow custom code to be run."
)


class TestRemoteCodeHint:
    def test_hint_names_the_env_var(self):
        hinted = remote_code_error(_REMOTE_CODE_ERROR, False, "EMBEDDING_TRUST_REMOTE_CODE")
        assert "EMBEDDING_TRUST_REMOTE_CODE=true" in str(hinted)
        assert "custom code" in str(hinted)

    def test_no_hint_when_trusted_or_unrelated(self):
        assert remote_code_error(_REMOTE_CODE_ERROR, True, "X") is None
        assert remote_code_error(OSError("no such model"), False, "X") is None

    def test_embedding_service_raises_hint(self, clean_env):
        from opencrane.mcp.services.embeddings import EmbeddingService

        with patch("opencrane.mcp.services.embeddings.SentenceTransformer", side_effect=_REMOTE_CODE_ERROR):
            with pytest.raises(RuntimeError, match="EMBEDDING_TRUST_REMOTE_CODE=true") as exc:
                EmbeddingService(model_name="acme/model")
        assert exc.value.__cause__ is _REMOTE_CODE_ERROR

    def test_embedding_service_reraises_other_errors(self, clean_env):
        from opencrane.mcp.services.embeddings import EmbeddingService

        with patch("opencrane.mcp.services.embeddings.SentenceTransformer", side_effect=OSError("offline")):
            with pytest.raises(OSError, match="offline"):
                EmbeddingService(model_name="acme/model")

    def test_reranker_raises_hint(self, clean_env):
        from opencrane.mcp.services.reranker import CrossEncoderReranker

        with patch("sentence_transformers.CrossEncoder", side_effect=_REMOTE_CODE_ERROR):
            with pytest.raises(RuntimeError, match="RERANKER_TRUST_REMOTE_CODE=true"):
                CrossEncoderReranker("acme/reranker")._load_model()

    def test_reranker_reraises_other_errors(self, clean_env):
        from opencrane.mcp.services.reranker import CrossEncoderReranker

        with patch("sentence_transformers.CrossEncoder", side_effect=OSError("offline")):
            with pytest.raises(OSError, match="offline"):
                CrossEncoderReranker("acme/reranker")._load_model()
