"""Tests for embedding document/query prompts."""

import logging

import pytest

from opencrane.shared.config import get_config
from opencrane.shared.utils.embedding_prompts import (
    format_document,
    format_query,
    warn_if_inconsistent,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_prompt_env(monkeypatch):
    monkeypatch.delenv("EMBEDDING_DOCUMENT_PROMPT", raising=False)
    monkeypatch.delenv("EMBEDDING_QUERY_PROMPT", raising=False)


def test_defaults_are_empty_and_leave_text_unchanged(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "example/model-without-prompts")
    config = get_config()
    assert config.embedding_document_prompt is None
    assert config.embedding_query_prompt is None
    assert format_document("some text") == "some text"
    assert format_query("how to x") == "how to x"


def test_nomic_prefixes_from_env(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DOCUMENT_PROMPT", "search_document: ")
    monkeypatch.setenv("EMBEDDING_QUERY_PROMPT", "search_query: ")
    assert format_document("passage") == "search_document: passage"
    assert format_query("question") == "search_query: question"


def test_query_template_placeholder_and_newline_unescape(monkeypatch):
    monkeypatch.setenv(
        "EMBEDDING_QUERY_PROMPT",
        r"Instruct: Given a question, retrieve relevant passages\nQuery: {query}",
    )
    assert get_config().embedding_query_prompt == (
        "Instruct: Given a question, retrieve relevant passages\nQuery: {query}"
    )
    assert format_query("what is AMF?") == (
        "Instruct: Given a question, retrieve relevant passages\nQuery: what is AMF?"
    )


def test_explicit_prompt_arguments_override_config(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DOCUMENT_PROMPT", "ignored: ")
    monkeypatch.setenv("EMBEDDING_QUERY_PROMPT", "ignored: ")
    assert format_document("d", "doc: ") == "doc: d"
    assert format_query("q", "<{query}>") == "<q>"
    assert format_query("q", "") == "q"


def test_warns_when_document_prompt_has_no_query_prompt(monkeypatch, caplog):
    monkeypatch.setenv("EMBEDDING_DOCUMENT_PROMPT", "search_document: ")
    monkeypatch.setenv("EMBEDDING_QUERY_PROMPT", "")
    with caplog.at_level(logging.WARNING):
        warn_if_inconsistent()
    assert "EMBEDDING_QUERY_PROMPT is empty" in caplog.text


@pytest.mark.parametrize("doc, query", [("", ""), ("search_document: ", "search_query: "), ("", "Query: {query}")])
def test_no_warning_for_consistent_setups(monkeypatch, caplog, doc, query):
    monkeypatch.setenv("EMBEDDING_DOCUMENT_PROMPT", doc)
    monkeypatch.setenv("EMBEDDING_QUERY_PROMPT", query)
    with caplog.at_level(logging.WARNING):
        warn_if_inconsistent()
    assert caplog.text == ""


# --- Resolution: env > model prompts > known-model table > empty -------------

from types import SimpleNamespace  # noqa: E402
from unittest.mock import patch  # noqa: E402

from opencrane.shared.utils import embedding_prompts  # noqa: E402
from opencrane.shared.utils.embedding_prompts import (  # noqa: E402
    KNOWN_MODEL_PROMPTS,
    read_model_prompts,
    resolve_document_prompt,
    resolve_query_prompt,
)

QWEN_QUERY = "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"
QWEN = SimpleNamespace(prompts={"query": QWEN_QUERY, "document": ""})
# sentence-transformers fills missing query/document prompts with ""
NOMIC = SimpleNamespace(prompts={"query": "", "document": ""})


@pytest.fixture
def no_model_files():
    """Mock the model-file lookup to report no file, so a test can assert on its calls."""
    with patch.object(embedding_prompts, "read_model_prompts", return_value=None) as m:
        yield m


def test_default_model_uses_known_nomic_prefixes(no_model_files):
    assert format_document("passage") == "search_document: passage"
    assert format_query("question") == "search_query: question"
    no_model_files.assert_called_with("nomic-ai/nomic-embed-text-v1.5")


def test_empty_env_means_no_prompt_even_for_known_model(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DOCUMENT_PROMPT", "")
    monkeypatch.setenv("EMBEDDING_QUERY_PROMPT", "")
    assert format_document("passage") == "passage"
    assert format_query("question") == "question"


def test_env_wins_over_model_prompts():
    with patch.dict("os.environ", {"EMBEDDING_QUERY_PROMPT": "q: "}):
        assert resolve_query_prompt(QWEN, "Qwen/Qwen3-Embedding-0.6B") == "q: "


def test_model_prompts_win_over_table():
    model = SimpleNamespace(prompts={"query": "mq: ", "document": "md: "})
    assert resolve_document_prompt(model, "nomic-ai/nomic-embed-text-v1.5") == "md: "
    assert resolve_query_prompt(model, "nomic-ai/nomic-embed-text-v1.5") == "mq: "


def test_qwen_shipped_prompts_are_used():
    assert resolve_document_prompt(QWEN, "Qwen/Qwen3-Embedding-0.6B") == ""
    assert format_query("what is AMF?", model=QWEN, model_name="Qwen/Qwen3-Embedding-0.6B") == QWEN_QUERY + "what is AMF?"


def test_empty_model_prompts_fall_back_to_table():
    assert resolve_document_prompt(NOMIC, "nomic-ai/nomic-embed-text-v1") == "search_document: "
    assert resolve_query_prompt(NOMIC, "nomic-ai/nomic-embed-text-v1") == "search_query: "


def test_prompt_name_aliases():
    model = SimpleNamespace(prompts={"passage": "p: ", "search_query": "sq: "})
    assert resolve_document_prompt(model, "x/y") == "p: "
    assert resolve_query_prompt(model, "x/y") == "sq: "


def test_non_dict_prompts_and_non_string_name_resolve_empty():
    model = SimpleNamespace(prompts=object())
    assert resolve_document_prompt(model, object()) == ""
    assert resolve_query_prompt(object(), "x/unknown") == ""


def test_unknown_model_resolves_empty():
    assert resolve_document_prompt(model_name="x/unknown") == ""


def test_without_model_reads_prompts_from_model_files():
    with patch.object(embedding_prompts, "read_model_prompts", return_value={"query": "fq: "}) as m:
        assert resolve_query_prompt(model_name="x/y") == "fq: "
    m.assert_called_once_with("x/y")


def test_known_model_table_pairs():
    assert KNOWN_MODEL_PROMPTS["nomic-ai/nomic-embed-text-v1.5"] == ("search_document: ", "search_query: ")
    assert KNOWN_MODEL_PROMPTS["intfloat/e5-base-v2"] == ("passage: ", "query: ")


def test_read_model_prompts_from_local_dir(tmp_path):
    (tmp_path / "config_sentence_transformers.json").write_text('{"prompts": {"query": "q: "}}')
    assert read_model_prompts(str(tmp_path)) == {"query": "q: "}


def test_read_model_prompts_non_dict_prompts(tmp_path):
    (tmp_path / "config_sentence_transformers.json").write_text('{"prompts": ["q"]}')
    assert read_model_prompts(str(tmp_path)) is None


def test_read_model_prompts_malformed_file(tmp_path):
    (tmp_path / "config_sentence_transformers.json").write_text("{not json")
    assert read_model_prompts(str(tmp_path)) is None


def test_read_model_prompts_from_hf_cache(tmp_path, monkeypatch):
    cached = tmp_path / "config_sentence_transformers.json"
    cached.write_text('{"prompts": {"document": "d: "}}')
    monkeypatch.setenv("SENTENCE_TRANSFORMERS_HOME", str(tmp_path / "st-home"))
    with patch.object(embedding_prompts, "try_to_load_from_cache", return_value=str(cached)) as m:
        assert read_model_prompts("org/model") == {"document": "d: "}
    m.assert_called_once_with("org/model", "config_sentence_transformers.json", cache_dir=str(tmp_path / "st-home"))


def test_read_model_prompts_not_cached():
    with patch.object(embedding_prompts, "try_to_load_from_cache", return_value=None):
        assert read_model_prompts("org/model") is None


def test_warns_for_model_defaults_with_empty_query_env(monkeypatch, caplog):
    monkeypatch.setenv("EMBEDDING_QUERY_PROMPT", "")
    with caplog.at_level(logging.WARNING):
        warn_if_inconsistent()
    assert "'search_document: '" in caplog.text


def test_no_warning_for_model_defaults(caplog):
    with caplog.at_level(logging.WARNING):
        warn_if_inconsistent(QWEN, "Qwen/Qwen3-Embedding-0.6B")
        warn_if_inconsistent(NOMIC, "nomic-ai/nomic-embed-text-v1.5")
    assert caplog.text == ""
