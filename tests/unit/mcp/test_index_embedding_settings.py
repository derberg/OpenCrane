"""The index records the embedding model and prompts, and the server uses them."""

import json
import logging
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest

from opencrane.mcp import server
from opencrane.mcp import http_server
from opencrane.mcp.init_vector_db import _REQUIRED_FIELDS, _embedding_metadata, main as init_main
from opencrane.mcp.services.embedding_settings import (
    EmbeddingSettings,
    EmbeddingSettingsMismatch,
    resolve_embedding_settings,
    with_model_prompts,
)
from opencrane.mcp.services.milvus_client import MilvusService
from opencrane.rag.generate_embeddings import _sync_query_prompt
from opencrane.shared.models.vector_chunk import EmbeddingRecord, EmbeddingsFile
from opencrane.shared.utils.embedding_prompts import warn_if_inconsistent

_RECORDED = {
    "model": "intfloat/e5-base-v2",
    "document_prompt": "passage: ",
    "query_prompt": "query: ",
    "dim": 768,
}


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("EMBEDDING_MODEL", "EMBEDDING_QUERY_PROMPT", "EMBEDDING_DOCUMENT_PROMPT"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def milvus():
    with patch("opencrane.mcp.services.milvus_client.MilvusClient") as client_class:
        client_class.return_value = Mock()
        yield MilvusService()


# --- MilvusService ---------------------------------------------------------


class TestMilvusEmbeddingMetadata:
    def test_create_collection_writes_metadata_to_description(self, milvus):
        milvus.create_collection(dim=768, embedding_metadata=_RECORDED)
        kwargs = milvus.client.create_schema.call_args.kwargs
        assert json.loads(kwargs["description"]) == {"opencrane_embedding": _RECORDED}
        assert milvus.embedding_metadata() == _RECORDED  # cached, no describe
        milvus.client.describe_collection.assert_not_called()

    def test_create_collection_without_metadata_leaves_description_empty(self, milvus):
        milvus.create_collection(dim=768)
        assert milvus.client.create_schema.call_args.kwargs["description"] == ""

    def test_reads_and_caches_recorded_metadata(self, milvus):
        milvus.client.describe_collection.return_value = {
            "description": json.dumps({"opencrane_embedding": _RECORDED})
        }
        assert milvus.embedding_metadata() == _RECORDED
        assert milvus.embedding_metadata() == _RECORDED
        milvus.client.describe_collection.assert_called_once()

    @pytest.mark.parametrize("description", ["", "plain text", "[1, 2]", '{"other": 1}', '{"opencrane_embedding": "x"}'])
    def test_none_without_recorded_metadata(self, milvus, description):
        milvus.client.describe_collection.return_value = {"description": description}
        assert milvus.embedding_metadata() is None

    def test_none_when_collection_missing(self, milvus):
        milvus.client.describe_collection.side_effect = Exception("collection not found")
        assert milvus.embedding_metadata() is None


# --- resolution ------------------------------------------------------------


class TestResolveEmbeddingSettings:
    def test_index_values_win_when_env_unset(self, clean_env):
        settings = resolve_embedding_settings(_RECORDED)
        assert settings == EmbeddingSettings(
            model="intfloat/e5-base-v2",
            model_source="index",
            query_prompt="query: ",
            query_prompt_source="index",
            document_prompt="passage: ",
            document_prompt_source="index",
        )

    def test_empty_model_counts_as_unset(self, clean_env):
        clean_env.setenv("EMBEDDING_MODEL", "")
        assert resolve_embedding_settings(_RECORDED).model == "intfloat/e5-base-v2"

    def test_empty_query_prompt_is_an_explicit_value(self, clean_env):
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "")
        with pytest.raises(EmbeddingSettingsMismatch, match="EMBEDDING_QUERY_PROMPT is ''"):
            resolve_embedding_settings(_RECORDED)
        settings = resolve_embedding_settings({**_RECORDED, "query_prompt": ""})
        assert (settings.query_prompt, settings.query_prompt_source) == ("", "index")

    def test_env_equal_to_index_is_accepted(self, clean_env):
        clean_env.setenv("EMBEDDING_MODEL", "intfloat/e5-base-v2")
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "query: ")
        settings = resolve_embedding_settings(_RECORDED)
        assert settings.model_source == "index"
        assert settings.query_prompt_source == "index"

    def test_model_mismatch_raises_with_both_values(self, clean_env):
        clean_env.setenv("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")
        with pytest.raises(EmbeddingSettingsMismatch) as exc:
            resolve_embedding_settings(_RECORDED)
        message = str(exc.value)
        assert "EMBEDDING_MODEL" in message
        assert "nomic-ai/nomic-embed-text-v1.5" in message
        assert "intfloat/e5-base-v2" in message
        assert "opencrane index" in message

    def test_query_prompt_mismatch_raises(self, clean_env):
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "search_query: ")
        with pytest.raises(EmbeddingSettingsMismatch, match="EMBEDDING_QUERY_PROMPT"):
            resolve_embedding_settings(_RECORDED)

    def test_index_without_query_prompt_uses_env(self, clean_env):
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "query: ")
        recorded = {k: v for k, v in _RECORDED.items() if k != "query_prompt"}
        settings = resolve_embedding_settings(recorded)
        assert (settings.query_prompt, settings.query_prompt_source) == ("query: ", "env")

    def test_old_collection_uses_defaults_and_warns(self, clean_env, caplog):
        with caplog.at_level(logging.WARNING):
            settings = resolve_embedding_settings(None)
        assert settings.model == "nomic-ai/nomic-embed-text-v1.5"
        assert settings.model_source == "default"
        # A collection from 0.33 or older: no prompt unless the env sets one, as then.
        assert (settings.query_prompt, settings.query_prompt_source) == ("", "legacy")
        assert (settings.document_prompt, settings.document_prompt_source) == ("", "legacy")
        assert "DROP_EXISTING=true opencrane index" in caplog.text

    def test_old_collection_uses_env(self, clean_env):
        clean_env.setenv("EMBEDDING_MODEL", "intfloat/e5-base-v2")
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", r"Instruct: x\nQuery: {query}")
        clean_env.setenv("EMBEDDING_DOCUMENT_PROMPT", "passage: ")
        settings = resolve_embedding_settings(None)
        assert (settings.model, settings.model_source) == ("intfloat/e5-base-v2", "env")
        assert settings.query_prompt == "Instruct: x\nQuery: {query}"
        assert settings.document_prompt == "passage: "

    def test_as_dict(self, clean_env):
        assert resolve_embedding_settings(_RECORDED).as_dict() == {
            "model": "intfloat/e5-base-v2",
            "model_source": "index",
            "query_prompt": "query: ",
            "query_prompt_source": "index",
        }


def test_warn_if_inconsistent_uses_given_prompts(clean_env, caplog):
    with caplog.at_level(logging.WARNING):
        warn_if_inconsistent(document_prompt="passage: ", query_prompt="query: ")
    assert caplog.text == ""
    with caplog.at_level(logging.WARNING):
        warn_if_inconsistent(document_prompt="passage: ", query_prompt="")
    assert "EMBEDDING_QUERY_PROMPT is empty" in caplog.text


# --- server ----------------------------------------------------------------


def _milvus_with(metadata):
    return Mock(embedding_metadata=Mock(return_value=metadata))


class TestServerSettings:
    def test_embeddings_service_uses_index_model(self, clean_env, monkeypatch):
        monkeypatch.setattr(server, "get_milvus_service", lambda: _milvus_with(_RECORDED))
        with patch.object(server, "EmbeddingService") as service_class:
            server.get_embeddings_service()
        service_class.assert_called_once_with(model_name="intfloat/e5-base-v2")
        assert server.get_embedding_settings().query_prompt == "query: "

    def test_settings_are_resolved_once(self, clean_env, monkeypatch):
        milvus = _milvus_with(_RECORDED)
        monkeypatch.setattr(server, "get_milvus_service", lambda: milvus)
        server.get_embedding_settings()
        server.get_embedding_settings()
        milvus.embedding_metadata.assert_called_once()

    def test_mismatch_blocks_the_embeddings_service(self, clean_env, monkeypatch):
        clean_env.setenv("EMBEDDING_MODEL", "other/model")
        monkeypatch.setattr(server, "get_milvus_service", lambda: _milvus_with(_RECORDED))
        with patch.object(server, "EmbeddingService") as service_class:
            with pytest.raises(EmbeddingSettingsMismatch):
                server.get_embeddings_service()
        service_class.assert_not_called()

    @pytest.mark.anyio
    async def test_search_applies_index_query_prompt(self, clean_env, monkeypatch):
        embeddings = Mock()
        embeddings.model.encode.return_value = [[0.1] * 768]
        monkeypatch.setattr(server, "_embedding_settings", resolve_embedding_settings(_RECORDED))
        with patch.object(server, "get_embeddings_service", return_value=embeddings), \
             patch.object(server, "get_milvus_service", return_value=Mock(search=Mock(return_value=[]))):
            await server._search_documentation_impl({"query": "what is AMF", "search_mode": "semantic"})
        embeddings.model.encode.assert_called_once_with(
            ["query: what is AMF"], batch_size=8, show_progress_bar=False
        )

    def test_check_logs_settings_in_use(self, clean_env, monkeypatch, caplog):
        monkeypatch.setattr(server, "get_milvus_service", lambda: _milvus_with(_RECORDED))
        with caplog.at_level(logging.INFO):
            server.check_embedding_settings()
        assert "'intfloat/e5-base-v2' (from index)" in caplog.text

    def test_check_raises_on_mismatch(self, clean_env, monkeypatch):
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "other: ")
        monkeypatch.setattr(server, "get_milvus_service", lambda: _milvus_with(_RECORDED))
        with pytest.raises(EmbeddingSettingsMismatch):
            server.check_embedding_settings()

    def test_check_defers_other_errors(self, clean_env, monkeypatch, caplog):
        def _unreachable():
            raise ConnectionError("milvus down")

        monkeypatch.setattr(server, "get_milvus_service", _unreachable)
        with caplog.at_level(logging.WARNING):
            server.check_embedding_settings()
        assert "milvus down" in caplog.text
        assert server._embedding_settings is None

    @pytest.mark.anyio
    async def test_stdio_main_refuses_to_start_on_mismatch(self, monkeypatch):
        def _mismatch():
            raise EmbeddingSettingsMismatch("EMBEDDING_MODEL is 'a' but the index was built with 'b'")

        monkeypatch.setattr(server, "check_embedding_settings", _mismatch)
        with patch.object(server, "stdio_server") as stdio:
            with pytest.raises(SystemExit):
                await server.main()
        stdio.assert_not_called()

    @patch("opencrane.mcp.server._query_probe")
    @patch("opencrane.mcp.server._memory_health")
    @patch("opencrane.mcp.server.get_milvus_service")
    @patch("opencrane.mcp.server.get_embeddings_service")
    @pytest.mark.anyio
    async def test_health_reports_model_and_source(
        self, mock_emb_get, mock_milv_get, mock_mem, mock_probe, clean_env, monkeypatch
    ):
        mock_milv_get.return_value = Mock(get_collection_stats=Mock(return_value={"row_count": 1}))
        mock_mem.return_value = {"status": "unavailable"}
        mock_probe.return_value = {"status": "healthy", "latency_ms": 1.0}
        monkeypatch.setattr(server, "_embedding_settings", resolve_embedding_settings(_RECORDED))
        payload = await server.compute_health()
        assert payload["checks"]["embedding"] == {
            "model": "intfloat/e5-base-v2",
            "model_source": "index",
            "query_prompt": "query: ",
            "query_prompt_source": "index",
        }


@pytest.mark.anyio
async def test_http_init_services_fails_on_mismatch(monkeypatch):
    monkeypatch.setattr(http_server, "_services_ready", False)
    with patch(
        "opencrane.mcp.server.get_embeddings_service",
        side_effect=EmbeddingSettingsMismatch("mismatch"),
    ):
        with pytest.raises(EmbeddingSettingsMismatch):
            await http_server.init_services()
    assert http_server._services_ready is False


# --- index step ------------------------------------------------------------

_CHUNKS = '[{"content": "test", "chunk_type": "prose", "source_file": "test.md", "token_count": 10, "line_start": 1, "metadata": {}}]'


def _embeddings(**overrides):
    fields = dict(
        model="intfloat/e5-base-v2",
        dimensions=768,
        created_at="2026-01-01T00:00:00+00:00",
        chunks_sha256="x",
        document_prompt="passage: ",
        query_prompt="query: ",
        embeddings=[EmbeddingRecord(chunk_index=0, chunk_id="c1", vector=[0.1] * 768)],
    )
    fields.update(overrides)
    return EmbeddingsFile(**fields)


def _populated_milvus(recorded):
    milvus = MagicMock()
    milvus.client.has_collection.return_value = True
    milvus.field_names.return_value = set(_REQUIRED_FIELDS)
    milvus.get_collection_stats.return_value = {"row_count": 65}
    milvus.vector_dim.return_value = 768
    milvus.embedding_metadata.return_value = recorded
    return milvus


def _run_index(milvus, embeddings):
    with patch("opencrane.mcp.init_vector_db.setup_logging"), \
         patch("opencrane.mcp.init_vector_db.MilvusService", return_value=milvus), \
         patch("opencrane.mcp.init_vector_db.EmbeddingService") as emb_class, \
         patch("builtins.open", new_callable=mock_open, read_data=_CHUNKS), \
         patch("opencrane.mcp.init_vector_db.Path") as path:
        path.return_value.exists.return_value = True
        emb_class.return_value.load_embeddings.return_value = embeddings
        init_main()


class TestIndexRecordsSettings:
    def test_metadata_from_embeddings(self):
        assert _embedding_metadata(_embeddings(), 768) == _RECORDED

    def test_metadata_records_old_rule_for_embeddings_file_without_query_prompt(self, clean_env):
        data = _embeddings().model_dump()
        del data["query_prompt"]
        metadata = _embedding_metadata(EmbeddingsFile(**data), 768)
        # The old serving rule: EMBEDDING_QUERY_PROMPT, else no prompt.
        assert metadata["query_prompt"] == ""

    def test_new_collection_records_settings(self):
        milvus = MagicMock()
        milvus.client.has_collection.return_value = False
        _run_index(milvus, _embeddings())
        milvus.create_collection.assert_called_once_with(dim=768, embedding_metadata=_RECORDED)

    def test_same_settings_keep_collection(self):
        milvus = _populated_milvus(dict(_RECORDED))
        _run_index(milvus, _embeddings())
        milvus.client.drop_collection.assert_not_called()
        milvus.create_collection.assert_not_called()

    @pytest.mark.parametrize("change", [
        {"model": "other/model"},
        {"document_prompt": ""},
        {"query_prompt": "search_query: "},
    ])
    def test_changed_settings_rebuild_collection(self, change):
        milvus = _populated_milvus(dict(_RECORDED))
        _run_index(milvus, _embeddings(**change))
        milvus.client.drop_collection.assert_called_once()
        milvus.create_collection.assert_called_once()
        assert milvus.create_collection.call_args.kwargs["embedding_metadata"] == {**_RECORDED, **change}

    def test_missing_metadata_keeps_collection_and_warns(self, caplog):
        milvus = _populated_milvus(None)
        with caplog.at_level(logging.WARNING):
            _run_index(milvus, _embeddings())
        milvus.client.drop_collection.assert_not_called()
        assert "DROP_EXISTING=true opencrane index" in caplog.text

    def test_empty_embeddings_never_rebuild_on_changed_settings(self):
        milvus = _populated_milvus(dict(_RECORDED))
        with patch("opencrane.mcp.init_vector_db.json.load", return_value=[]):
            _run_index(milvus, _embeddings(model="other/model", embeddings=[]))
        milvus.client.drop_collection.assert_not_called()


# --- embed step ------------------------------------------------------------


class TestEmbedRecordsQueryPrompt:
    def test_generated_file_records_query_prompt(self, clean_env):
        clean_env.setenv("AI_DOCS_EMBEDDINGS_BACKEND", "mock")
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "query: ")
        from opencrane.mcp.services.embeddings import EmbeddingService

        result = EmbeddingService().generate_embeddings(
            [{"chunk_id": "c1", "content": "x", "source_file": "a.md", "chunk_type": "prose"}]
        )
        assert result.query_prompt == "query: "

    def test_sync_writes_changed_query_prompt(self, clean_env, tmp_path):
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "query: ")
        path = tmp_path / "embeddings.json"
        path.write_text(json.dumps({"model": "m", "embeddings": []}))
        _sync_query_prompt(path)
        assert json.loads(path.read_text()) == {"model": "m", "embeddings": [], "query_prompt": "query: "}

    def test_sync_leaves_matching_file_untouched(self, clean_env, tmp_path):
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "query: ")
        path = tmp_path / "embeddings.json"
        original = json.dumps({"query_prompt": "query: "})
        path.write_text(original)
        _sync_query_prompt(path)
        assert path.read_text() == original

    def test_sync_warns_on_unreadable_file(self, clean_env, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            _sync_query_prompt(tmp_path / "missing.json")
        assert "Could not record the query prompt" in caplog.text


# --- #95 prompt resolution -------------------------------------------------


class TestModelPromptFallback:
    def test_loaded_model_prompts_replace_defaults(self, clean_env):
        clean_env.setenv("EMBEDDING_MODEL", "acme/no-table-entry")
        settings = resolve_embedding_settings({})
        assert (settings.query_prompt, settings.document_prompt) == ("", "")
        model = Mock(prompts={"query": "Instruct: find\nQuery: ", "document": "doc: "})
        updated = with_model_prompts(settings, model)
        assert updated.query_prompt == "Instruct: find\nQuery: "
        assert updated.document_prompt == "doc: "
        assert updated.query_prompt_source == "default"

    def test_index_and_env_values_are_kept(self, clean_env):
        settings = resolve_embedding_settings(_RECORDED)
        assert with_model_prompts(settings, Mock(prompts={"query": "other: "})) is settings

    def test_explicit_empty_query_prompt_without_index_value(self, clean_env):
        clean_env.setenv("EMBEDDING_QUERY_PROMPT", "")
        settings = resolve_embedding_settings(None)
        assert (settings.query_prompt, settings.query_prompt_source) == ("", "env")

    def test_embed_records_the_effective_query_prompt(self, clean_env):
        clean_env.setenv("AI_DOCS_EMBEDDINGS_BACKEND", "mock")
        clean_env.setenv("EMBEDDING_MODEL", "intfloat/e5-base-v2")
        from opencrane.mcp.services.embeddings import EmbeddingService

        result = EmbeddingService().generate_embeddings(
            [{"chunk_id": "c1", "content": "x", "source_file": "a.md", "chunk_type": "prose"}]
        )
        assert (result.document_prompt, result.query_prompt) == ("passage: ", "query: ")

    def test_sync_resolves_the_prompt_for_the_file_model(self, clean_env, tmp_path):
        path = tmp_path / "embeddings.json"
        path.write_text(json.dumps({"model": "intfloat/e5-base-v2"}))
        _sync_query_prompt(path)
        assert json.loads(path.read_text())["query_prompt"] == "query: "
