"""Auth misconfiguration stops the HTTP server instead of serving unprotected.

Covers each fail-closed case, the configs that ask for no protection and must
still start, and the startup warning for anonymous endpoints that serve every
source.
"""

import logging

import pytest

import opencrane.mcp.http_server as http_server
from opencrane.config import OpenCraneConfig
from opencrane.mcp.auth.config_model import AuthConfigError, load_mapping_data

_LOGGER = "opencrane.mcp.http_server"


@pytest.fixture(autouse=True)
def reset_module_globals(monkeypatch):
    monkeypatch.delenv("OPENCRANE_CONFIG", raising=False)
    http_server._services_ready = False
    http_server._milvus_stats = None
    yield
    http_server._services_ready = False
    http_server._milvus_stats = None


def _config(tmp_path, monkeypatch, text):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(text, encoding="utf-8")
    monkeypatch.setenv("MAPPING_FILE", str(cfg))
    return cfg


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING and r.name == _LOGGER]


class TestFailClosed:
    def test_unparseable_config_stops_the_server(self, tmp_path, monkeypatch):
        """An unparseable config.yaml no longer falls back to auth: none."""
        _config(tmp_path, monkeypatch, "auth:\n  type: oauth\n  oidc: [unclosed\n")
        with pytest.raises(AuthConfigError, match="cannot parse .*config.yaml"):
            http_server.build_asgi_app()

    def test_custom_without_hook_stops_the_server(self, tmp_path, monkeypatch):
        """A custom endpoint with no hook no longer runs unauthenticated."""
        _config(tmp_path, monkeypatch, "auth:\n  type: custom\n")
        monkeypatch.setattr("opencrane.cli.load_config", lambda _arg: OpenCraneConfig())
        with pytest.raises(AuthConfigError, match="would run unauthenticated"):
            http_server.build_asgi_app()

    def test_middleware_load_failure_stops_the_server(self, tmp_path, monkeypatch):
        """A Config class that fails to load no longer starts without its middleware."""
        _config(tmp_path, monkeypatch, "auth:\n  type: none\n")

        def _boom(_arg):
            raise RuntimeError("bad extensions module")

        monkeypatch.setattr("opencrane.cli.load_config", _boom)
        with pytest.raises(AuthConfigError, match="cannot load the project Config class"):
            http_server.build_asgi_app()

    def test_missing_extensions_file_from_config_yaml_stops_the_server(self, tmp_path, monkeypatch):
        """config.yaml names an extensions file that does not exist."""
        (tmp_path / ".opencrane").mkdir()
        (tmp_path / ".opencrane" / "config.yaml").write_text(
            "extensions: extensions.py\n", encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        _config(tmp_path, monkeypatch, "auth:\n  type: none\n")
        with pytest.raises(AuthConfigError, match="extensions file .*extensions.py does not exist"):
            http_server.build_asgi_app()

    def test_unparseable_project_config_with_other_mapping_file_stops_the_server(
        self, tmp_path, monkeypatch
    ):
        """MAPPING_FILE is valid, but the .opencrane/config.yaml that holds the
        extensions key is not, so its middleware would be dropped without a word."""
        (tmp_path / ".opencrane").mkdir()
        (tmp_path / ".opencrane" / "config.yaml").write_text(
            "extensions: extensions.py\nsources: [\n", encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        _config(tmp_path, monkeypatch, "auth:\n  type: none\n")
        with pytest.raises(AuthConfigError, match=r"cannot parse \.opencrane/config\.yaml"):
            http_server.build_asgi_app()

    def test_missing_config_path_stops_the_server(self, tmp_path, monkeypatch):
        """--config / OPENCRANE_CONFIG names a file that does not exist."""
        _config(tmp_path, monkeypatch, "auth:\n  type: none\n")
        monkeypatch.setenv("OPENCRANE_CONFIG", str(tmp_path / "missing.py"))
        with pytest.raises(AuthConfigError, match="missing.py does not exist"):
            http_server.build_asgi_app()


class TestStillStarts:
    def test_auth_none_starts_without_warning(self, tmp_path, monkeypatch, caplog):
        _config(tmp_path, monkeypatch, "auth:\n  type: none\n")
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            assert http_server.build_asgi_app() is not None
        assert _warnings(caplog) == []

    def test_no_auth_block_starts_without_warning(self, tmp_path, monkeypatch, caplog):
        _config(tmp_path, monkeypatch, "sources: {}\n")
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            assert http_server.build_asgi_app() is not None
        assert _warnings(caplog) == []

    def test_missing_config_yaml_starts(self, tmp_path, monkeypatch):
        """A missing config.yaml is not an unparseable one."""
        missing = tmp_path / "absent.yaml"
        monkeypatch.setenv("MAPPING_FILE", str(missing))
        assert load_mapping_data(missing) == {}
        assert http_server.build_asgi_app() is not None

    def test_existing_extensions_file_starts(self, tmp_path, monkeypatch):
        (tmp_path / ".opencrane").mkdir()
        (tmp_path / ".opencrane" / "config.yaml").write_text(
            "extensions: extensions.py\n", encoding="utf-8"
        )
        (tmp_path / ".opencrane" / "extensions.py").write_text(
            "from opencrane.config import OpenCraneConfig\n\n"
            "class Config(OpenCraneConfig):\n    pass\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        _config(tmp_path, monkeypatch, "auth:\n  type: none\n")
        assert http_server.build_asgi_app() is not None

    def test_module_class_config_starts(self, tmp_path, monkeypatch):
        """A module:Class import path is not checked as a file."""
        _config(tmp_path, monkeypatch, "auth:\n  type: none\n")
        monkeypatch.setenv("OPENCRANE_CONFIG", "opencrane.config:OpenCraneConfig")
        assert http_server.build_asgi_app() is not None


class TestOpenEndpointWarning:
    def test_named_open_endpoint_without_sources_warns(self, tmp_path, monkeypatch, caplog):
        _config(
            tmp_path,
            monkeypatch,
            "auth:\n  public:\n    type: none\n  docs:\n    type: none\n    default_sources: []\n"
            "    scope_sources:\n      docs:read: []\n",
        )
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            http_server.build_asgi_app()
        warnings = _warnings(caplog)
        assert len(warnings) == 1
        assert "/mcp/public" in warnings[0]
        assert "serves every indexed source to anyone" in warnings[0]

    def test_allow_anonymous_without_sources_warns(self, tmp_path, monkeypatch, caplog):
        _config(
            tmp_path,
            monkeypatch,
            "auth:\n  type: oauth\n  allow_anonymous: true\n  oidc:\n"
            "    issuer: https://idp.example.com\n    audience: docs-mcp\n",
        )
        monkeypatch.delenv("PUBLIC_URL", raising=False)
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            http_server.build_asgi_app()
        warnings = _warnings(caplog)
        assert len(warnings) == 1
        assert "auth endpoint /mcp " in warnings[0]

    def test_open_endpoint_with_default_sources_does_not_warn(self, tmp_path, monkeypatch, caplog):
        cfg = _config(tmp_path, monkeypatch, "")
        cfg.write_text(
            "sources:\n  glossary:\n    url: https://github.com/org/glossary\n"
            "auth:\n  public:\n    type: none\n    default_sources: [glossary]\n",
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            http_server.build_asgi_app()
        assert _warnings(caplog) == []
