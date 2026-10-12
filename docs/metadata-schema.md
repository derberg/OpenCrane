# Chunk metadata schema

This page lists the metadata fields of each chunk type. Your code can use these fields to move between related chunks and to add context to a search result. Retrieval-augmented generation (RAG) responses use them to link to the source page.

## Universal metadata

Chunks of all types can carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `source_url` | string, optional | Link to the documentation page that the chunk came from, without an in-page anchor. Use it to link RAG responses to the source page. | `"https://docs.example.com/config"` |
| `section_anchor` | string, optional | In-page anchor of the section that the chunk came from. Only prose, list item, and table row chunks that have a `source_url` and sit under a heading of level two or deeper have it. | `"prerequisites"` |
| `original_format` | string, optional | Original format of the content. Only CustomResourceDefinition (CRD), OpenAPI, and JSON Schema chunks have it. Use it to convert the content back to that format, for example from a dictionary to YAML. | `"yaml"` |
| `schema_type` | string, enum, optional | Schema category of YAML content: `"k8s_crd"`, `"openapi"`, or `"json_schema"`. Use it to tell the schema formats apart. | `"openapi"` |

The chunker finds the `source_url` of a chunk by matching the `llms-full.txt` content to the companion `llms.txt` index of each source. It checks each match against the H1 title of the page. For details, see [Document boundaries and page URLs](chunking.md#document-boundaries-and-page-urls).

To link to a section, join the two fields as `{SOURCE_URL}#{SECTION_ANCHOR}`. Section anchors are on by default. To turn them off, set `section_anchor_style: none` in `.opencrane/config.yaml`. To change how OpenCrane builds an anchor from a heading, override `section_anchor_for(self, heading)` on your `OpenCraneConfig` subclass in `.opencrane/extensions.py`. OpenCrane loads that file only when `.opencrane/config.yaml` sets `extensions: extensions.py`, and the class must be named `Config`.

## Hierarchical navigation metadata

The following fields describe where a chunk sits in a page or in a YAML tree:

| Field | Type | Description | Example |
|---|---|---|---|
| `breadcrumb_path` | string, optional | Location of the chunk. Prose chunks use `page title > section`. List item and table row chunks use the heading ancestry, joined by ` > `. CRD, OpenAPI, and JSON Schema chunks use a dot-separated path with array indices. Code and generic YAML chunks have no breadcrumb. Prose chunks whose page is not in the `llms.txt` index, and table rows with no heading above them, have none either. | Prose: `"Setup Guide > Prerequisites"`<br>CRD: `"spec.versions[0].schema.openAPIV3Schema.properties.spec.replicas"`<br>OpenAPI: `"paths./users/{id}.get"`<br>JSON Schema: `"properties.config.properties.database"` |
| `logical_parent` | string | Dot-separated path of the parent node. It does not always equal `breadcrumb_path` without its final segment. A top-level CRD property keeps the trailing `properties` segment, and a top-level JSON Schema property has the parent `"root"`. Use it to find sibling chunks and to build a tree view. | For `spec.replicas`: `"spec.versions[0].schema.openAPIV3Schema.properties.spec.properties"`<br>For `paths./users.get`: `"paths./users"` |
| `neighbor_chunks` | array of chunk IDs | The `chunk_id` values of the chunks that share the same `logical_parent`. An empty array means that the chunk is the only child of its parent. Use it to fetch related properties for more context. | For `spec.replicas`, the ID of the `spec.image` chunk |

## CRD metadata

Chunks of Kubernetes CRDs, with `chunk_type: "crd_definition"`, carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `crd_kind` | string | Kubernetes resource kind. Use it to filter chunks by resource type. | `"MyResource"`, `"Certificate"` |
| `crd_api_version` | string | Full API group and version, in the format `{GROUP}/{VERSION}`. Use it to look up a property in one API version. | `"mygroup.example.com/v1"` |
| `crd_version` | string | Version identifier only. Use it to filter chunks by version. | `"v1"`, `"v1alpha1"`, `"v1beta1"` |
| `crd_property_path` | string | Short property path that starts at `spec.`. For a recursively split property, it shows the full nested path. Use it to show a short path in RAG responses. | Top-level: `"spec.replicas"`<br>Nested: `"spec.config.database"`<br>Array items: `"spec.volumes.items.name"` |

## OpenAPI metadata

Chunks of OpenAPI specifications, with `chunk_type: "openapi_spec"`, carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `openapi_version` | string | OpenAPI specification version. Use it to tell OpenAPI 3.0 and 3.1 content apart. | `"3.0.1"`, `"3.1.0"` |
| `openapi_element` | string, enum | Top-level element type: `"info"`, `"servers"`, `"security"`, `"tags"`, `"paths"`, or `"components"`. Use it to filter chunks by element type. | `"paths"` |
| `server_url` | string, optional | Server URL. Only server chunks have it. | `"https://api.example.com/v1"` |
| `endpoint_path` | string, optional | Endpoint path. Only path operation chunks have it. | `"/users/{id}/settings"` |
| `http_method` | string, optional | HTTP method, such as `"get"`, `"post"`, `"put"`, `"delete"`, or `"patch"`. Only path operation chunks have it. | `"get"` |
| `component_type` | string, optional | Component type, such as `"schemas"`, `"securitySchemes"`, `"responses"`, or `"parameters"`. Only component chunks have it. | `"schemas"` |
| `schema_name` | string, optional | Schema name. Only schema component chunks have it. | `"User"`, `"Order"`, `"ErrorResponse"` |
| `security_scheme_name` | string, optional | Security scheme name. Only security scheme component chunks have it. | `"ApiKeyAuth"` |
| `property_name` | string, optional | Property name. Only chunks of recursively split schema properties have it. | `"email"`, `"profile"`, `"settings"` |
| `property_path` | string, optional | Dot-separated path within the schema. Only chunks of recursively split schema properties have it. | `"User.profile.address"`, `"Order.items.quantity"` |

## JSON Schema metadata

Chunks of JSON Schema documents, with `chunk_type: "json_schema"`, carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `schema_version` | string | JSON Schema draft version. Use it to parse the schema with the correct draft. | `"https://json-schema.org/draft/2020-12/schema"` |
| `schema_id` | string, optional | Schema identifier from the `$id` field. | `"https://example.com/schemas/user.json"` |
| `schema_title` | string, optional | Schema title from the root `title` field. | `"User Configuration Schema"` |
| `schema_element` | string, enum | Schema element type: `"root"`, `"properties"`, or `"definitions"`. Use it to filter chunks by element type. | `"properties"` |
| `property_name` | string, optional | Property name. Only property chunks have it. | `"username"`, `"config"`, `"settings"` |
| `property_path` | string, optional | Dot-separated path without the `properties` keywords. Only property chunks have it. Use it to show a short property path. | Simple: `"username"`<br>Nested: `"config.database"`<br>Array items: `"volumes.items.name"` |
| `definition_name` | string, optional | Definition name. Only definition chunks have it. | `"address"`, `"phoneNumber"` |

## List item metadata

A `list_item` chunk holds a single bullet or numbered item of a Markdown list. The chunker stores each item as its own chunk, so semantic search can match one item. The metadata links each item to its list, so you can fetch the full list when you need it.

Chunks with `chunk_type: "list_item"` carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `breadcrumb_path` | string | Headings that the list sits under, joined by ` > `. The chunker also adds it to the chunk content as a `#` line, so the embedding includes the heading context. | `"Migration guide > Upgrade to 1.7"` |
| `list_id` | string | Stable identifier shared by all items of the same list. Pass it to `get_list_members(list_id=...)` to fetch the whole list. A nested list has a different `list_id` from its parent list. | `"9f2c4a7e1b0d3c58"` |
| `list_style` | string, enum | `"ordered"` for a numbered list (`1.`, `2.`), `"unordered"` for a bulleted list (`-`, `*`, `+`). An ordered list is usually a procedure, where the order matters. | `"ordered"` |
| `position` | integer, 1-indexed | Position of the item in its list. Use it to rebuild the list in order. | `1` for the first item |
| `total_siblings` | integer | Number of items in the list, including this item. | `5` |
| `sibling_ids` | array of `chunk_id` strings | The `chunk_id` values of the other items in the same list, in list order. To fetch all items in one call, use `get_list_members(list_id=...)` instead. The array always has `total_siblings - 1` entries. | `["a41e…", "c07b…"]` (shortened) |
| `sibling_previews` | array of strings | Short previews of the other items, in list order. For the length and the cap, see [Previews of list items](#previews-of-list-items). | `["1. Back up the database", "3. Restart the server"]` |
| `parent_item_id` | `chunk_id` string, or null | For a nested item, the `chunk_id` of the item that contains it. The value is `null` at the top level. The parent item belongs to the outer list, so its `list_id` differs from the `list_id` of this item. | `null` |
| `depth` | integer | Nesting level of the item: `0` for a top-level item, `1` for the first nested level, and so on. | `0` |

### Previews of list items

The `sibling_previews` field gives an AI agent a short summary of the other items in the list. With the previews, the agent can decide whether the other items matter, without fetching them. The chunker builds each preview as follows:

- Every preview is at most 30 display characters long.
- An ordered item keeps its `N.` prefix.
- Cut-off previews end with `…`.
- If an item has more paragraphs or code after its first line, its preview ends with a space and `…`.

The array holds at most 15 previews. With more than 15 other items, the array holds the first 15 previews and a 16th entry that reads literally `"... +N more"`, where N is the number of remaining items.

### Search results with several items of one list

The top-ranked search results can contain two or more items with the same `list_id`. In that case, the Model Context Protocol (MCP) `search_docs` tool groups them into a single result, with all matched items inline. The grouped result shows the unmatched items as `sibling_previews`.

## Table row metadata

A `table_row` chunk holds a single data row of a Markdown table. The chunker stores each row as its own chunk, so semantic search can match one row. The metadata links each row to its table, so you can fetch the full table when you need it.

Chunks with `chunk_type: "table_row"` carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `table_id` | string | Stable identifier shared by all `table_row` chunks of the same table. Pass it to `get_table_members(table_id=...)` to fetch the whole table. | `"3f9a1c0b2e7d4a65"` |
| `columns` | array of strings | Column header names, in order, repeated on every row chunk. Use it to read the values of a row without fetching the other rows. | `["Field", "Type", "Description"]` |
| `row_index` | integer, 1-indexed | Position of the row in the table. Use it to rebuild the table in order. | `1` for the first data row |
| `total_rows` | integer | Number of data rows in the table. Use it to show "row 3 of 12" and to decide whether to fetch the full table. | `12` |
| `row_key` | string | Value of the first column of the row. Use it as a short label for the row. | `"replicas"`, if the first column is "Field" |
| `sibling_ids` | array of `chunk_id` strings | The `chunk_id` values of the other rows in the same table, in row order. To fetch all rows in one call, use `get_table_members(table_id=...)` instead. The array always has `total_rows - 1` entries. | `["a41e…", "c07b…"]` (shortened) |
| `sibling_previews` | array of strings | The `row_key` of each other row, shortened, in row order. For the length and the cap, see [Previews of table rows](#previews-of-table-rows). | `["image", "resources"]` |
| `breadcrumb_path` | string, optional | Headings that the table sits under, joined by ` > `. Only a table under one or more headings has it. The chunker adds it to the row content as `# {BREADCRUMB_PATH}`, so each row carries its location. | `"Configuration > Parameters"` |
| `table_caption` | string, optional | Lead-in sentence of the table, which is the last non-blank line before the table. Only a table with a lead-in sentence has it. The chunker adds it to the row content, so the embedding of each row includes it. | `"The following parameters are available:"` |

### Previews of table rows

The `sibling_previews` field gives an AI agent a short summary of the other rows. With the previews, the agent can decide whether it needs `get_table_members`, without fetching each row. Every preview is at most 30 display characters long, and a cut-off preview ends with `…`.

The array holds at most 15 previews. With more than 15 other rows, the array holds the first 15 previews and a 16th entry that reads literally `"... +N more"`, where N is the number of remaining rows.

### Fetch the full table

To fetch all `table_row` chunks of a table, call `get_table_members(table_id=...)`. The tool returns the chunks in `row_index` order. When a search result is a `table_row` chunk, the MCP `search_docs` tool adds a tip that names this tool.

### Search results with several rows of one table

The top-ranked search results can contain two or more rows with the same `table_id`. In that case, the MCP `search_docs` tool groups them into a single result, with all matched rows inline. The grouped result shows the unmatched rows as `sibling_previews`. To retrieve the full table, call `get_table_members(table_id=...)`.

## Programmatic usage examples

The following Python examples use the metadata fields to move between chunks. They apply to CRD, OpenAPI, and JSON Schema chunks, which carry `breadcrumb_path`, `logical_parent`, and `neighbor_chunks`.

### Expand the context with neighbor chunks

The following function fetches the neighbor chunks of a chunk for more context:

```python
from typing import Dict, List
from opencrane.shared.models.chunk import Chunk

def expand_with_neighbors(chunk: Chunk, chunk_db: Dict[str, Chunk]) -> List[Chunk]:
    """Fetch neighbor chunks for additional context."""
    neighbor_ids = chunk.metadata["neighbor_chunks"]
    neighbors = [chunk_db[id] for id in neighbor_ids if id in chunk_db]
    return [chunk] + neighbors
```

### Group chunks by parent

The built-in tree walkers split CRD, OpenAPI, and JSON Schema YAML into chunks. They create a chunk only for each property or element that they do not split. A property that they split gets no chunk of its own. So usually no chunk has a `breadcrumb_path` equal to the `logical_parent` of another chunk, and you cannot walk up to a parent chunk. Group chunks by `logical_parent` instead.

The following function groups chunks by their parent node, for example to build a tree view:

```python
from collections import defaultdict

def group_by_parent(chunks: List[Chunk]) -> Dict[str, List[Chunk]]:
    """Group chunks by their logical_parent, for example to build a tree view."""
    groups: Dict[str, List[Chunk]] = defaultdict(list)
    for chunk in chunks:
        parent = chunk.metadata.get("logical_parent")
        if parent is not None:
            groups[parent].append(chunk)
    return dict(groups)
```

### Rebuild an approximate YAML tree

The following functions rebuild a nested dictionary from chunks by using their breadcrumb paths:

```python
def set_nested_value(target: dict, keys: List[str], value) -> None:
    """Set value at the nested key path, creating dictionaries on the way."""
    for key in keys[:-1]:
        target = target.setdefault(key, {})
    target[keys[-1]] = value

def reconstruct_yaml(chunks: List[Chunk]) -> dict:
    """Reconstruct YAML tree from chunks using breadcrumb paths."""
    result = {}
    for chunk in chunks:
        path = chunk.metadata["breadcrumb_path"]
        set_nested_value(result, path.split("."), chunk.content)
    return result
```

The result is a nested dictionary, not an exact copy of the source YAML:

- List indices such as `versions[0]` stay plain keys.
- A key that contains a dot, such as the OpenAPI path `/v1.0/users`, splits at the dot.
- CRD breadcrumbs leave out every `properties` segment below `spec`.

## MCP server integration

The MCP server uses the metadata fields in the following ways:

| MCP server feature | How it uses the metadata |
|---|---|
| Search tool | Shows `breadcrumb_path` and `section_anchor` with each result. For CRD, OpenAPI, and JSON Schema results, it adds `breadcrumb_path` and `logical_parent` as comments to the content instead. |
| YAML definition tool | Adds `breadcrumb_path` and `logical_parent` as location comments. It also lists up to five `neighbor_chunks` IDs, so the AI agent can fetch them. |

The AI agent receives formatted results from the MCP server, not raw chunks. To learn what a metadata field means, the agent can call the `get_metadata_schema` tool, which returns the schema from `opencrane/mcp/metadata-schema.md`.

## Chunk model definition

For programmatic validation, see the Pydantic model definition in `opencrane/shared/models/chunk.py`.
