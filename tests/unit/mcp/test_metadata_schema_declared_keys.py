"""Tests for strategy-declared metadata keys in get_metadata_schema."""

from pathlib import Path
from unittest.mock import patch

import pytest

from opencrane.config import OpenCraneConfig
from opencrane.mcp import server as mcp_server
from opencrane.mcp.server import get_metadata_schema
from opencrane.rag.services.base_strategy import ProcessingStrategy


class Labeled(ProcessingStrategy):
    block_tags = ("Box",)
    metadata_keys = {"box_label": "Label of the Box component the chunk comes from."}

    def can_process(self, node) -> bool:
        return False  # pragma: no cover - never run here

    def process(self, node, source_file: Path):
        return []  # pragma: no cover - never run here


class LabeledConfig(OpenCraneConfig):
    chunking_strategies = [Labeled(), *OpenCraneConfig.chunking_strategies]


@pytest.fixture(autouse=True)
def _reset_cache():
    mcp_server._declared_keys_cache = None
    yield
    mcp_server._declared_keys_cache = None


async def _schema(config, arguments=None):
    with patch("opencrane.cli.load_config", return_value=config):
        result = await get_metadata_schema(arguments or {})
    return result[0].text


@pytest.mark.anyio
async def test_full_schema_lists_declared_keys():
    text = await _schema(LabeledConfig())
    assert "## Strategy Metadata" in text
    assert "`box_label`" in text
    assert "Label of the Box component the chunk comes from." in text


@pytest.mark.anyio
async def test_filtered_schema_lists_declared_keys():
    text = await _schema(LabeledConfig(), {"chunk_type": "list_item"})
    assert "`box_label`" in text


@pytest.mark.anyio
async def test_no_section_without_extra_declared_keys():
    text = await _schema(OpenCraneConfig())
    assert "## Strategy Metadata" not in text


@pytest.mark.anyio
async def test_no_section_when_config_fails_to_load():
    with patch("opencrane.cli.load_config", side_effect=RuntimeError("broken")):
        result = await get_metadata_schema({})
    assert "## Strategy Metadata" not in result[0].text


@pytest.mark.anyio
async def test_schema_documents_details_summary_and_no_tab_fields():
    text = await _schema(OpenCraneConfig())
    assert "`details_summary`" in text
    assert "tab_value" not in text and "tab_label" not in text
