# List-Item Chunking Fixtures

Review-stage fixtures for the list-item chunking feature
(spec: `docs/superpowers/specs/2026-04-21-list-item-chunking-design.md`).

Each fixture is a pair:

- `NN_<name>.md` — input markdown
- `NN_<name>.expected.json` — expected chunk structure the chunker must emit

## Symbolic IDs

Real `chunk_id` and `list_id` are deterministic hashes generated at runtime.
Expected files use **symbolic identifiers** prefixed with `$` so cross-references
(sibling_ids, parent_item_id) stay readable.

Example: `"chunk_id": "$item1"` in one entry and `"sibling_ids": ["$item1"]` in
another both resolve to the same real chunk_id at test time.

At test time, the harness:

1. Runs the chunker against the input `.md`
2. Generates real chunk_ids
3. Maps each symbolic `$x` in the expected file to the real chunk_id (by
   matching content + metadata)
4. Asserts the resulting structure matches

## Omitted fields

- `token_count` — runtime-calculated; excluded from assertions
- `line_start` — unused (always null); excluded from assertions

## Fixtures

| File | Purpose |
|---|---|
| `01_simple_ordered.md` | Baseline ordered list with intro + trailing prose |
| `02_unordered_short.md` | Short-item enumeration (prereqs pattern) |
| `03_nested.md` | Multi-level nesting; distinct parent/sibling relations |
| `04_with_embedded_code.md` | List items containing fenced code + continuation paragraphs |
| `05_in_code_fence.md` | List-looking lines inside a YAML fence MUST NOT be chunked as list_items |
| `06_multiple_same_section.md` | Two distinct lists in one section → two distinct `list_id`s |
| `07_long.md` | 16-item list → exercises the 15-preview cap with overflow marker |

## MCP grouping acceptance (no markdown fixture)

Derived from `01_simple_ordered.md` chunks. Acceptance asserts:

- Search for `"upgrade cgw 1.7"` returns both step chunks in top-K
- MCP response collapses them into **one** grouped result slot with both items inline
- No duplicate content across result slots
- Grouped result's score equals `max` of matched item scores
