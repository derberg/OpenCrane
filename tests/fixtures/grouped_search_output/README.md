# Grouped Search Output Fixtures

Golden files for the text that the MCP tools return for grouped list and table
results. The chunking fixtures (`lists/`, `source_url_pipeline/`) check what the
chunker emits. This fixture checks what an agent reads after search.

Test: `tests/unit/mcp/test_grouped_search_output_golden.py`

## Input

`chunks.json` holds the chunks as they sit in Milvus. The test serializes each
`metadata` object to `metadata_json`, mocks the Milvus search and member
queries, and calls the real tool code.

| Chunks | Purpose |
|---|---|
| `upgrade-step-1` to `upgrade-step-3` | Ordered list (`list_id: upgrade-1-7`) with `source_url` in metadata and a `source_name` |
| `log-level-row-1` to `log-level-row-3` | Table (`table_id: log-settings`) with `source_url` in metadata and a `source_name` |
| `prereq-1`, `prereq-2` | Unordered list without `source_url`, so the output falls back to `source_file` |

`source_name` is a top-level field of each chunk, like the Milvus column, not a
metadata key.

## Expected output

| File | Renders |
|---|---|
| `expected/search_docs_grouped_list.txt` | `search_docs` hit on list items 1 and 3, grouped into one result |
| `expected/search_docs_grouped_table.txt` | `search_docs` hit on table rows 1 and 2, grouped into one result |
| `expected/search_docs_grouped_list_without_source_url.txt` | `search_docs` hit on both items of the list without `source_url` |
| `expected/get_list_members.txt` | `get_list_members(list_id="upgrade-1-7")` |
| `expected/get_table_members.txt` | `get_table_members(table_id="log-settings")` |

## Regenerate

After a change to the output format, rewrite the expected files and review
their diff before you commit:

```bash
REGEN=1 ./pytest.sh tests/unit/mcp/test_grouped_search_output_golden.py --no-cov -v
```
