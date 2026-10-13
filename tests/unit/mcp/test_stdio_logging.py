"""The stdio MCP server honors LOG_LEVEL and keeps stdout clean."""

import os
import subprocess
import sys

import pytest

_PROBE = (
    "import opencrane.mcp.server as s\n"
    "s.logger.debug('probe debug line')\n"
    "s.logger.info('probe info line')\n"
)


def _run_server_import(tmp_path, log_level):
    env = dict(os.environ)
    env.pop("LOG_LEVEL", None)
    if log_level is not None:
        env["LOG_LEVEL"] = log_level
    # tmp_path as the working directory keeps the log file out of the repo.
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300,
    )


@pytest.mark.unit
class TestStdioServerLogging:

    def test_debug_goes_to_stderr_and_stdout_stays_empty(self, tmp_path):
        result = _run_server_import(tmp_path, "DEBUG")

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert "probe debug line" in result.stderr
        assert "probe info line" in result.stderr

    def test_default_level_is_info(self, tmp_path):
        result = _run_server_import(tmp_path, None)

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert "probe debug line" not in result.stderr
        assert "probe info line" in result.stderr

    def test_invalid_value_warns_once_on_stderr(self, tmp_path):
        result = _run_server_import(tmp_path, "chatty")

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert result.stderr.count("Ignoring invalid LOG_LEVEL='chatty'") == 1
        assert "probe debug line" not in result.stderr
        assert "probe info line" in result.stderr
