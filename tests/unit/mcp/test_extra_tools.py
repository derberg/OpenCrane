"""Unit tests for the ``OpenCraneConfig.extra_tools`` extension point."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolRequest, CallToolRequestParams, ImageContent, TextContent

from opencrane import ExtraTool, OpenCraneConfig, ToolContext
from opencrane.mcp import extra_tools as et
from opencrane.mcp import server as s
from opencrane.mcp.http_server import build_app

SCHEMA = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}


def _echo(arguments, context):
    return f"echo {arguments['x']}"


def _tool(name="echo", handler=_echo, schema=SCHEMA):
    return ExtraTool(name=name, description=f"{name} tool", input_schema=schema, handler=handler)


class _Cfg(OpenCraneConfig):
    def __init__(self, tools):
        self.extra_tools = tools


@pytest.fixture(autouse=True)
def reset_extra_tools():
    s._extra_tools = {}
    yield
    s._extra_tools = {}


# --- validation ---------------------------------------------------------------


class TestValidate:
    def test_valid_tools_keyed_by_name(self):
        a, b = _tool("a"), _tool("b")
        assert et.validate_extra_tools([a, b], {"search_docs"}) == {"a": a, "b": b}

    def test_builtin_collision_raises(self):
        with pytest.raises(ValueError, match="collides with a built-in"):
            et.validate_extra_tools([_tool("search_docs")], s.BUILTIN_TOOL_NAMES)

    def test_duplicate_raises(self):
        with pytest.raises(ValueError, match="more than once"):
            et.validate_extra_tools([_tool("a"), _tool("a")], set())

    def test_non_extratool_entry_raises(self):
        with pytest.raises(ValueError, match="ExtraTool instances"):
            et.validate_extra_tools([{"name": "a"}], set())

    @pytest.mark.parametrize("name", ["", None])
    def test_bad_name_raises(self, name):
        with pytest.raises(ValueError, match="non-empty string"):
            et.validate_extra_tools([_tool(name)], set())

    @pytest.mark.parametrize("schema", [None, {"type": "string"}, {}])
    def test_bad_schema_raises(self, schema):
        with pytest.raises(ValueError, match="input_schema"):
            et.validate_extra_tools([_tool(schema=schema)], set())

    def test_non_callable_handler_raises(self):
        with pytest.raises(ValueError, match="callable"):
            et.validate_extra_tools([_tool(handler="nope")], set())


# --- loading from config --------------------------------------------------------


class TestLoad:
    def test_default_config_has_no_extra_tools(self):
        assert OpenCraneConfig.extra_tools == []
        with patch("opencrane.cli.load_config", return_value=OpenCraneConfig()):
            assert et.load_extra_tools(s.BUILTIN_TOOL_NAMES) == ({}, None)

    def test_config_without_attribute_is_empty(self):
        with patch("opencrane.cli.load_config", return_value=object()):
            assert et.load_extra_tools(set()) == ({}, None)

    def test_config_load_failure_is_skipped(self):
        with patch("opencrane.cli.load_config", side_effect=RuntimeError("bad module")):
            assert et.load_extra_tools(set()) == ({}, None)

    def test_tools_loaded_with_context(self):
        cfg = _Cfg([_tool()])
        with patch("opencrane.cli.load_config", return_value=cfg):
            tools, context = et.load_extra_tools(set())
        assert list(tools) == ["echo"]
        assert isinstance(context, ToolContext)
        assert context.config is cfg

    def test_collision_propagates(self):
        with patch("opencrane.cli.load_config", return_value=_Cfg([_tool("health")])):
            with pytest.raises(ValueError, match="health"):
                et.load_extra_tools(s.BUILTIN_TOOL_NAMES)


# --- context ----------------------------------------------------------------------


class TestToolContext:
    def test_services_resolved_lazily_from_server(self):
        ctx = ToolContext(config="cfg")
        with patch.object(s, "get_milvus_service", return_value="M") as gm, \
                patch.object(s, "get_embeddings_service", return_value="E"), \
                patch.object(s, "get_keyword_service", return_value="K"):
            gm.assert_not_called()
            assert (ctx.milvus, ctx.embeddings, ctx.keyword_search) == ("M", "E", "K")
        assert ctx.config == "cfg"

    def test_allowed_sources(self):
        from opencrane.mcp.auth import runtime

        token = runtime._allowed_sources.set(("a",))
        try:
            assert ToolContext(None).allowed_sources() == ("a",)
        finally:
            runtime._allowed_sources.reset(token)


# --- handler binding and result normalisation -----------------------------------------


class TestBindHandler:
    @pytest.mark.anyio
    async def test_sync_handler(self):
        seen = {}

        def handler(arguments, context):
            seen["context"] = context
            return "ok"

        ctx = ToolContext(None)
        result = await et.bind_handler(_tool(handler=handler), ctx)({"x": "1"})
        assert result == [TextContent(type="text", text="ok")]
        assert seen["context"] is ctx

    @pytest.mark.anyio
    async def test_async_function_handler(self):
        async def handler(arguments, context):
            return {"got": arguments}

        result = await et.bind_handler(_tool(handler=handler), None)(None)
        assert result[0].text == '{"got": {}}'

    @pytest.mark.anyio
    async def test_async_callable_object_handler(self):
        class Handler:
            async def __call__(self, arguments, context):
                return [TextContent(type="text", text="a"), TextContent(type="text", text="b")]

        result = await et.bind_handler(_tool(handler=Handler()), None)({})
        assert [c.text for c in result] == ["a", "b"]

    @pytest.mark.anyio
    async def test_exception_is_reraised(self):
        def handler(arguments, context):
            raise KeyError("missing")

        with pytest.raises(KeyError):
            await et.bind_handler(_tool(handler=handler), None)({})

    def test_to_content_variants(self):
        image = ImageContent(type="image", data="AAAA", mimeType="image/png")
        assert et._to_content(image) == [image]
        assert et._to_content([]) == [TextContent(type="text", text="[]")]
        assert et._to_content(None) == [TextContent(type="text", text="null")]
        assert et._to_content([1, "ü"]) == [TextContent(type="text", text='[1, "ü"]')]


# --- stdio transport ----------------------------------------------------------------


class TestStdio:
    @pytest.mark.anyio
    async def test_builtin_names_match_full_tool_set(self):
        """Guard: BUILTIN_TOOL_NAMES lists every tool list_tools can advertise."""
        with patch.object(s, "_has_yaml_chunks", return_value=True), \
                patch.object(s, "_has_list_item_chunks", return_value=True), \
                patch.object(s, "_has_table_row_chunks", return_value=True), \
                patch.object(s, "_has_prose_navigation", return_value=True), \
                patch.object(s, "_get_indexed_chunk_types", return_value=set()), \
                patch.object(s, "_get_source_topics", return_value=[]):
            names = {t.name for t in await s.list_tools()}
        assert names == s.BUILTIN_TOOL_NAMES

    @pytest.mark.anyio
    async def test_list_and_call_extra_tool(self):
        with patch("opencrane.cli.load_config", return_value=_Cfg([_tool()])):
            s._extra_tools = s.load_extra_tools()
        with patch.object(s, "_get_indexed_chunk_types", return_value=set()), \
                patch.object(s, "_get_source_topics", return_value=[]):
            tools = await s.list_tools()
        echo = next(t for t in tools if t.name == "echo")
        assert echo.inputSchema == SCHEMA
        assert echo.description == "echo tool"
        assert await s.call_tool("echo", {"x": "hi"}) == [TextContent(type="text", text="echo hi")]

    @pytest.mark.anyio
    async def test_builtin_dispatch_unaffected(self):
        with patch("opencrane.cli.load_config", return_value=_Cfg([_tool()])):
            s._extra_tools = s.load_extra_tools()
        with patch.object(s, "health_check", new=AsyncMock(return_value=["h"])):
            assert await s.call_tool("health", {}) == ["h"]
        with pytest.raises(ValueError, match="Unknown tool"):
            await s.call_tool("nope", {})

    @pytest.mark.anyio
    async def test_handler_exception_becomes_mcp_error(self):
        """Through the MCP request handler, a failing extra tool yields isError."""
        def boom(arguments, context):
            raise RuntimeError("clause not found")

        with patch("opencrane.cli.load_config", return_value=_Cfg([_tool(handler=boom)])):
            s._extra_tools = s.load_extra_tools()
        req = CallToolRequest(method="tools/call",
                              params=CallToolRequestParams(name="echo", arguments={"x": "1"}))
        with patch.object(s, "_get_indexed_chunk_types", return_value=set()), \
                patch.object(s, "_get_source_topics", return_value=[]):
            result = await s.app.request_handlers[CallToolRequest](req)
        assert result.root.isError is True
        assert "clause not found" in result.root.content[0].text

    @pytest.mark.anyio
    async def test_main_loads_extra_tools(self):
        cm = Mock()
        cm.__aenter__ = AsyncMock(return_value=(Mock(), Mock()))
        cm.__aexit__ = AsyncMock(return_value=None)
        with patch("opencrane.cli.load_config", return_value=_Cfg([_tool()])), \
                patch.object(s, "stdio_server", return_value=cm), \
                patch.object(s, "app") as app:
            app.run = AsyncMock()
            await s.main()
        assert list(s._extra_tools) == ["echo"]

    @pytest.mark.anyio
    async def test_main_fails_on_collision(self):
        with patch("opencrane.cli.load_config", return_value=_Cfg([_tool("search_docs")])):
            with pytest.raises(ValueError, match="collides"):
                await s.main()


# --- HTTP transport -----------------------------------------------------------------


class TestHttp:
    @pytest.mark.anyio
    async def test_extra_tool_registered_and_callable(self):
        with patch("opencrane.cli.load_config", return_value=_Cfg([_tool()])), \
                patch.object(s, "_get_indexed_chunk_types", return_value=set()):
            mcp = build_app()
        tools = await mcp.list_tools()
        echo = next(t for t in tools if t.name == "echo")
        assert echo.inputSchema == SCHEMA
        result = await mcp.call_tool("echo", {"x": "hi"})
        assert result == [TextContent(type="text", text="echo hi")]

    @pytest.mark.anyio
    async def test_handler_exception_becomes_tool_error(self):
        async def boom(arguments, context):
            raise RuntimeError("clause not found")

        with patch("opencrane.cli.load_config", return_value=_Cfg([_tool(handler=boom)])), \
                patch.object(s, "_get_indexed_chunk_types", return_value=set()):
            mcp = build_app()
        with pytest.raises(ToolError, match="clause not found"):
            await mcp.call_tool("echo", {"x": "1"})

    def test_collision_fails_at_build(self):
        with patch("opencrane.cli.load_config", return_value=_Cfg([_tool("get_table_members")])), \
                patch.object(s, "_get_indexed_chunk_types", return_value=set()):
            with pytest.raises(ValueError, match="collides"):
                build_app()


# --- review follow-ups ---------------------------------------------------------------


class TestReviewFollowUps:
    def test_allowed_sources_applies_scope_sources_policy(self, tmp_path, monkeypatch):
        """Without a middleware override, allowed_sources() reflects the endpoint's
        scope_sources policy, exactly as built-in search does."""
        from opencrane.mcp.auth import reset_auth_runtime
        from opencrane.mcp.auth.runtime import set_optional_scopes

        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            "sources:\n"
            "  cgw:\n    url: https://github.com/org/cgw\n"
            "  other:\n    url: https://github.com/org/other\n"
            "auth:\n  scope_sources:\n    docs:tp:\n      - cgw\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MAPPING_FILE", str(config_yaml))
        reset_auth_runtime()
        try:
            set_optional_scopes(("docs:tp",))
            assert ToolContext(None).allowed_sources() == ("cgw",)
            set_optional_scopes(())
            assert ToolContext(None).allowed_sources() == ()
        finally:
            reset_auth_runtime()

    def test_service_getters_create_one_instance_across_threads(self, monkeypatch):
        """Sync handlers run in worker threads; concurrent first use must not build
        a second MilvusService."""
        import threading
        import time

        created = []

        class SlowMilvus:
            def __init__(self):
                time.sleep(0.05)
                created.append(self)

        monkeypatch.setattr(s, "MilvusService", SlowMilvus)
        monkeypatch.setattr(s, "_milvus_service", None)
        barrier = threading.Barrier(4)
        results = []

        def worker():
            barrier.wait()
            results.append(s.get_milvus_service())

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(created) == 1
        assert all(r is created[0] for r in results)

    @pytest.mark.anyio
    async def test_sync_handler_returning_coroutine_is_awaited(self):
        async def fetch(arguments, context):
            return f"async {arguments['x']}"

        handler = lambda arguments, context: fetch(arguments, context)  # noqa: E731
        result = await et.bind_handler(_tool(handler=handler), None)({"x": "1"})
        assert result == [TextContent(type="text", text="async 1")]
