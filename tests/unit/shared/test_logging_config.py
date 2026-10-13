"""Unit tests for logging configuration."""

import logging
import pytest
from unittest.mock import patch, mock_open
from opencrane.shared.logging_config import setup_logging


class TestLoggingConfig:
    """Test cases for logging setup."""

    @patch('logging.basicConfig')
    @patch('logging.FileHandler')
    @patch('logging.StreamHandler')
    def test_setup_logging(self, mock_stream, mock_file, mock_basic):
        """Test logging setup with default level."""
        setup_logging(logging.DEBUG)

        mock_basic.assert_called_once()
        call_kwargs = mock_basic.call_args[1]
        assert call_kwargs['level'] == logging.DEBUG
        assert 'handlers' in call_kwargs

@pytest.fixture(autouse=True)
def _restore_logging_state():
    """Keep each test's root level and warned values out of the next test."""
    from opencrane.shared import logging_config
    root = logging.getLogger()
    saved_level = root.level
    saved_warned = set(logging_config._warned_values)
    logging_config._warned_values.clear()
    yield
    root.setLevel(saved_level)
    logging_config._warned_values.clear()
    logging_config._warned_values.update(saved_warned)


@pytest.mark.unit
class TestLogLevelVariable:
    """LOG_LEVEL sets the level of every OpenCrane command."""

    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch, tmp_path):
        # setup_logging creates .opencrane/ in the working directory.
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("LOG_LEVEL", raising=False)

    def test_debug_enables_debug_output(self, monkeypatch, caplog):
        monkeypatch.setenv("LOG_LEVEL", "debug")
        with patch('logging.basicConfig'):
            setup_logging()

        assert logging.getLogger().level == logging.DEBUG
        logging.getLogger("opencrane.test").debug("debug line")
        assert "debug line" in caplog.text

    def test_default_is_info(self, caplog):
        with patch('logging.basicConfig') as mock_basic:
            setup_logging()

        assert mock_basic.call_args[1]['level'] == logging.INFO
        assert logging.getLogger().level == logging.INFO
        logging.getLogger("opencrane.test").debug("debug line")
        assert "debug line" not in caplog.text

    def test_invalid_value_warns_once_and_falls_back(self, monkeypatch, caplog):
        monkeypatch.setenv("LOG_LEVEL", "verbose")
        with patch('logging.basicConfig'):
            setup_logging()
            setup_logging()

        assert logging.getLogger().level == logging.INFO
        warnings = [r for r in caplog.records if "LOG_LEVEL" in r.getMessage()]
        assert len(warnings) == 1
        assert warnings[0].levelno == logging.WARNING
        assert "'verbose'" in warnings[0].getMessage()

    @pytest.mark.parametrize("value,expected", [
        ("DEBUG", logging.DEBUG),
        ("Warning", logging.WARNING),
        (" error ", logging.ERROR),
        ("critical", logging.CRITICAL),
        ("", logging.INFO),
    ])
    def test_resolve_log_level_is_case_insensitive(self, monkeypatch, value, expected):
        from opencrane.shared.logging_config import resolve_log_level
        monkeypatch.setenv("LOG_LEVEL", value)
        assert resolve_log_level() == expected

    def test_resolve_log_level_keeps_caller_default(self, monkeypatch, caplog):
        from opencrane.shared.logging_config import resolve_log_level
        assert resolve_log_level(logging.WARNING) == logging.WARNING

        monkeypatch.setenv("LOG_LEVEL", "loud")
        assert resolve_log_level(logging.WARNING) == logging.WARNING
        assert resolve_log_level(logging.WARNING) == logging.WARNING
        warnings = [r for r in caplog.records if "LOG_LEVEL" in r.getMessage()]
        assert len(warnings) == 1
        assert "Using WARNING" in warnings[0].getMessage()

    @pytest.mark.parametrize("value", [None, "verbose"])
    def test_keeps_host_root_level_without_valid_variable(self, monkeypatch, value):
        """A host app that configured logging first keeps its root level."""
        if value is not None:
            monkeypatch.setenv("LOG_LEVEL", value)
        logging.getLogger().setLevel(logging.WARNING)
        with patch('logging.basicConfig'):
            setup_logging()

        assert logging.getLogger().level == logging.WARNING
