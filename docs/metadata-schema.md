# Chunk metadata schema

This page lists the metadata fields of each chunk type. Your code can use these fields to move between related chunks and to add context to a search result. Retrieval-augmented generation (RAG) responses use them to link to the source page. For the top-level fields of a chunk, such as `chunk_id` and `content`, see [Chunk data model](chunking.md#chunk-data-model).

## Universal metadata

Chunks of all types can carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `source_url` | string, optional | Link to the documentation page that the chunk came from, without an in-page anchor. Use it to link RAG responses to the source page. A CustomResourceDefinition (CRD), OpenAPI, or JSON Schema chunk without a page URL holds the path of the source file instead. | `"https://docs.example.com/config"` |
| `section_anchor` | string, optional | In-page anchor of the section that the chunk came from. Only chunks with a `source_url` have it. A prose chunk takes it from the first heading of level two or deeper in its content. A list item or table row chunk takes it from the last segment of its `breadcrumb_path`, when the breadcrumb has two or more segments. | `"prerequisites"` |
| `original_format` | string, optional | Original format of the content. Only CRD, OpenAPI, and JSON Schema chunks have it. Use it to convert the content back to that format, for example from a dictionary to YAML. | `"yaml"` |
| `schema_type` | string, enum, optional | Schema category of YAML content: `"k8s_crd"`, `"openapi"`, or `"json_schema"`. Only CRD, OpenAPI, and JSON Schema chunks have it. | `"openapi"` |
| `root_identity` | object, optional | Identity of a Kubernetes resource: its `apiVersion`, `kind`, `name`, and `namespace`. Only `yaml_content` chunks of a YAML document with `apiVersion`, `kind`, and `metadata.name` have it. | `{"apiVersion": "v1", "kind": "ConfigMap", "name": "app-config", "namespace": null}` |

The chunker finds the `source_url` of a chunk by matching the `llms-full.txt` content to the companion `llms.txt` index. For details, see [Document boundaries and page URLs](chunking.md#document-boundaries-and-page-urls).

To link to a section, join the two fields as `{SOURCE_URL}#{SECTION_ANCHOR}`. To turn section anchors off or change how OpenCrane builds them, see [Section anchors](../README.md#section-anchors).

## Hierarchical navigation metadata

The following fields describe where a chunk sits in a page or in a YAML tree:

| Field | Type | Description | Example |
|---|---|---|---|
| `breadcrumb_path` | string, optional | Location of the chunk. Prose chunks use `page title > section`, where the section is the first heading of level two or deeper in the chunk. A prose chunk without such a heading gets only the page title. A prose chunk whose page is not in the `llms.txt` index gets no breadcrumb. List item and table row chunks use the headings that they sit under on the page, joined by ` > `. CRD, OpenAPI, and JSON Schema chunks use a dot-separated path with array indices. Code and generic YAML chunks have no breadcrumb. | Prose: `"Setup Guide > Prerequisites"`<br>CRD: `"spec.versions[0].schema.openAPIV3Schema.properties.spec.replicas"`<br>OpenAPI: `"paths./users/{id}.get"`, `"servers[0]"`<br>JSON Schema: `"properties.config.properties.database"` |
| `logical_parent` | string | Dot-separated path of the parent node. It does not always equal `breadcrumb_path` without its final segment. A top-level CRD property keeps the trailing `properties` segment. The parent is `"root"` for the OpenAPI `info`, `security`, and `tags` chunks, and for the JSON Schema root chunk and top-level properties. It is `"servers"` for OpenAPI server chunks, and `"$defs"` or `"definitions"` for JSON Schema definitions. Use it to find sibling chunks and to build a tree view. | For `spec.replicas`: `"spec.versions[0].schema.openAPIV3Schema.properties.spec.properties"`<br>For `paths./users.get`: `"paths./users"` |
| `neighbor_chunks` | array of chunk IDs | The `chunk_id` values of the chunks that share the same `logical_parent`. An empty array means that the chunk is the only child of its parent. Use it to fetch related properties for more context. | For `spec.replicas`, the ID of the `spec.image` chunk |

## Code snippet metadata

Chunks with `chunk_type: "code_snippet"` carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `language` | string | Language identifier of the fenced code block, or `"unknown"` for a block without one. Every code chunk has it. | `"python"` |
| `is_complete` | boolean | Always `true`. | `true` |
| `tab_value`, `tab_label` | string, optional | The `value` and `label` attributes of a `<Tab>` component. Only a custom processing strategy sets them. | `"helm"`, `"Helm"` |

## CRD metadata

Chunks of Kubernetes CRDs, with `chunk_type: "crd_definition"`, carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `crd_kind` | string | Kubernetes resource kind, from `spec.names.kind`. Use it to filter chunks by resource type. | `"MyResource"`, `"Certificate"` |
| `crd_api_version` | string | API group and version, in the format `{GROUP}/{VERSION}`. Use it to look up a property in one API version. | `"mygroup.example.com/v1"` |
| `crd_version` | string | Version name only. Use it to filter chunks by version. The `breadcrumb_path` and `logical_parent` use the index of the version instead, for example `versions[1]`. | `"v1"`, `"v1alpha1"`, `"v1beta1"` |
| `crd_property_path` | string | Short property path that starts at `spec.`. For a recursively split property, it shows the full nested path. Use it to show a short path in RAG responses. | Top-level: `"spec.replicas"`<br>Nested: `"spec.config.database"`<br>Array items: `"spec.volumes.items.name"` |

## OpenAPI metadata

Chunks of OpenAPI specifications, with `chunk_type: "openapi_spec"`, carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `openapi_version` | string | Value of the `openapi` or `swagger` field. Use it to tell OpenAPI versions apart. | `"3.0.1"`, `"3.1.0"` |
| `openapi_element` | string, enum | Top-level element type: `"info"`, `"servers"`, `"security"`, `"tags"`, `"paths"`, or `"components"`. Use it to filter chunks by element type. | `"paths"` |
| `server_url` | string, optional | Server URL. Only server chunks have it. | `"https://api.example.com/v1"` |
| `endpoint_path` | string, optional | Endpoint path. Only path operation chunks have it. | `"/users/{id}/settings"` |
| `http_method` | string, optional | HTTP method: `"get"`, `"post"`, `"put"`, `"delete"`, `"patch"`, `"options"`, `"head"`, or `"trace"`. Only path operation chunks have it. | `"get"` |
| `component_type` | string, optional | Component type: `"schemas"`, `"securitySchemes"`, `"responses"`, `"parameters"`, `"examples"`, `"requestBodies"`, `"headers"`, `"links"`, or `"callbacks"`. Only component chunks have it. | `"schemas"` |
| `schema_name` | string, optional | Schema name. Only schema component chunks have it, including the chunks of a split schema. Use it to resolve `$ref` links. | `"User"`, `"Order"`, `"ErrorResponse"` |
| `security_scheme_name` | string, optional | Security scheme name. Only security scheme component chunks have it. | `"ApiKeyAuth"` |
| `property_name` | string, optional | Property name. Only chunks of recursively split schema properties have it. | `"email"`, `"profile"`, `"settings"` |
| `property_path` | string, optional | Dot-separated path within the schema. Only chunks of recursively split schema properties have it. | `"User.profile.address"`, `"Order.items.quantity"` |

## JSON Schema metadata

Chunks of JSON Schema documents, with `chunk_type: "json_schema"`, carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `schema_version` | string | Value of the `$schema` field, or `"unknown"` without one. Use it to parse the schema with the correct draft. | `"https://json-schema.org/draft/2020-12/schema"` |
| `schema_id` | string, optional | Schema identifier from the `$id` or `id` field. | `"https://example.com/schemas/user.json"` |
| `schema_title` | string, optional | Schema title from the root `title` field. | `"User Configuration Schema"` |
| `schema_element` | string, enum | Schema element type: `"root"`, `"properties"`, or `"definitions"`. The children of a split definition are `"properties"` chunks. Use it to filter chunks by element type. | `"properties"` |
| `property_name` | string, optional | Property name. Only property chunks have it. | `"username"`, `"config"`, `"settings"` |
| `property_path` | string, optional | Dot-separated path without the `properties` keywords. Only property chunks have it. Use it to show a short property path. | Simple: `"username"`<br>Nested: `"config.database"`<br>Array items: `"volumes.items.name"` |
| `definition_name` | string, optional | Definition name. Only definition chunks have it. | `"address"`, `"phoneNumber"` |

## Prose navigation metadata

Chunks with `chunk_type: "prose"` carry the following navigation fields, unless `prose_navigation` is off in the configuration class:

| Field | Type | Description | Example |
|---|---|---|---|
| `heading_path` | string, optional | Section heading and the headings above it, from the page title down, joined by ` > `. A chunk before the first heading of the page has none. | `"Setup Guide > Install > Prerequisites"` |
| `clause_id` | string, optional | Clause number at the start of the section heading, such as a dotted number or an annex. Pass it to `get_section(clause_id=...)`. | `"5.4.1.2a"`, `"Annex C"` |
| `parent_chunk_id` | `chunk_id` string, or null | Chunk of the nearest enclosing section, or `null` at the top level. | `null` |
| `position` | integer, 1-indexed | Position of the chunk among the prose chunks of its page. | `1` |
| `prev_chunk_id`, `next_chunk_id` | `chunk_id` string, or null | Previous and next prose chunk of the page, or `null` at the page edges. | `"a41e…"` (shortened) |

A chunk without a leading heading continues the previous section and repeats its `heading_path`, `clause_id`, and `parent_chunk_id`.

To set the clause format, see [Section navigation and clause IDs](../README.md#section-navigation-and-clause-ids).

## List item metadata

A `list_item` chunk holds a single bullet or numbered item of a Markdown list. The chunker stores each item as its own chunk, so semantic search can match one item. The chunk of a top-level item holds the item text up to its first nested item. The chunk leaves out the nested items and any text after them. The chunk of a nested item holds only the first line of each parent item and of the item itself. The metadata links each item to its list, so you can fetch the full list when you need it.

Chunks with `chunk_type: "list_item"` carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `breadcrumb_path` | string | Headings that the list sits under, joined by ` > `, or an empty string when no heading precedes the list. The chunker also adds it to the chunk content as a `#` line, so the embedding includes the heading context. | `"Migration guide > Upgrade to 1.7"` |
| `list_id` | string | Stable identifier shared by all items of the same list. Lists on different pages with the same `breadcrumb_path` can share a `list_id`. Pass it to `get_list_members(list_id=...)` to fetch the whole list. A nested list has a different `list_id` from its parent list. | `"9f2c4a7e1b0d3c58"` |
| `list_style` | string, enum | `"ordered"` for a numbered item (`1.`), `"unordered"` for a bulleted item (`-`, `*`, `+`). An ordered list is usually a procedure, where the order matters. | `"ordered"` |
| `position` | integer, 1-indexed | Position of the item in its list. Use it to rebuild the list in order. | `1` for the first item |
| `total_siblings` | integer | Number of items in the list, including this item. | `5` |
| `sibling_ids` | array of `chunk_id` strings | The `chunk_id` values of the other items in the same list, in list order. To fetch all items in one call, use `get_list_members(list_id=...)` instead. The array always has `total_siblings - 1` entries. | `["a41e…", "c07b…"]` (shortened) |
| `sibling_previews` | array of strings | Short previews of the other items, in list order. For the length and the cap, see [Previews of list items](#previews-of-list-items). | `["1. Back up the database", "3. Restart the server"]` |
| `parent_item_id` | `chunk_id` string, or null | For a nested item, the `chunk_id` of the item that contains it. The value is `null` at the top level. The parent item belongs to the outer list, so its `list_id` differs from the `list_id` of this item. | `null` |
| `depth` | integer | Nesting level of the item: `0` for a top-level item, `1` for the first nested level, and so on. | `0` |

### Previews of list items

The `sibling_previews` field gives an AI agent a short summary of the other items in the list. With the previews, the agent can decide whether the other items matter, without fetching them. The chunker builds each preview from the first line of an item:

- An ordered item keeps its `N.` prefix.
- A first line longer than 30 characters, counting the prefix, is cut to 30 characters that end with `…`.
- A shorter first line of an item with more lines after it ends with a space and `…`.

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
| `total_rows` | integer | Number of data rows in the table. Use it to decide whether to fetch the full table. | `12` |
| `row_key` | string | Value of the first cell of the row. Use it as a short label for the row. | `"replicas"`, if the first column is "Field" |
| `sibling_ids` | array of `chunk_id` strings | The `chunk_id` values of the other rows in the same table, in row order. To fetch all rows in one call, use `get_table_members(table_id=...)` instead. The array always has `total_rows - 1` entries. | `["a41e…", "c07b…"]` (shortened) |
| `sibling_previews` | array of strings | The `row_key` of each other row, shortened, in row order. For the length and the cap, see [Previews of table rows](#previews-of-table-rows). | `["image", "resources"]` |
| `breadcrumb_path` | string, optional | Headings that the table sits under on the page, joined by ` > `. Only a table under one or more headings has it. The chunker adds it to the row content as `# {BREADCRUMB_PATH}`, so each row carries its location. | `"Configuration > Parameters"` |
| `table_caption` | string, optional | Lead-in sentence of the table: the last non-blank line before the table, without a list marker. Only a table whose preceding line is text, not a heading, has it. The chunker adds it to the row content, so the embedding of each row includes it. | `"The following parameters are available:"` |

### Previews of table rows

The `sibling_previews` field gives an AI agent a short summary of the other rows. With the previews, the agent can decide whether it needs `get_table_members`, without fetching each row. Every preview is at most 30 characters long, and a cut-off preview ends with `…`.

The array holds at most 15 previews. With more than 15 other rows, the array holds the first 15 previews and a 16th entry that reads literally `"... +N more"`, where N is the number of remaining rows.

### Search results with several rows of one table

The top-ranked search results can contain two or more rows with the same `table_id`. In that case, the MCP `search_docs` tool groups them into a single result, with all matched rows inline. The grouped result shows the unmatched rows as `sibling_previews`.

## Custom chunk type metadata

A chunk with a custom chunk type carries the metadata fields that your strategy or walker sets. OpenCrane does not check these fields. To link the chunk to its source page, set the universal `source_url` field, as the built-in strategies do. For the naming rules of a custom chunk type, see [Custom chunk types](chunking.md#custom-chunk-types).

## Programmatic usage examples

The following Python examples use the metadata fields to move between chunks. They apply to CRD, OpenAPI, and JSON Schema chunks, which carry `breadcrumb_path`, `logical_parent`, and `neighbor_chunks`. The Pydantic model that validates chunks is in `opencrane/shared/models/chunk.py`.

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

A property or schema that the tree walkers split gets no chunk of its own. So usually no chunk has a `breadcrumb_path` equal to the `logical_parent` of another chunk, and you cannot walk up to a parent chunk. Group chunks by `logical_parent` instead.

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
| Section tool | Finds a prose section by `chunk_id` or `clause_id`, and uses `parent_chunk_id` and `position` to return it with its sub-sections. |

The AI agent receives formatted results from the MCP server, not raw chunks. To learn what a metadata field means, the agent can call the `get_metadata_schema` tool, which returns the schema from `opencrane/mcp/metadata-schema.md`.
