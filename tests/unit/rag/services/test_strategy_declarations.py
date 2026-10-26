"""Tests for the block tags and metadata keys that strategies declare."""

from pathlib import Path

import pytest

from opencrane.config import OpenCraneConfig
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.rag.services.file_processor import FileProcessor
from opencrane.rag.services.utils.chunk_id_generator import generate_unique_chunk_id
from opencrane.shared.models.chunk import (
    BUILTIN_PROSE_METADATA_KEYS,
    Chunk,
    declared_metadata_keys,
    register_metadata_keys,
)


class _Strategy(ProcessingStrategy):
    def can_process(self, node) -> bool:
        return False

    def process(self, node, source_file: Path):
        return []  # pragma: no cover - never chosen


def _strategy(tags=(), keys=None, name="Declaring"):
    cls = type(name, (_Strategy,), {"block_tags": tuple(tags), "metadata_keys": dict(keys or {})})
    return cls()


def _config(*strategies):
    class Config(OpenCraneConfig):
        chunking_strategies = [*strategies, *OpenCraneConfig.chunking_strategies]
    return Config()


@pytest.fixture(autouse=True)
def _reset_registry():
    yield
    register_metadata_keys({})


def _prose(metadata):
    return Chunk(content="text", source_file="f", chunk_type="prose", metadata=metadata, token_count=1)


def test_base_strategy_declares_nothing():
    assert _Strategy.block_tags == ()
    assert _Strategy.metadata_keys == {}


def test_block_strategies_maps_tag_to_strategy():
    strategy = _strategy(tags=["details"])
    assert FileProcessor(_config(strategy)).block_strategies == {"details": strategy}


def test_duplicate_block_tag_raises():
    with pytest.raises(ValueError, match="details.*First.*Second|details.*Second.*First"):
        FileProcessor(_config(_strategy(["details"], name="First"), _strategy(["details"], name="Second")))


def test_declared_key_equal_to_builtin_raises():
    with pytest.raises(ValueError, match="source_url"):
        FileProcessor(_config(_strategy(keys={"source_url": "clash"})))


def test_conflicting_descriptions_raise():
    with pytest.raises(ValueError, match="my_key"):
        FileProcessor(_config(_strategy(keys={"my_key": "one"}), _strategy(keys={"my_key": "two"})))


def test_same_key_same_description_is_allowed():
    FileProcessor(_config(_strategy(keys={"my_key": "same"}), _strategy(keys={"my_key": "same"})))
    assert declared_metadata_keys() == {"my_key": "same"}


def test_declared_prose_key_accepted():
    FileProcessor(_config(_strategy(keys={"tab_label": "Label of the tab."})))
    assert _prose({"tab_label": "CLI"}).metadata["tab_label"] == "CLI"


def test_undeclared_prose_key_rejected():
    FileProcessor(_config())
    with pytest.raises(ValueError):
        _prose({"tab_label": "CLI"})


def test_tab_keys_are_not_builtin():
    assert "tab_value" not in BUILTIN_PROSE_METADATA_KEYS
    assert "tab_label" not in BUILTIN_PROSE_METADATA_KEYS


def test_tab_value_no_longer_changes_chunk_id():
    first = generate_unique_chunk_id("same", "f", "prose", {"tab_value": "cli"})
    from opencrane.rag.services.utils.chunk_id_generator import reset_collision_tracking
    reset_collision_tracking()
    second = generate_unique_chunk_id("same", "f", "prose", {"tab_value": "cmc"})
    assert first == second
