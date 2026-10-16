"""The image build reads the embeddings.json header whatever the key order and size."""
import json

import pytest

from opencrane import container_env
from opencrane.container_env import ContainerEnvError, build_settings, read_embeddings_header

pytestmark = pytest.mark.unit

# Strings with brackets, braces, quotes and escapes, so the skipped list
# exercises every branch of the scanner.
_TRICKY = ['a]b', 'c}d', 'e"f', 'g\\h', '[{', '\\"]']


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("EMBEDDING_MODEL", "EMBEDDING_QUERY_PROMPT", "RERANKER_MODEL"):
        monkeypatch.delenv(name, raising=False)


def _data(records=20):
    return {
        "model": "org/recorded-model",
        "dimensions": 123456,
        "query_prompt": "search_query: ",
        "embeddings": [
            {"chunk_id": _TRICKY[i % len(_TRICKY)], "vector": [0.1, -2e-3, 3], "extra": {"k": [None, True]}}
            for i in range(records)
        ],
    }


@pytest.mark.parametrize("chunk", [1, 2, 3, 7, 64, 64 * 1024])
@pytest.mark.parametrize("indent", [None, 2])
def test_reads_header_with_sorted_keys_at_any_chunk_size(tmp_path, monkeypatch, chunk, indent):
    """sort_keys puts ``embeddings`` before ``model`` and ``query_prompt``."""
    path = tmp_path / "embeddings.json"
    path.write_text(json.dumps(_data(), indent=indent, sort_keys=True))
    monkeypatch.setattr(container_env, "_HEADER_BYTES", chunk)
    assert read_embeddings_header(path) == {
        "dimensions": 123456,
        "model": "org/recorded-model",
        "query_prompt": "search_query: ",
    }


def test_reads_header_after_a_list_larger_than_the_old_read_window(tmp_path):
    path = tmp_path / "embeddings.json"
    data = _data(records=5000)
    path.write_text(json.dumps({"embeddings": data["embeddings"], "model": data["model"]}))
    assert path.stat().st_size > 64 * 1024
    assert read_embeddings_header(path) == {"model": "org/recorded-model"}


def test_scalar_embeddings_value_and_empty_object(tmp_path):
    path = tmp_path / "embeddings.json"
    path.write_text('{"embeddings": null, "model": "m"}')
    assert read_embeddings_header(path) == {"model": "m"}
    path.write_text(" {  } ")
    assert read_embeddings_header(path) == {}


@pytest.mark.parametrize("text", [
    "",
    "[]",
    "{",
    '{"model": "m",',
    '{1: 2}',
    '{"model" "m"}',
    '{"model": "m"',
    '{"embeddings": [1, 2',
    '{"embeddings": ["a\\',
    '{"model": "unterminated',
])
def test_unparseable_file_raises_a_distinct_error(tmp_path, monkeypatch, text):
    path = tmp_path / "embeddings.json"
    path.write_text(text)
    monkeypatch.setattr(container_env, "_HEADER_BYTES", 2)
    with pytest.raises(ContainerEnvError, match="exists but cannot be parsed"):
        read_embeddings_header(path)


def test_invalid_utf8_raises_a_distinct_error(tmp_path):
    path = tmp_path / "embeddings.json"
    path.write_bytes(b'{"model": "\xff"}')
    with pytest.raises(ContainerEnvError, match="exists but cannot be parsed"):
        read_embeddings_header(path)


def test_broken_value_is_not_read_to_the_end_of_the_file(tmp_path, monkeypatch):
    """A broken value stops the read after a bounded amount of text."""
    path = tmp_path / "embeddings.json"
    path.write_text('{"model": "' + "a" * 10_000)
    monkeypatch.setattr(container_env, "_HEADER_BYTES", 16)
    monkeypatch.setattr(container_env, "_MAX_VALUE_CHARS", 64)
    reads = []
    real_more = container_env._JsonStream._more

    def counting_more(self):
        reads.append(1)
        return real_more(self)

    monkeypatch.setattr(container_env._JsonStream, "_more", counting_more)
    with pytest.raises(ContainerEnvError, match="exists but cannot be parsed"):
        read_embeddings_header(path)
    assert len(reads) < 10


def test_build_settings_tells_missing_file_from_file_without_model(tmp_path):
    with pytest.raises(ContainerEnvError, match="missing.json is missing"):
        build_settings(tmp_path / "missing.json")
    path = tmp_path / "embeddings.json"
    path.write_text('{"embeddings": []}')
    with pytest.raises(ContainerEnvError, match="has no model field"):
        build_settings(path)


def test_main_reports_unparseable_file(tmp_path, capsys):
    path = tmp_path / "embeddings.json"
    path.write_text('{"model": ')
    out = tmp_path / "image.env"
    assert container_env.main([str(path), str(out)]) == 1
    assert "exists but cannot be parsed" in capsys.readouterr().err
    assert not out.exists()
