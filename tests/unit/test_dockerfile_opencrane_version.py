"""The generated Dockerfile installs at least the opencrane that wrote it, and the
README sends the runtime-only encoder settings to the container, not the build."""
import importlib.metadata
import sys
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from opencrane import templates
from opencrane.cli import main as cli_main
from opencrane.templates import dockerfile, opencrane_requirement, readme

pytestmark = pytest.mark.unit


def _version(value):
    return patch.object(templates.importlib.metadata, "version", return_value=value)


@pytest.mark.parametrize("installed, expected", [
    ("1.2.3", '"opencrane>=1.2.3"'),
    ("1.2.3+g1234abc", '"opencrane>=1.2.3"'),
    ("1.3.0rc1", '"opencrane>=1.3.0rc1"'),
    ("0.0.0", "opencrane"),
    ("0", "opencrane"),
    ("not a version", "opencrane"),
])
def test_requirement_follows_the_installed_version(installed, expected):
    with _version(installed):
        assert opencrane_requirement() == expected


def test_requirement_without_package_metadata_is_unpinned():
    error = importlib.metadata.PackageNotFoundError("opencrane")
    with patch.object(templates.importlib.metadata, "version", side_effect=error):
        assert opencrane_requirement() == "opencrane"


def test_requirement_without_packaging_is_unpinned():
    with _version("1.2.3"), patch.dict(sys.modules, {"packaging.version": None}):
        assert opencrane_requirement() == "opencrane"


def test_dockerfile_installs_the_rendering_version():
    with _version("4.5.6"):
        text = dockerfile()
    assert 'pip install "opencrane>=4.5.6"' in text
    assert "{opencrane_requirement}" not in text
    assert "pip install opencrane\n" not in text


def test_init_writes_the_rendered_dockerfile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with _version("7.8.9"):
        result = CliRunner().invoke(cli_main, ["init", "--no-add"])
    assert result.exit_code == 0, result.output
    assert 'pip install "opencrane>=7.8.9"' in (tmp_path / ".opencrane" / "Dockerfile").read_text()


def test_init_from_a_checkout_writes_an_installable_dockerfile(tmp_path, monkeypatch):
    """No mock: the version of this checkout renders into a valid requirement."""
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli_main, ["init", "--no-add"])
    assert result.exit_code == 0, result.output
    text = (tmp_path / ".opencrane" / "Dockerfile").read_text()
    assert f"pip install {opencrane_requirement()}\n" in text
    assert "{opencrane_requirement}" not in text


@pytest.mark.parametrize("podman, tool", [(False, "docker"), (True, "podman")])
def test_readme_sets_dtype_and_device_at_run_time(podman, tool):
    text = readme(podman=podman)
    assert f"`{tool} run -e EMBEDDING_DTYPE=bfloat16`" in text
    assert "Only the server uses them" in text
    assert "--build-arg EMBEDDING_DTYPE" not in text
    assert "--build-arg EMBEDDING_DEVICE" not in text
