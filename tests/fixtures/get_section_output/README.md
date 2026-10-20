# get_section Output Fixtures

Golden files for the text that the `get_section` MCP tool returns for a page
that mixes prose, a bulleted list, a numbered list, and a table across a
section and its sub-sections.

Test: `tests/unit/mcp/test_get_section_output_golden.py`

## Input

`page.md` is the page as an author wrote it. Compare the expected output with
it to check that `get_section` returns the whole section.

`chunks.json` holds the chunks that `opencrane chunk` makes from `page.md`, as
they sit in Milvus. The chunk, list, and table IDs are renamed to readable
names (`upgrade`, `step-2`, `log-variables`), and every chunk has the
`source_name` `gateway-docs` and the `source_file` `gateway/operations.md`. The
test serializes each `metadata` object to `metadata_json`, copies the metadata
keys that the index stores as scalar columns (`list_id`, `table_id`,
`clause_id`, `parent_chunk_id`), mocks the Milvus lookups, and calls the real
tool code.

| Chunks | Section | Purpose |
|---|---|---|
| `page-intro` | Gateway operations | Page title and intro |
| `upgrade`, `upgrade-2`, `upgrade-3` | Upgrade the gateway | Prose of the section, split around its two lists |
| `prereq-1`, `prereq-2` | Upgrade the gateway | Bulleted list (`list_id: prereqs`) |
| `step-1` to `step-3` | Upgrade the gateway | Numbered list (`list_id: steps`) |
| `log-settings`, `log-settings-2` | Log settings | Sub-section prose, split around its table |
| `log-var-1`, `log-var-2` | Log settings | Table (`table_id: log-variables`) |
| `rollback-check-1`, `rollback-check-2` | Rollback checks | Sub-section that has only a bulleted list (`list_id: rollback-checks`), so it has no prose chunk |
| `monitor` | Monitor the gateway | Next section |

## Expected output

| File | Renders |
|---|---|
| `expected/get_section_upgrade.txt` | `get_section(chunk_id="upgrade")` |
| `expected/get_section_upgrade_with_subsections.txt` | `get_section(chunk_id="upgrade", include_subsections=true)` |
| `expected/get_section_from_table_row.txt` | `get_section(chunk_id="log-var-1")`, a table row chunk ID |

## Regenerate

After a change to the output format, rewrite the expected files and review
their diff before you commit:

```bash
REGEN=1 ./pytest.sh tests/unit/mcp/test_get_section_output_golden.py --no-cov -v
```

After a change to the chunker, chunk `page.md` again, rename the IDs as
described in [Input](#input), and replace `chunks.json`.
