"""Unit tests for the FastMCP-based HTTP MCP server transport (fully mocked)."""

import json
import pytest
from unittest.mock import Mock, patch, AsyncMock

from starlette.testclient import TestClient
from mcp.types import TextContent

import opencrane.mcp.http_server as http_server
from opencrane.mcp.http_server import (
    init_services,
    build_app,
    lifespan,
    main,
    app,
    health_handler,
)
from opencrane.mcp import server as s


def _body(response):
    """Decode a Starlette JSONResponse body to a dict."""
    return json.loads(response.body)


@pytest.fixture(autouse=True)
def reset_module_globals():
    """Reset module-level state before and after each test for isolation."""
    http_server._services_ready = False
    http_server._milvus_stats = None
    yield
    http_server._services_ready = False
    http_server._milvus_stats = None


class TestInitServices:
    @pytest.mark.anyio
    async def test_init_services_success(self):
        """init_services loads embeddings, connects Milvus, marks ready."""
        mock_milvus = Mock()
        mock_milvus.get_collection_stats.return_value = {"row_count": 42}

        with patch("opencrane.mcp.server.get_embeddings_service") as mock_embed, \
                patch("opencrane.mcp.server.get_milvus_service", return_value=mock_milvus) as mock_get_milvus:
            await init_services()

        mock_embed.assert_called_once()
        mock_get_milvus.assert_called_once()
        assert http_server._services_ready is True
        assert http_server._milvus_stats == {"row_count": 42}

    @pytest.mark.anyio
    async def test_init_services_failure(self):
        """init_services swallows errors and leaves services not ready."""
        with patch("opencrane.mcp.server.get_embeddings_service", side_effect=RuntimeError("boom")):
            await init_services()

        assert http_server._services_ready is False


class TestLifespan:
    @pytest.mark.anyio
    async def test_lifespan_runs_init_services(self):
        """The FastMCP lifespan invokes init_services on startup."""
        mcp = build_app()
        with patch("opencrane.mcp.http_server.init_services", new=AsyncMock()) as mock_init:
            async with lifespan(mcp):
                pass
        mock_init.assert_awaited_once()


class TestRegisteredTools:
    """The bridge registers the existing server.py handlers with their schemas."""

    @pytest.mark.anyio
    async def test_base_tools_always_advertised(self):
        with patch.object(s, "_has_yaml_chunks", return_value=False), \
                patch.object(s, "_has_list_item_chunks", return_value=False):
            mcp = build_app()
            tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert names == {"search_docs", "health"}

    @pytest.mark.anyio
    async def test_search_docs_schema_matches_source_of_truth(self):
        """search_docs advertises exactly server._build_search_tool().inputSchema."""
        with patch.object(s, "_has_yaml_chunks", return_value=False), \
                patch.object(s, "_has_list_item_chunks", return_value=False):
            mcp = build_app()
            tools = await mcp.list_tools()
        search = next(t for t in tools if t.name == "search_docs")
        assert search.inputSchema == s._build_search_tool().inputSchema
        assert search.description == s._build_search_tool().description

    @pytest.mark.anyio
    async def test_list_members_tool_appears_when_predicate_true(self):
        with patch.object(s, "_has_yaml_chunks", return_value=False), \
                patch.object(s, "_has_list_item_chunks", return_value=True):
            mcp = build_app()
            tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert "get_list_members" in names
        # get_metadata_schema also gated on list-item OR yaml
        assert "get_metadata_schema" in names
        assert "get_yaml_definition" not in names
        gm = next(t for t in tools if t.name == "get_list_members")
        assert gm.inputSchema == s.GET_LIST_MEMBERS_TOOL_SCHEMA
        assert gm.description == s.GET_LIST_MEMBERS_TOOL_DESCRIPTION

    @pytest.mark.anyio
    async def test_yaml_tools_appear_when_predicate_true(self):
        with patch.object(s, "_has_yaml_chunks", return_value=True), \
                patch.object(s, "_has_list_item_chunks", return_value=False):
            mcp = build_app()
            tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert "get_yaml_definition" in names
        assert "get_metadata_schema" in names
        assert "get_list_members" not in names
        gy = next(t for t in tools if t.name == "get_yaml_definition")
        assert gy.inputSchema == s.GET_YAML_DEFINITION_TOOL_SCHEMA
        assert gy.description == s.GET_YAML_DEFINITION_TOOL_DESCRIPTION
        gm = next(t for t in tools if t.name == "get_metadata_schema")
        assert gm.inputSchema == s.GET_METADATA_SCHEMA_TOOL_SCHEMA
        assert gm.description == s.GET_METADATA_SCHEMA_TOOL_DESCRIPTION

    @pytest.mark.anyio
    async def test_call_tool_search_docs_reaches_handler(self):
        """call_tool bridges arguments dict to the existing handler and returns list[TextContent]."""
        fake_embeddings = Mock()
        encoded = Mock()
        encoded.tolist.return_value = [[0.1, 0.2]]
        fake_embeddings.model.encode.return_value = encoded

        fake_milvus = Mock()
        fake_milvus.search.return_value = [
            {
                "content": "hello world",
                "source_file": "docs/x.md",
                "chunk_type": "prose",
                "chunk_id": "abc",
                "metadata_json": "{}",
                "distance": 0.9,
                "source_name": "topic",
            }
        ]

        with patch.object(s, "_has_yaml_chunks", return_value=False), \
                patch.object(s, "_has_list_item_chunks", return_value=False), \
                patch.object(s, "_get_indexed_chunk_types", return_value=set()), \
                patch.object(s, "get_embeddings_service", return_value=fake_embeddings), \
                patch.object(s, "get_milvus_service", return_value=fake_milvus):
            mcp = build_app()
            result = await mcp.call_tool(
                "search_docs", {"query": "hi", "search_mode": "semantic"}
            )

        assert isinstance(result, list)
        assert all(isinstance(c, TextContent) for c in result)
        assert "hello world" in result[0].text


class TestAdvertisedSourceKeys:
    """Per-endpoint scoping of the advertised search topics / source_names enum."""

    def test_open_endpoint_with_default_sources_scopes(self):
        from opencrane.mcp.auth.config_model import AuthConfig
        with patch.object(s, "_get_source_keys", return_value=["a", "b", "c"]):
            keys = http_server._advertised_source_keys(
                AuthConfig(type="none", default_sources=("a", "c")))
        assert keys == ["a", "c"]

    def test_open_endpoint_without_default_sources_returns_none(self):
        from opencrane.mcp.auth.config_model import AuthConfig
        assert http_server._advertised_source_keys(AuthConfig(type="none")) is None

    def test_authenticated_endpoint_returns_none(self):
        """An authenticated endpoint advertises all sources (per-caller scope is dynamic)."""
        from opencrane.mcp.auth.config_model import AuthConfig
        cfg = AuthConfig(type="oauth", default_sources=("a",))
        assert http_server._advertised_source_keys(cfg) is None


class TestPerEndpointToolScoping:
    @pytest.mark.anyio
    async def test_build_mcp_scopes_open_endpoint_search_tool(self):
        """A type:none + default_sources endpoint advertises only those topics —
        a private source is neither in the enum nor the description."""
        from opencrane.mcp.auth.config_model import AuthConfig
        with patch.object(s, "_get_source_keys",
                          return_value=["public-a", "public-b", "private-x"]), \
                patch.object(s, "_get_source_topics",
                             return_value=["public a", "public b", "private x"]), \
                patch.object(s, "_get_indexed_chunk_types", return_value=set()), \
                patch.object(s, "_has_yaml_chunks", return_value=False), \
                patch.object(s, "_has_list_item_chunks", return_value=False):
            mcp, _ = http_server._build_mcp(
                AuthConfig(type="none", default_sources=("public-a", "public-b")),
                "/mcp/public", http_server._noop_lifespan)
            tools = await mcp.list_tools()
        search = next(t for t in tools if t.name == "search_docs")
        enum = search.inputSchema["properties"]["source_names"]["items"]["enum"]
        assert enum == ["public-a", "public-b"]
        assert "private-x" not in enum
        assert "private x" not in search.description


class TestTransportSecurity:
    def test_disabled_by_default(self, monkeypatch):
        """Without MCP_ALLOWED_HOSTS the DNS-rebinding host check is off, so a
        server behind a real hostname/proxy does not 421 (the SDK would otherwise
        auto-enable a localhost-only allow-list)."""
        monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)
        settings = http_server._transport_security()
        assert settings.enable_dns_rebinding_protection is False

    def test_allowed_hosts_opt_in(self, monkeypatch):
        """MCP_ALLOWED_HOSTS re-enables protection with the given hosts and
        derives matching http/https origins."""
        monkeypatch.setenv("MCP_ALLOWED_HOSTS", "mcp.cennso.com, example.com:8000")
        settings = http_server._transport_security()
        assert settings.enable_dns_rebinding_protection is True
        assert settings.allowed_hosts == ["mcp.cennso.com", "example.com:8000"]
        assert "https://mcp.cennso.com" in settings.allowed_origins
        assert "http://example.com:8000" in settings.allowed_origins


class TestHealthEndpoint:
    @pytest.mark.anyio
    async def test_health_ready_delegates_to_compute_health(self):
        """When services are ready, the honest compute_health payload is returned."""
        http_server._services_ready = True
        payload = {"status": "healthy", "checks": {"query_probe": {"status": "healthy"}}}
        with patch("opencrane.mcp.server.compute_health", new=AsyncMock(return_value=payload)):
            response = await health_handler(Mock())
        assert response.status_code == 200
        assert _body(response) == payload

    @pytest.mark.anyio
    async def test_health_degraded_still_returns_200(self):
        """A degraded instance is still serving, so the probe stays 200."""
        http_server._services_ready = True
        payload = {"status": "degraded", "checks": {}}
        with patch("opencrane.mcp.server.compute_health", new=AsyncMock(return_value=payload)):
            response = await health_handler(Mock())
        assert response.status_code == 200
        assert _body(response)["status"] == "degraded"

    @pytest.mark.anyio
    async def test_health_unhealthy_returns_503(self):
        """An unhealthy instance cannot serve queries, so the probe fails."""
        http_server._services_ready = True
        payload = {"status": "unhealthy", "checks": {}}
        with patch("opencrane.mcp.server.compute_health", new=AsyncMock(return_value=payload)):
            response = await health_handler(Mock())
        assert response.status_code == 503
        assert _body(response)["status"] == "unhealthy"

    def test_health_initializing(self):
        http_server._services_ready = False
        client = TestClient(build_app().streamable_http_app())
        resp = client.get("/health")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "initializing"
        assert data["services"] == "loading"


class TestMain:
    @pytest.mark.anyio
    async def test_main_uses_env_and_serves(self):
        mock_server = Mock()
        mock_server.serve = AsyncMock()
        mock_config = Mock()
        mock_uvicorn = Mock()
        mock_uvicorn.Config.return_value = mock_config
        mock_uvicorn.Server.return_value = mock_server

        env = {"MCP_HTTP_PORT": "1234", "MCP_HTTP_HOST": "127.0.0.1"}
        with patch.dict("sys.modules", {"uvicorn": mock_uvicorn}), \
                patch.dict("os.environ", env, clear=False):
            await main()

        mock_uvicorn.Config.assert_called_once_with(
            app, host="127.0.0.1", port=1234
        )
        mock_uvicorn.Server.assert_called_once_with(mock_config)
        mock_server.serve.assert_awaited_once()

    @pytest.mark.anyio
    async def test_main_defaults_when_env_absent(self):
        mock_server = Mock()
        mock_server.serve = AsyncMock()
        mock_uvicorn = Mock()
        mock_uvicorn.Config.return_value = Mock()
        mock_uvicorn.Server.return_value = mock_server

        env = {}
        with patch.dict("sys.modules", {"uvicorn": mock_uvicorn}), \
                patch.dict("os.environ", env, clear=True):
            await main()

        mock_uvicorn.Config.assert_called_once_with(
            app, host="0.0.0.0", port=8000
        )

    @pytest.mark.anyio
    async def test_main_logs_each_named_endpoint(self, tmp_path, monkeypatch, caplog):
        """With a named auth map, main() logs one MCP endpoint line per name."""
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "auth:\n  public:\n    type: none\n  private:\n    type: none\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MAPPING_FILE", str(cfg))

        mock_server = Mock()
        mock_server.serve = AsyncMock()
        mock_uvicorn = Mock()
        mock_uvicorn.Config.return_value = Mock()
        mock_uvicorn.Server.return_value = mock_server

        with patch.dict("sys.modules", {"uvicorn": mock_uvicorn}), \
                caplog.at_level("INFO", logger="opencrane.mcp.http_server"):
            await main()

        logged = " ".join(caplog.messages)
        assert "/mcp/public" in logged
        assert "/mcp/private" in logged
