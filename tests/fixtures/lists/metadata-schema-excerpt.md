# Metadata Schema Excerpt — `list_item`

This is a review draft of the section that will be appended to
`opencrane/mcp/metadata-schema.md` during implementation.

Agents retrieve this via the parameterized tool:

```
get_metadata_schema(chunk_type="list_item")
```

The tool returns this section plus the Universal Metadata section (source_url,
original_format, schema_type) that applies to all chunk types.

---

## List Item Metadata (`chunk_type: "list_item"`)

A `list_item` chunk represents a single markdown bullet or numbered list item.
Each item of a list is indexed as its own chunk so semantic search can match
individual items precisely. Metadata links each item back to its list so the
full list can be reconstructed when needed.

### `breadcrumb_path` (string)
- **Purpose**: Heading ancestry above the list, for context anchoring
- **Format**: Heading titles joined by ` > `
- **Example**: `"Migration guide > 1.6 -> 1.7"`
- **Usage**: Already prefixed to the chunk's content as a `#` line so the
  embedding captures domain context. Agents can display it as the "where in
  the docs" locator.

### `list_id` (string)
- **Purpose**: Stable identifier grouping all items that belong to the same list
- **Format**: Deterministic hash of `(breadcrumb_path, list_ordinal_within_section, depth)`
- **Usage**:
  - Pass to `get_list_members(list_id=...)` to fetch all items of the list
  - Detect when multiple search hits belong to the same list (MCP does this
    automatically and groups them)
- **Note**: Nested lists have a different `list_id` from their parent list.
  Siblings share a `list_id`; a parent and its children do NOT.

### `list_style` (string, enum)
- **Values**: `"ordered"` (numbered: `1.`, `2.`), `"unordered"` (bulleted: `-`, `*`, `+`)
- **Usage**: Hint to the agent about the list's nature. Ordered lists are
  typically procedures (sequence matters); unordered lists are typically
  enumerations (order less important).

### `position` (integer, 1-indexed)
- **Purpose**: Position of this item within its list
- **Example**: `1` for the first item
- **Usage**: Reconstruct the list in order; render "item N of M" displays.

### `total_siblings` (integer)
- **Purpose**: Total number of items in this list (including self)
- **Example**: `5` means the list has 5 items; this item is one of them
- **Usage**: Show "item 3 of 5" context; decide whether to fetch the full list.

### `sibling_ids` (array of chunk_id strings)
- **Purpose**: chunk_ids of every OTHER item in the same list, in list order
- **Length**: Always `total_siblings - 1` (self excluded)
- **Usage**: Follow these to fetch specific sibling chunks. For bulk fetch,
  use `get_list_members(list_id=...)` instead — it's one call.

### `sibling_previews` (array of strings)
- **Purpose**: Short text previews of each sibling, same order as `sibling_ids`
- **Format**: First ~25 chars of each sibling's item text; `…` appended when truncated
- **Cap**: 15 entries maximum
  - If fewer than 15 siblings: one preview per sibling (length matches `sibling_ids`)
  - If more than 15 siblings: first 15 previews + a 16th entry literally
    `"... +N more"` where N is the overflow count
- **Usage**: Give the agent an at-a-glance "table of contents" for the rest
  of the list so it can decide whether the other items matter WITHOUT making a
  follow-up tool call. This is the token-efficient alternative to fetching the
  full list immediately.

### `parent_item_id` (chunk_id string, or null)
- **Purpose**: For nested items, the chunk_id of the enclosing bullet
- **Values**: `null` at top level (depth 0); a real chunk_id for nested items
- **Usage**: Walk up from a sub-bullet to its parent bullet. Note: the parent's
  `list_id` is different from this item's `list_id` (parent belongs to the
  outer list; this item belongs to an inner list grouped by shared parent).

### `depth` (integer)
- **Purpose**: Nesting level of this item
- **Values**: `0` for top-level items; `1` for first-nested; etc.
- **Usage**: Render indented displays; filter by level.

## Usage Example

Agent receives a `list_item` search hit:

```
Type: list_item
Metadata:
  breadcrumb_path: "Migration guide > 1.6 -> 1.7"
  list_id:        "a7f3c21b"
  list_style:     "ordered"
  position:       1
  total_siblings: 2
  sibling_ids:    ["b9e48f02"]
  sibling_previews: ["2. Install the cgw-support He…"]
Content:
# Migration guide > 1.6 -> 1.7
1. Install the cgw Helm chart in version 1.7.0.
```

The agent:

1. Sees item 1 of 2 — a small list
2. Reads the single preview and recognises it as the continuation of the
   upgrade procedure
3. Decides whether the preview is enough or calls `get_list_members(list_id="a7f3c21b")`
   to get both items in full
4. Presents the complete procedure to the user

## When Multiple List Items Match One Query

When top-K results contain ≥ 2 items sharing the same `list_id`, the MCP
`search_docs` tool **auto-groups them into a single result slot** with all
matched items inline. Unmatched items appear as `sibling_previews` in the
grouped output. This prevents duplicate content from consuming multiple result
slots. No agent action needed — the grouping is automatic.
