"""Source authorization for the id-based lookup tools.

get_yaml_definition, get_list_members and get_table_members must apply the same
source policy as search_docs: a chunk or member of a source the caller may not
read is answered exactly like a missing id, on both the stdio and HTTP transports.
"""

import json
from unittest.mock import patch

import pytest

from opencrane.mcp import server as s
from opencrane.mcp.auth.runtime import (
    reset_auth_runtime,
    set_allowed_sources,
    set_current_endpoint,
)
from opencrane.mcp.http_server import build_app


def _row(chunk_id, source, chunk_type, content, metadata, **ids):
    return {
        "chunk_id": chunk_id,
        "source_name": source,
        "chunk_type": chunk_type,
        "content": content,
        "metadata_json": json.dumps(metadata),
        "list_id": ids.get("list_id", ""),
        "table_id": ids.get("table_id", ""),
    }


ROWS = [
    _row("y_pub", "public", "crd_definition", json.dumps({"kind": "PublicKind"}), {}),
    _row("y_priv", "private", "crd_definition", json.dumps({"kind": "SecretKind"}), {}),
    _row("l_pub", "public", "list_item", "public item", {"position": 1}, list_id="Lpub"),
    _row("l_priv", "private", "list_item", "secret item", {"position": 1}, list_id="Lpriv"),
    _row("t_pub", "public", "table_row", "public row", {"row_index": 0}, table_id="Tpub"),
    _row("t_priv", "private", "table_row", "secret row", {"row_index": 0}, table_id="Tpriv"),
]


class FakeMilvus:
    """In-memory lookups that honor ``source_names`` like the Milvus filter does."""

    def __init__(self, rows, ignore_source_filter=False):
        self.rows = {r["chunk_id"]: r for r in rows}
        self.ignore_source_filter = ignore_source_filter
        self.member_queries = []

    def get_chunk(self, chunk_id):
        return self.rows.get(chunk_id)

    def query_by_field(self, field, value, chunk_type=None, limit=16384, source_names=None):
        self.member_queries.append(source_names)
        return [
            r for r in self.rows.values()
            if r.get(field) == value
            and (chunk_type is None or r["chunk_type"] == chunk_type)
            and (self.ignore_source_filter or source_names is None
                 or r["source_name"] in source_names)
        ]


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """Two sources indexed; no auth config, so the policy is AllowAll by default."""
    monkeypatch.setenv("MAPPING_FILE", str(tmp_path / "missing.yaml"))
    milvus = FakeMilvus(ROWS)
    monkeypatch.setattr(s, "get_milvus_service", lambda: milvus)
    reset_auth_runtime()
    yield milvus
    reset_auth_runtime()


def _open_endpoint_config(tmp_path, monkeypatch):
    """An open endpoint that serves only the ``public`` source (default_sources)."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "sources:\n"
        "  public:\n"
        "    url: https://github.com/org/public\n"
        "  private:\n"
        "    url: https://github.com/org/private\n"
        "auth:\n"
        "  type: none\n"
        "  default_sources:\n"
        "    - public\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAPPING_FILE", str(config))
    reset_auth_runtime()


async def _stdio(name, args):
    return (await s.call_tool(name, args))[0].text


async def _http(name, args):
    with patch.object(s, "_get_indexed_chunk_types",
                      return_value={"crd_definition", "list_item", "table_row"}), \
            patch.object(s, "_has_prose_navigation", return_value=False):
        result = await build_app().call_tool(name, args)
    return result[0].text


TRANSPORTS = pytest.mark.parametrize("call", [_stdio, _http], ids=["stdio", "http"])


async def _assert_only_public_visible(call):
    # Allowed source: returned as before.
    assert "PublicKind" in await call("get_yaml_definition", {"chunk_id": "y_pub"})
    assert "public item" in await call("get_list_members", {"list_id": "Lpub"})
    assert "public row" in await call("get_table_members", {"table_id": "Tpub"})

    # Denied source: the same answer as an id that does not exist.
    assert await call("get_yaml_definition", {"chunk_id": "y_priv"}) == "Chunk not found: y_priv"
    assert await call("get_yaml_definition", {"chunk_id": "nope"}) == "Chunk not found: nope"
    assert await call("get_list_members", {"list_id": "Lpriv"}) == "No list found for list_id='Lpriv'."
    assert await call("get_list_members", {"list_id": "nope"}) == "No list found for list_id='nope'."
    assert await call("get_table_members", {"table_id": "Tpriv"}) == "No table found for table_id='Tpriv'."
    assert await call("get_table_members", {"table_id": "nope"}) == "No table found for table_id='nope'."


@TRANSPORTS
@pytest.mark.anyio
async def test_open_endpoint_default_sources_hide_other_sources(fake, call, tmp_path, monkeypatch):
    _open_endpoint_config(tmp_path, monkeypatch)
    await _assert_only_public_visible(call)
    # The member filter reaches the database, not only the Python post-filter.
    assert fake.member_queries and all(q == ["public"] for q in fake.member_queries)


@TRANSPORTS
@pytest.mark.anyio
async def test_middleware_allowed_sources_hide_other_sources(fake, call):
    set_allowed_sources(("public",))
    await _assert_only_public_visible(call)


@TRANSPORTS
@pytest.mark.anyio
async def test_named_endpoint_policy_applies(fake, call, tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text(
        "sources:\n"
        "  public:\n"
        "    url: https://github.com/org/public\n"
        "  private:\n"
        "    url: https://github.com/org/private\n"
        "auth:\n"
        "  docs:\n"
        "    type: none\n"
        "    default_sources:\n"
        "      - public\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAPPING_FILE", str(config))
    reset_auth_runtime()
    set_current_endpoint("docs")
    await _assert_only_public_visible(call)


@TRANSPORTS
@pytest.mark.anyio
async def test_empty_allowlist_hides_everything_without_querying_members(fake, call):
    set_allowed_sources(())
    assert await call("get_yaml_definition", {"chunk_id": "y_pub"}) == "Chunk not found: y_pub"
    assert await call("get_list_members", {"list_id": "Lpub"}) == "No list found for list_id='Lpub'."
    assert await call("get_table_members", {"table_id": "Tpub"}) == "No table found for table_id='Tpub'."
    assert fake.member_queries == []


@TRANSPORTS
@pytest.mark.anyio
async def test_unrestricted_caller_sees_every_source(fake, call):
    assert "SecretKind" in await call("get_yaml_definition", {"chunk_id": "y_priv"})
    assert "secret item" in await call("get_list_members", {"list_id": "Lpriv"})
    assert "secret row" in await call("get_table_members", {"table_id": "Tpriv"})
    # No source filter is added for an unrestricted caller.
    assert fake.member_queries == [None, None]


@pytest.mark.anyio
async def test_rows_outside_policy_are_dropped_even_if_backend_returns_them(fake):
    fake.ignore_source_filter = True
    set_allowed_sources(("public",))
    assert await _stdio("get_list_members", {"list_id": "Lpriv"}) == "No list found for list_id='Lpriv'."
    assert await _stdio("get_table_members", {"table_id": "Tpriv"}) == "No table found for table_id='Tpriv'."
