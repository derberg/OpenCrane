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


def test_defaults_are_empty_and_leave_text_unchanged():
    config = get_config()
    assert config.embedding_document_prompt == ""
    assert config.embedding_query_prompt == ""
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
