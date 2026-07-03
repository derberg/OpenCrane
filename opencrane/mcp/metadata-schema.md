# Chunk Metadata Schema

This document defines the metadata schema for all chunk types. Metadata fields enable programmatic navigation, context expansion, and hierarchical relationships in the RAG system.

## Universal Metadata (All Chunk Types)

### `source_url` (string, optional)
- **Purpose**: Link to original documentation page
- **Usage**: Provide source attribution in RAG responses
- **Example**: `"https://github.com/org/repo/blob/main/docs/config.md"`

### `original_format` (string, optional)
- **Purpose**: Original serialization format of content
- **Values**: `"yaml"` for structured schema chunks
- **Usage**: Guide re-hydration process (e.g., convert dict back to YAML)

### `schema_type` (string, optional)
- **Purpose**: High-level schema category for YAML content
- **Values**: `"k8s_crd"`, `"openapi"`, `"json_schema"`
- **Usage**: Route to appropriate validators and processors

## Hierarchical Navigation Metadata

These fields enable tree traversal and context reconstruction:

### `breadcrumb_path` (string)
- **Purpose**: Exact location in YAML/document tree structure
- **Format**: Dot-separated path with array indices
- **Usage**:
  - **Re-hydration**: Reconstruct complete YAML tree from chunks
  - **Location Display**: Show users where property exists in schema
  - **Precise Lookup**: Find exact position in nested structures
- **Examples**:
  - CRD: `"spec.versions[0].schema.openAPIV3Schema.properties.spec.properties.replicas"`
  - OpenAPI: `"paths./users/{id}.get"`
  - JSON Schema: `"properties.config.properties.database"`

### `logical_parent` (string)
- **Purpose**: Parent node in tree hierarchy (one level up)
- **Format**: Same as breadcrumb_path but without final segment
- **Usage**:
  - **Parent Context**: Navigate up to parent for additional context
  - **Grouping**: Identify sibling chunks (chunks with same parent)
  - **Hierarchy Display**: Build visual tree representations
- **Examples**:
  - For `spec.replicas` → parent is `"spec.versions[0].schema.openAPIV3Schema.properties.spec.properties"`
  - For `paths./users.get` → parent is `"paths./users"`

### `neighbor_chunks` (array of UUIDs)
- **Purpose**: Sibling chunks at same tree level
- **Definition**: All chunks sharing the same `logical_parent`
- **Format**: Array of chunk_id UUIDs
- **Usage**:
  - **Context Expansion**: Automatically fetch related properties/siblings
  - **Related Info**: Show users other properties at same level
  - **Completeness**: Ensure all related config options are retrieved
- **Example**: For CRD property `spec.replicas`, neighbors include `spec.image`, `spec.config`, etc.
- **Empty Array**: Indicates chunk has no siblings (only child under parent)

## CRD-Specific Metadata (`chunk_type: "crd_definition"`)

### `crd_kind` (string)
- **Purpose**: Kubernetes resource kind
- **Example**: `"MyResource"`, `"Deployment"`, `"Service"`
- **Usage**: Filter by resource type

### `crd_api_version` (string)
- **Purpose**: Full API group and version
- **Format**: `{group}/{version}`
- **Example**: `"mygroup.example.com/v1"`
- **Usage**: Version-specific property lookup

### `crd_version` (string)
- **Purpose**: Version identifier only
- **Example**: `"v1"`, `"v1alpha1"`, `"v1beta1"`
- **Usage**: Quick version filtering

### `crd_property_path` (string)
- **Purpose**: User-friendly property path (simplified)
- **Format**: Starts from `spec.`, shows property hierarchy
- **Examples**:
  - Top-level: `"spec.replicas"`
  - Nested: `"spec.config.database"`
  - Array items: `"spec.volumes.items.name"`
- **Usage**: Display concise paths in RAG responses
- **Note**: For recursively chunked properties, shows full nested path

## OpenAPI-Specific Metadata (`chunk_type: "openapi_spec"`)

### `openapi_version` (string)
- **Purpose**: OpenAPI specification version
- **Examples**: `"3.0.1"`, `"3.1.0"`
- **Usage**: Ensure compatibility with spec version

### `openapi_element` (string, enum)
- **Purpose**: Top-level OpenAPI element type
- **Values**: `"info"`, `"servers"`, `"security"`, `"tags"`, `"paths"`, `"components"`
- **Usage**: Categorize and filter chunks by element type

### `server_url` (string, optional)
- **Present in**: Server chunks
- **Example**: `"https://api.example.com/v1"`

### `endpoint_path` (string, optional)
- **Present in**: Path operation chunks
- **Example**: `"/users/{id}/settings"`

### `http_method` (string, optional)
- **Present in**: Path operation chunks
- **Values**: `"get"`, `"post"`, `"put"`, `"delete"`, `"patch"`, etc.

### `component_type` (string, optional)
- **Present in**: Component chunks
- **Values**: `"schemas"`, `"securitySchemes"`, `"responses"`, `"parameters"`, etc.

### `schema_name` (string, optional)
- **Present in**: Schema component chunks
- **Example**: `"User"`, `"Order"`, `"ErrorResponse"`

### `property_name` (string, optional)
- **Present in**: Recursively chunked schema property chunks
- **Example**: `"email"`, `"profile"`, `"settings"`

### `property_path` (string, optional)
- **Present in**: Recursively chunked schema property chunks
- **Format**: Dot-separated path within schema
- **Examples**:
  - `"User.profile.address"`
  - `"Order.items.quantity"`

## JSON Schema-Specific Metadata (`chunk_type: "json_schema"`)

### `schema_version` (string)
- **Purpose**: JSON Schema draft version
- **Example**: `"https://json-schema.org/draft/2020-12/schema"`
- **Usage**: Parse schema according to correct draft

### `schema_id` (string, optional)
- **Purpose**: Schema identifier from `$id` field
- **Example**: `"https://example.com/schemas/user.json"`

### `schema_title` (string, optional)
- **Purpose**: Schema title from root `title` field
- **Example**: `"User Configuration Schema"`

### `schema_element` (string, enum)
- **Purpose**: Schema element type
- **Values**: `"root"`, `"properties"`, `"definitions"`
- **Usage**: Categorize chunks by element type

### `property_name` (string, optional)
- **Present in**: Property chunks
- **Example**: `"username"`, `"config"`, `"settings"`

### `property_path` (string, optional)
- **Present in**: Property chunks
- **Format**: Dot-separated path (no "properties" keywords)
- **Examples**:
  - Simple: `"username"`
  - Nested: `"config.database"`
  - Array items: `"volumes.items.name"`
- **Usage**: Display clean property paths

### `definition_name` (string, optional)
- **Present in**: Definition chunks
- **Example**: `"address"`, `"phoneNumber"`
- **Usage**: Reference schema definitions

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
- **Format**: Preview line capped at 30 display characters; ordered items
  include their `N.` prefix. `…` appended when the body is truncated;
  ` …` appended when the body fits but the item has additional paragraphs /
  code beyond the first line.
- **Cap**: 15 entries maximum
  - If fewer than 15 siblings: one preview per sibling (length matches `sibling_ids`)
  - If more than 15 siblings: first 15 previews + a 16th entry literally
    `"... +N more"` where N is the overflow count
- **Usage**: Give the agent an at-a-glance "table of contents" for the rest
  of the list so it can decide whether the other items matter WITHOUT making a
  follow-up tool call.

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

### When Multiple List Items Match One Query

When top-K search results contain two or more items sharing the same `list_id`,
the MCP `search_docs` tool **auto-groups them into a single result slot** with
all matched items inline. Unmatched items appear as `sibling_previews` in the
grouped output. This prevents duplicate content from consuming multiple result
slots. No agent action needed — the grouping is automatic.

## Table Row Metadata (`chunk_type: "table_row"`)

A `table_row` chunk represents a single data row of a markdown table. Each row
is indexed as its own chunk so semantic search can match individual rows
precisely. Metadata links each row back to its table so the full table can be
reconstructed when needed.

### `table_id` (string)
- **Purpose**: Stable identifier matching the parent `table` chunk and all
  sibling `table_row` chunks
- **Usage**:
  - Pass to `get_table_members(table_id=...)` to fetch the whole table
  - Detect when multiple search hits belong to the same table

### `columns` (array of strings)
- **Purpose**: Ordered list of column header names (repeated from the overview)
- **Usage**: Interpret the row's field values without fetching the overview chunk

### `row_index` (integer, 1-indexed)
- **Purpose**: Position of this row within the table
- **Example**: `1` for the first data row
- **Usage**: Reconstruct the table in order; render "row N of M" displays

### `total_rows` (integer)
- **Purpose**: Total number of data rows in the table
- **Usage**: Show "row 3 of 12" context; decide whether to fetch the full table

### `row_key` (string, optional)
- **Purpose**: Value of the first column for this row, used as a concise label
- **Example**: `"replicas"` (if the first column is "Field")
- **Usage**: Quick identification without parsing the full row content

### `sibling_ids` (array of chunk_id strings)
- **Purpose**: chunk_ids of every OTHER row in the same table, in row order
- **Length**: Always `total_rows - 1` (self excluded)
- **Usage**: Follow these to fetch specific sibling row chunks. For bulk fetch,
  use `get_table_members(table_id=...)` instead — it is one call.

### `sibling_previews` (array of strings, optional)
- **Purpose**: Short text previews of other rows in the same table
- **Format**: One preview per sibling row, capped at ~30 characters; `...`
  appended when truncated
- **Usage**: Give the agent an at-a-glance summary of other rows so it can
  decide whether to call `get_table_members` without a follow-up tool call

### Rehydration Tool

Use `get_table_members(table_id=...)` to fetch all `table_row` chunks for a
given `table_id`, returned in `row_index` order.
The MCP `search_docs` tool appends a tip automatically when a result is a
`table_row` chunk.

## Programmatic Usage Examples

### Context Expansion (Python)
```python
def expand_with_neighbors(chunk: Chunk, chunk_db: Dict[str, Chunk]) -> List[Chunk]:
    """Fetch neighbor chunks for additional context."""
    neighbor_ids = chunk.metadata["neighbor_chunks"]
    neighbors = [chunk_db[id] for id in neighbor_ids if id in chunk_db]
    return [chunk] + neighbors
```

### Parent Navigation (Python)
```python
def get_parent_context(chunk: Chunk, chunk_db: Dict[str, Chunk]) -> Optional[Chunk]:
    """Navigate up to parent chunk."""
    parent_path = chunk.metadata["logical_parent"]
    # Find chunk with breadcrumb_path matching parent_path
    for candidate in chunk_db.values():
        if candidate.metadata.get("breadcrumb_path") == parent_path:
            return candidate
    return None
```

### Re-hydration (Python)
```python
def reconstruct_yaml(chunks: List[Chunk]) -> dict:
    """Reconstruct YAML tree from chunks using breadcrumb paths."""
    result = {}
    for chunk in chunks:
        path = chunk.metadata["breadcrumb_path"]
        set_nested_value(result, path.split("."), chunk.content)
    return result
```

## MCP Server Integration

The MCP server uses these metadata fields programmatically:

1. **Search Tool**: Returns chunks with metadata for LLM to understand context
2. **YAML Definition Tool**: Uses `breadcrumb_path` to add location comments
3. **Context Expansion**: Automatically fetches `neighbor_chunks` when relevant
4. **Hierarchical Display**: Uses `logical_parent` to show tree structure

The LLM receives **enriched results** from the MCP server, not raw chunks, so it doesn't need to interpret metadata directly.

## Schema JSON Definition

For programmatic validation, see `opencrane/shared/models/chunk.py` for the Pydantic model definition.
