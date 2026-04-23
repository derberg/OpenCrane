"""Fixture-driven tests for ListChunkingStrategy."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from opencrane.rag.services.list_chunker import ListChunkingStrategy
from opencrane.rag.services.utils.chunk_id_generator import reset_collision_tracking


FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "lists"


def _mk_node(text: str, *, source_url=None, node_type: str = "text"):
    node = Mock(spec=[])
    node.text = text
    node.node_type = node_type
    node.source_url = source_url
    return node


def _run_strategy(md_path: Path):
    reset_collision_tracking()
    strategy = ListChunkingStrategy()
    text = md_path.read_text()
    node = _mk_node(text)
    # Stabilise source_file in metadata by using the repo-relative fixture path.
    source_file = Path("tests/fixtures/lists") / md_path.name
    return strategy.process(node, source_file)


def _resolve_symbols(expected: list, actual: list) -> tuple[dict, list]:
    """Map each symbolic $id in expected to the matching real value from actual.

    Walks expected + actual chunks in order. Binds:
      - The expected chunk_id symbol to the actual chunk_id.
      - Any `$x` symbols in scalar metadata fields (e.g. list_id, parent_item_id)
        to the matching actual metadata value at the same key.
      - Symbols inside list-valued metadata (sibling_ids, sibling_previews) are
        resolved separately during assertion.
    Returns (mapping, pairs) where pairs is [(expected_entry, actual_chunk), ...]
    for every asserted entry.
    """
    mapping: dict = {}
    pairs: list = []
    actual_iter = iter(actual)

    for entry in expected:
        if "chunk_id" not in entry or not isinstance(entry.get("chunk_id"), str):
            continue
        if not entry["chunk_id"].startswith("$"):
            continue  # pragma: no cover
        if entry["chunk_id"] == "$yaml_or_code":
            continue
        expected_type = entry.get("chunk_type")
        next_chunk = None
        for chunk in actual_iter:
            if chunk.chunk_type == expected_type:
                next_chunk = chunk
                break
        assert next_chunk is not None, (
            f"No actual chunk matched expected {entry['chunk_id']} (type={expected_type})"
        )
        mapping[entry["chunk_id"]] = next_chunk.chunk_id
        pairs.append((entry, next_chunk))

    # Second pass: bind symbolic scalars inside metadata (list_id, parent_item_id, …)
    for entry, chunk in pairs:
        for key, expected_val in (entry.get("metadata") or {}).items():
            if isinstance(expected_val, str) and expected_val.startswith("$"):
                actual_val = chunk.metadata.get(key)
                if expected_val in mapping:
                    assert mapping[expected_val] == actual_val, (
                        f"symbol {expected_val} resolves inconsistently: "
                        f"{mapping[expected_val]!r} vs {actual_val!r}"
                    )
                else:
                    mapping[expected_val] = actual_val

    return mapping, pairs


def _deref(value, mapping):
    """Replace any symbolic ids in nested structures with real ids using mapping."""
    if isinstance(value, str):
        if value.startswith("$") and value in mapping:
            return mapping[value]
        return value
    if isinstance(value, list):
        return [_deref(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: _deref(v, mapping) for k, v in value.items()}
    return value


def _assert_matches(expected_entries: list, actual_chunks: list):
    """Assert that `actual_chunks` match the expected entries after symbolic mapping."""
    mapping, pairs = _resolve_symbols(expected_entries, actual_chunks)

    for entry, chunk in pairs:
        sym_id = entry["chunk_id"]
        assert chunk.content == entry["content"], (
            f"{sym_id}: content mismatch\nEXPECTED:\n{entry['content']!r}\nACTUAL:\n{chunk.content!r}"
        )
        assert chunk.source_file == entry["source_file"], f"{sym_id}: source_file mismatch"
        assert chunk.chunk_type == entry["chunk_type"], f"{sym_id}: chunk_type mismatch"

        expected_meta = _deref(entry["metadata"], mapping)
        for key, expected_val in expected_meta.items():
            assert chunk.metadata.get(key) == expected_val, (
                f"{sym_id}.metadata.{key}: expected {expected_val!r}, got {chunk.metadata.get(key)!r}"
            )


FIXTURE_NAMES = [
    "01_simple_ordered",
    "02_unordered_short",
    "03_nested",
    "04_with_embedded_code",
    "06_multiple_same_section",
]


@pytest.mark.parametrize("fixture", FIXTURE_NAMES)
def test_fixture(fixture):
    md = FIXTURES_DIR / f"{fixture}.md"
    expected_path = FIXTURES_DIR / f"{fixture}.expected.json"
    assert md.exists() and expected_path.exists()
    expected = json.loads(expected_path.read_text())
    actual = _run_strategy(md)
    _assert_matches(expected, actual)


def test_07_long_overflow():
    """Verify invariants for long lists: sibling_ids length and preview overflow marker."""
    md = FIXTURES_DIR / "07_long.md"
    expected = json.loads((FIXTURES_DIR / "07_long.expected.json").read_text())
    actual = _run_strategy(md)

    list_items = [c for c in actual if c.chunk_type == "list_item"]
    assert len(list_items) == 17

    for chunk in list_items:
        total = chunk.metadata["total_siblings"]
        sibling_ids = chunk.metadata["sibling_ids"]
        previews = chunk.metadata["sibling_previews"]
        # sibling_ids length == total_siblings - 1
        assert len(sibling_ids) == total - 1
        # Previews: first 15 + overflow marker when > 15 siblings
        if total - 1 > 15:
            assert len(previews) == 16
            assert previews[-1].startswith("... +")
            assert previews[-1].endswith("more")
        else:
            assert len(previews) == total - 1  # pragma: no cover

    # Spot-check the expected content for item_01 (the only item fully spelled out in expected.json).
    prose_intro = expected[0]
    item_01_expected = expected[1]
    # Find the actual prose_intro chunk
    prose_chunks = [c for c in actual if c.chunk_type == "prose"]
    assert len(prose_chunks) == 1
    assert prose_chunks[0].content == prose_intro["content"]

    item_01 = list_items[0]
    assert item_01.content == item_01_expected["content"]
    assert item_01.metadata["position"] == 1
    assert item_01.metadata["total_siblings"] == 17
    assert len(item_01.metadata["sibling_ids"]) == 16
    assert item_01.metadata["sibling_previews"][-1] == "... +1 more"
    # First 15 previews match the first 15 regions from item_02 onwards
    expected_first_15 = [
        "us-east-2", "us-west-1", "us-west-2", "eu-west-1", "eu-west-2",
        "eu-central-1", "ap-south-1", "ap-southeast-1", "ap-southeast-2", "ap-northeast-1",
        "ap-northeast-2", "sa-east-1", "ca-central-1", "af-south-1", "me-south-1",
    ]
    assert item_01.metadata["sibling_previews"][:15] == expected_first_15


def test_05_code_fence_never_produces_list_items():
    """Invariant: lines inside a fenced block MUST NOT be chunked as list_items."""
    md = FIXTURES_DIR / "05_in_code_fence.md"
    actual = _run_strategy(md)
    # Inside the yaml fence the lines "- 192.0.2.1" look like list items but must be ignored.
    assert all(c.chunk_type != "list_item" for c in actual), (
        "Fenced lines leaked into list_item chunks: "
        + repr([c.content for c in actual if c.chunk_type == "list_item"])
    )


def test_can_process_requires_list_outside_fence():
    strategy = ListChunkingStrategy()
    # Plain prose with no lists — ListChunkingStrategy should decline.
    node = _mk_node("# Title\n\nJust some prose.\n")
    assert strategy.can_process(node) is False

    # Lists only inside a fence — still False.
    node_fenced = _mk_node("```\n- item\n```\n")
    assert strategy.can_process(node_fenced) is False

    # Actual list marker outside fence — True.
    node_list = _mk_node("- a\n- b\n")
    assert strategy.can_process(node_list) is True


def test_can_process_rejects_non_text_nodes():
    strategy = ListChunkingStrategy()
    empty = Mock(spec=[])  # no .text attribute
    assert strategy.can_process(empty) is False

    code_node = _mk_node("- a\n- b\n", node_type="code")
    assert strategy.can_process(code_node) is False

    blank = _mk_node("   \n\n")
    assert strategy.can_process(blank) is False
