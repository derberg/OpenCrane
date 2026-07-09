"""Unit tests for the generic ASGI middleware hook applied in build_asgi_app()."""

import pytest

import opencrane.mcp.http_server as http_server


@pytest.fixture(autouse=True)
def reset_module_globals():
    http_server._services_ready = False
    http_server._milvus_stats = None
    yield
    http_server._services_ready = False
    http_server._milvus_stats = None


class _Marker:
    """Minimal ASGI middleware that records the app it wraps."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):  # pragma: no cover - not driven here
        await self.app(scope, receive, send)


class _Outer(_Marker):
    pass


class _Inner(_Marker):
    pass


class _FakeConfig:
    def __init__(self, middleware):
        self.middleware = middleware


def _none_mode(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("auth:\n  type: none\n", encoding="utf-8")
    monkeypatch.setenv("MAPPING_FILE", str(cfg))


class TestMiddlewareHook:
    def test_middleware_applied_outermost_in_order(self, tmp_path, monkeypatch):
        """First entry in oc.middleware becomes the outermost wrapper."""
        _none_mode(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "opencrane.cli.load_config",
            lambda _arg: _FakeConfig([_Outer, _Inner]),
        )
        app = http_server.build_asgi_app()
        assert isinstance(app, _Outer)
        assert isinstance(app.app, _Inner)

    def test_empty_middleware_is_noop(self, tmp_path, monkeypatch):
        """An empty middleware list leaves the app unwrapped."""
        _none_mode(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "opencrane.cli.load_config",
            lambda _arg: _FakeConfig([]),
        )
        app = http_server.build_asgi_app()
        assert not isinstance(app, _Marker)

    def test_config_load_failure_does_not_break_default_path(self, tmp_path, monkeypatch):
        """A config-load failure is swallowed; the app is returned unwrapped."""
        _none_mode(tmp_path, monkeypatch)

        def _boom(_arg):
            raise RuntimeError("bad extensions module")

        monkeypatch.setattr("opencrane.cli.load_config", _boom)
        app = http_server.build_asgi_app()
        assert not isinstance(app, _Marker)
