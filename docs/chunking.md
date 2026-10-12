# Split documentation into chunks for RAG

The OpenCrane chunker splits documentation into chunks for retrieval-augmented generation (RAG). Each chunk holds one unit of content, such as a section of prose, a code block, a list item, or a table row.

> [!TIP]
> If you write documentation that OpenCrane indexes, see the [authoring guide](authoring-guide.md). It explains how to structure your Markdown so the chunks are high quality and easy to retrieve.

To generate the chunks, run the following command:

```bash
opencrane chunk
```

The command writes the chunks to `.opencrane/chunks.json`. To use a custom configuration class, add the `--config {MODULE}:{CLASS}` option.

## Document boundaries and page URLs

The chunker reads the `llms-full.txt` bundle and its companion `llms.txt` index. For details on the two files, see [Generate llms-full.txt bundles](llms-generation.md). The headings in `llms-full.txt` carry no URLs, so the chunker takes the page `source_url` of each chunk from the index. It matches the bundle content to the index in the following steps:

1. The chunker splits `llms-full.txt` into source blocks on `======` separators. The Nth block matches the Nth `## {SOURCE}` section in `llms.txt`.
2. Within a source block, the chunker splits pages on the `<!-- opencrane:page -->` separator. When the separator is missing, it splits on `#` H1 lines, but not on `#` lines inside fenced code blocks. The separator is an HTML comment, not a line of dashes, so a thematic break such as `---` in page content never splits a page.
3. For each page, the chunker takes the URL from the next entry in the index list of that source. It checks the title of that entry against the leading H1 title of the page, ignoring case and extra whitespace. On a mismatch, it looks ahead in the remaining entries of the same source for a matching title. If no title matches, `source_url` stays unset and the chunker logs a warning.
4. Every chunk produced from the page gets the resolved page URL.

The chunker matches titles within each source only, so the same page title in two sources causes no problems.

The following example shows a page in both input files and part of a chunk that the chunker produces from it:

```text
Input (llms-full.txt):          Input (llms.txt):
  # Setup Guide                   ## my-source
  Paragraph content...            - [Setup Guide](https://docs.example.com/setup)
  ## Prerequisites
  More content...

Output (.opencrane/chunks.json):
  {
    "chunk_type": "prose",
    "metadata": {
      "source_url": "https://docs.example.com/setup",
      ...
    },
    "content": "More content..."
  }
```

When no companion `llms.txt` is present, the chunker uses the URL markers inside the bundle instead. It treats each `### https://...` marker line as a document boundary and takes the source URL from it. An older bundle keeps working this way until you regenerate it with `opencrane llms`.

## Table chunks

Every Markdown table becomes one `table_row` chunk per data row. The chunker renders each row as natural-language `Column: value.` lines. Each row chunk carries the section heading and the lead-in sentence from the source, so search can return the row on its own. Rows link to each other through a shared `table_id` field and through `sibling_ids`, the same way `list_item` chunks do.

To fetch the full table from a row chunk, call the `get_table_members(table_id=...)` Model Context Protocol (MCP) tool with the `table_id` field from the metadata of the row chunk. The call returns all sibling row chunks, ordered by `row_index`.

A table with no heading or lead-in sentence in the source still produces `table_row` chunks, but those chunks have no `breadcrumb_path` or `table_caption` metadata. To make those chunks retrievable by semantic search, add a heading and a lead-in sentence to the source.

The fixture pair `tests/fixtures/markdown_with_table.md` and `tests/fixtures/expected_table_chunks.json` is a generated baseline. It shows the chunks produced for a representative table document. When you change the chunking behavior on purpose, regenerate `expected_table_chunks.json` with `ChunkSerializer.serialize_chunks`.

## Chunking strategies

The chunker uses the strategy pattern to support different content formats. Each processing strategy implements the `ProcessingStrategy` interface, so you can add a new format, such as JSON or XML, without changing the core logic. For a reference implementation, see `CodeChunkingStrategy` in `opencrane/rag/services/code_chunker.py`.

Structured YAML specifications go to tree walkers. A tree walker is a class that walks the YAML tree of one specification format and creates one chunk for each property or element.

The chunker evaluates the following strategies in this order, and the first strategy that matches the content handles it:

| Strategy | Content it handles |
|---|---|
| `YamlChunkingStrategy` | YAML content. Structured YAML specifications, such as Kubernetes CustomResourceDefinitions (CRDs) and OpenAPI specifications, go to tree walkers for structured chunking. Other YAML becomes the generic `yaml_content` chunk type. |
| `CodeChunkingStrategy` | Fenced code blocks, with language detection. The strategy detects CRDs and OpenAPI specifications in YAML code blocks and passes them to the built-in CRD and OpenAPI tree walkers. Fenced `yaml` and `yml` blocks go to `YamlChunkingStrategy` first, which runs every configured tree walker. |
| `TableChunkingStrategy` | Markdown tables. The strategy emits one `table_row` chunk per data row, rendered as natural language and linked to the other rows through `table_id` and `sibling_ids`. It passes regions that are not tables to the list and prose strategies. |
| `ListChunkingStrategy` | Markdown lists. The strategy emits one chunk per list item. |
| `ProseChunkingStrategy` | Markdown and text with hierarchical headings. This is the fallback strategy. |

## Chunk data model

Each chunk has a set of top-level fields and a `metadata` object. The fields in the `metadata` object depend on the chunk type. For the list item and table row fields, see [Chunk metadata schema](metadata-schema.md).

### Top-level fields

Every chunk has the following top-level fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `chunk_id` | string | Unique identifier of the chunk, as a 64-character hexadecimal string. OpenCrane builds it from a hash of the chunk content, source file, chunk type, and metadata, so the same input produces the same ID on every run. Milvus uses it as the primary key. | `"195c9565…"` (shortened) |
| `chunk_type` | string, enum | Semantic type of the chunk content. Use it to route the chunk to the matching processing logic. For the values, see [Chunk types](#chunk-types). | `"prose"` |
| `content` | string or object | The chunk content. Prose, code, generic YAML, list item, and table row chunks store a string. CRD, OpenAPI, and JSON Schema chunks store a JSON object or array parsed from the YAML. | `"Run the following command to install the server."` |
| `source_file` | string | Path to the source file, relative to the project root. This is usually the `llms-full.txt` file. Use it to trace a chunk back to its file for debugging and filtering. | `"llmstxt/llms-full.txt"` |
| `source_name` | string, optional | Path key of the source under `sources` in `.opencrane/config.yaml`. The chunker matches the `metadata.source_url` of the chunk against the `url` and `docs_url` of each source, and the longest match wins. The value is `null` when no source matches. The `source_names` parameter of `search_docs` filters on this field. | `"MicrosoftDocs/microsoft-style-guide"` |
| `token_count` | integer | Number of tokens in the chunk content, counted with the `cl100k_base` encoding of tiktoken. Use it to check chunk size limits and to estimate context window usage. | `412` |

### Chunk types

The `chunk_type` field takes one of the following values:

| Value | Content |
|---|---|
| `"prose"` | Markdown or text with hierarchical headings |
| `"code_snippet"` | Fenced code blocks, with language detection |
| `"crd_definition"` | Properties of a Kubernetes CRD |
| `"openapi_spec"` | Elements of an OpenAPI specification |
| `"json_schema"` | Properties of a JSON Schema definition |
| `"yaml_content"` | Generic YAML configuration that is not a recognized structured format |
| `"list_item"` | A single Markdown list item |
| `"table_row"` | A single data row of a Markdown table |

### Universal metadata

The `metadata` object of any chunk type can carry the following fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `source_url` | string, optional | Link to the documentation page that the chunk came from. The chunker finds it through the `llms.txt` index, as described in [Document boundaries and page URLs](#document-boundaries-and-page-urls). Use it to link RAG responses to the source page. | `"https://docs.example.com/configuration"` |
| `section_anchor` | string, optional | In-page anchor of the section that the chunk came from. A direct section link is `{SOURCE_URL}#{SECTION_ANCHOR}`. Only prose, list item, and table row chunks that have a `source_url` and sit under a heading of level two or deeper have it. To turn anchors off, set `section_anchor_style: none` in `.opencrane/config.yaml`. | `"prerequisites"` |
| `original_format` | string, optional | Original format of the content. Only CRD, OpenAPI, and JSON Schema chunks have it. Use it to choose the output format when you rebuild the YAML from chunks. | `"yaml"` |
| `schema_type` | string, enum, optional | Schema category of YAML content: `"k8s_crd"`, `"openapi"`, or `"json_schema"`. Only CRD, OpenAPI, and JSON Schema chunks have it. Use it to tell the schema formats apart. | `"k8s_crd"` |

### Prose chunks

Prose chunks (`chunk_type: "prose"`) carry the following metadata field:

| Field | Type | Description | Example |
|---|---|---|---|
| `breadcrumb_path` | string, optional | Location of the chunk in the page, as `page title > section`. The section is the first heading of level two or deeper in the chunk. When the chunk has no such heading, the value is only the page title. Only chunks whose `source_url` is listed in the `llms.txt` index have it. | `"Setup Guide > Prerequisites"` |

### Code chunks

Code chunks (`chunk_type: "code_snippet"`) carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `language` | string | Programming language of the code block, taken from the language identifier of the fenced code block, such as `` ```python ``. Every code chunk has it, because chunk validation requires it. Use it to filter code by language. | `"python"` |
| `tab_value` | string, optional | Tab identifier, taken from the `value` attribute of the `<Tab>` component. Only a custom processing strategy sets it. The built-in strategies do not. | `"helm"` |
| `tab_label` | string, optional | Tab label, taken from the `label` attribute of the `<Tab>` component. Only a custom processing strategy sets it. The built-in strategies do not. | `"Helm"` |

### CRD chunks

The chunker splits CRDs (`chunk_type: "crd_definition"`) by property. It splits a property further only when the property exceeds 800 tokens. The following table shows how the chunker handles each `spec.properties` field:

| Property size and structure | Result |
|---|---|
| 800 tokens or fewer | One chunk with the nested content |
| More than 800 tokens, with nested `properties` | The chunker recurses into the nested properties and creates separate chunks |
| More than 800 tokens, with `items.properties` (an array) | The chunker recurses into the array item properties and creates separate chunks |
| More than 800 tokens, with no structure to split | One chunk, for example for a map with `additionalProperties` |

When the chunker splits a property, the property itself gets no chunk of its own. The following table shows examples of the result:

| Property | Size and structure | Chunks |
|---|---|---|
| `spec.replicas` | 50 tokens | One chunk with the full definition |
| `spec.config` | 1,200 tokens, nested properties | Separate chunks for `spec.config.database` and `spec.config.cache` |
| `spec.volumes` | 900 tokens, array items with properties | Separate chunks for `spec.volumes.items.name` and `spec.volumes.items.path` |

The chunker processes all CRD versions. Each version produces separate chunks with `crd_version` metadata.

CRD chunks carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `breadcrumb_path` | string | Location in the YAML tree, as a dot-separated path with array indices. Use it to look up a property. | `"spec.versions[0].schema.openAPIV3Schema.properties.spec.replicas"` |
| `logical_parent` | string | Dot-separated path of the parent node. It does not always equal `breadcrumb_path` without its final segment: a top-level property keeps the trailing `properties` segment. Use it to find sibling chunks. | `"spec.versions[0].schema.openAPIV3Schema.properties.spec.properties"` |
| `neighbor_chunks` | array of chunk IDs | The `chunk_id` values of the chunks that share the same `logical_parent`. The array is empty when the chunk is the only child of its parent. Use it to fetch related properties for more context. | For `spec.replicas`, the ID of the `spec.image` chunk |
| `crd_kind` | string | Kubernetes resource kind. Use it to filter chunks by CRD. | `"MyResource"` |
| `crd_api_version` | string | Full API group and version, in the format `{GROUP}/{VERSION}`. Use it to tell apart API versions of the same resource. | `"mygroup.example.com/v1"` |
| `crd_version` | string | Version identifier only. Use it to filter chunks by CRD version. | `"v1"` |
| `crd_property_path` | string | Property path that starts at `spec.`. For a recursively split property, it includes the full nested path. Use it to show a short property path in RAG responses. | `"spec.config.database"` |

### OpenAPI chunks

The chunker splits OpenAPI specifications (`chunk_type: "openapi_spec"`) by element. It splits a component schema further only when the schema exceeds 800 tokens. The following table shows how the chunker handles each kind of element:

| Element | Result |
|---|---|
| Top-level elements: `info`, `security`, and `tags` | One chunk for each element |
| `servers` | One chunk for each server |
| Path operations, such as GET and POST | A separate chunk for each method |
| Component schema of 800 tokens or fewer | One chunk with the schema as it is |
| Component schema of more than 800 tokens, with nested `properties` | The chunker recurses into the properties and creates separate chunks |
| Component schema of more than 800 tokens, with `items.properties` (an array schema) | The chunker recurses into the array item properties and creates separate chunks |

When the chunker splits a schema, the schema itself gets no chunk of its own. The following table shows examples of the result:

| Element | Size and structure | Chunks |
|---|---|---|
| `components.schemas.User` | 200 tokens | One chunk |
| `components.schemas.Order` | 1,500 tokens, nested properties | Separate chunks for `Order.customer` and `Order.items` |
| Path operation `/users.post` | Large request and response | One chunk, because the chunker never splits an operation |

OpenAPI chunks carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `breadcrumb_path` | string | Location in the OpenAPI tree, as a dot-separated path. Server chunks use an array index, such as `servers[0]`. Use it to look up an element. | `"paths./groups/{id}/access_requests.get"` |
| `logical_parent` | string | Parent node in the tree. Use it to find sibling chunks. `"root"` is the parent of `info`, `security`, and `tags`. `"servers"` is the parent of each server chunk. | `"paths./groups/{id}/access_requests"`, the parent of its GET and POST operations |
| `neighbor_chunks` | array of chunk IDs | The `chunk_id` values of the chunks that share the same `logical_parent`. The array is empty when the chunk is the only child, for example a single server. Use it to fetch related API elements. | For the GET operation, the ID of the POST chunk at the same path |
| `openapi_version` | string | OpenAPI specification version. Use it to tell OpenAPI 3.0 and 3.1 content apart. | `"3.1.0"` |
| `openapi_element` | string, enum | Top-level element type: `"info"`, `"servers"`, `"security"`, `"tags"`, `"paths"`, or `"components"`. Use it to filter chunks by element. | `"paths"` |
| `server_url` | string, optional | Server base URL. Only server chunks have it. | `"https://www.example.com/api/v4"` |
| `endpoint_path` | string, optional | API endpoint path. Only path operation chunks have it. Use it to filter by endpoint. | `"/groups/{id}/access_requests"` |
| `http_method` | string, optional | HTTP method of the operation: `"get"`, `"post"`, `"put"`, `"delete"`, `"patch"`, `"options"`, `"head"`, or `"trace"`. Only path operation chunks have it. | `"get"` |
| `component_type` | string, optional | Component category: `"schemas"`, `"securitySchemes"`, `"responses"`, `"parameters"`, `"examples"`, `"requestBodies"`, `"headers"`, `"links"`, or `"callbacks"`. Only component chunks have it. | `"schemas"` |
| `schema_name` | string, optional | Name of the schema definition. Only schema component chunks have it. Use it to resolve `$ref` links. | `"API_Entities_AccessRequester"` |
| `security_scheme_name` | string, optional | Name of the security scheme. Only security scheme component chunks have it. | `"ApiKeyAuth"` |
| `property_name` | string, optional | Name of the property. Only chunks of recursively split schema properties have it. | `"email"` |
| `property_path` | string, optional | Dot-separated path within the schema. Only chunks of recursively split schema properties have it. | `"User.profile.address"` |

### JSON Schema chunks

The chunker splits JSON Schema documents (`chunk_type: "json_schema"`) by property and definition. It splits a property further only when the property exceeds 800 tokens. The following table shows how the chunker handles each part of the schema:

| Part of the schema | Result |
|---|---|
| Root metadata, such as the title and description | One chunk, if the metadata is present |
| Property of 800 tokens or fewer | One chunk with the property and its nested content |
| Property of more than 800 tokens, with nested `properties` | The chunker recurses into the nested properties |
| Property of more than 800 tokens, with `items.properties` (an array) | The chunker recurses into the array item properties |
| Definitions in `$defs` or `definitions` | The same recursive logic as for properties |

When the chunker splits a property or a definition, the property or definition gets no chunk of its own. The following table shows examples of the result:

| Element | Size and structure | Chunks |
|---|---|---|
| `properties.username` | 30 tokens | One chunk |
| `properties.config` | 1,000 tokens, nested | Separate chunks for `config.database` and `config.cache` |
| `$defs.address` | 900 tokens, array items | Separate chunks for `address.items.street` and `address.items.city` |

JSON Schema chunks carry `breadcrumb_path`, `logical_parent`, and `neighbor_chunks` in the same way as CRD chunks. The root chunk and the top-level properties have the parent `"root"`. JSON Schema chunks also carry the following metadata fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `schema_version` | string | JSON Schema draft version. Use it to parse the schema with the correct draft. | `"https://json-schema.org/draft/2020-12/schema"` |
| `schema_id` | string, optional | Schema identifier from the `$id` field. | `"https://example.com/schemas/user.json"` |
| `schema_title` | string, optional | Schema title from the root `title` field. | `"User Configuration Schema"` |
| `schema_element` | string, enum | Schema element type: `"root"`, `"properties"`, or `"definitions"`. | `"properties"` |
| `property_name` | string, optional | Name of the property. Only property chunks have it. | `"config"` |
| `property_path` | string, optional | Dot-separated path without the `properties` keywords. Only property chunks have it. | `"config.database"` |
| `definition_name` | string, optional | Name of the definition. Only definition chunks have it. | `"address"` |

## Extend the chunker

To extend the chunker, add a processing strategy or a tree walker. A processing strategy adds support for a new content type. A tree walker adds support for a new structured YAML specification.

The following table summarizes the concepts that the extension points rely on:

| Concept | Description |
|---|---|
| Processing strategy | A class that handles one content type, such as YAML, code, or prose. |
| Tree walker | A class that splits one structured YAML format, such as CRDs, OpenAPI, or AsyncAPI, into chunks. |
| Priority order | The order of the strategies in `chunking_strategies`. The first strategy that matches the content handles it. |
| Neighbor relationships | The `neighbor_chunks` links that a tree walker sets between chunks with the same `logical_parent`. |
| Chunk type | The `chunk_type` value of a chunk, such as `asyncapi_spec`, which search can filter on. |

You register both kinds of extension in a configuration class. OpenCrane finds the class in one of two ways:

- If `.opencrane/config.yaml` sets `extensions: extensions.py`, OpenCrane loads `.opencrane/extensions.py`. The class in that file must be named `Config`.
- If you pass the `--config {MODULE}:{CLASS}` option or set the `OPENCRANE_CONFIG` environment variable, OpenCrane imports the class that you name. This class takes precedence over the `extensions` key.

## Add a processing strategy

To add support for a new content type, such as JSON, XML, or a custom Markdown component, complete the steps in this section.

### 1. Create a strategy class

The following example shows a strategy that handles nodes starting with `{{custom}}`:

```python
from pathlib import Path
from typing import List
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.rag.services.utils.chunk_id_generator import generate_unique_chunk_id
from opencrane.shared.models.chunk import Chunk
from opencrane.shared.utils.token_counter import get_token_count

class MyCustomStrategy(ProcessingStrategy):
    def can_process(self, node) -> bool:
        """Check if this strategy can handle the node."""
        return hasattr(node, 'text') and node.text.startswith('{{custom}}')

    def process(self, node, source_file: Path) -> List[Chunk]:
        """Process node into chunks."""
        content = node.text.removeprefix('{{custom}}').strip()
        metadata = {}

        chunk = Chunk(
            chunk_id=generate_unique_chunk_id(content, str(source_file), "prose", metadata),
            content=content,
            source_file=str(source_file),
            chunk_type="prose",
            metadata=metadata,
            token_count=get_token_count(content)
        )
        return [chunk]
```

The `chunk_type` must be one of the values in the `chunk_type` `Literal` in `opencrane/shared/models/chunk.py`. Prose chunks accept only the following metadata keys:

- `source_url`
- `breadcrumb_path`
- `section_anchor`
- `tab_value`
- `tab_label`
- `key`

### 2. Register the strategy

Save the strategy class as `.opencrane/my_strategies.py`, next to `extensions.py`. When OpenCrane loads `extensions.py`, it adds that directory to the Python import path, so the import in the following example works.

The following example registers the strategy in your configuration class and places it second in the list:

```python
# .opencrane/extensions.py
from opencrane import OpenCraneConfig
from opencrane.rag.services.yaml_chunker import YamlChunkingStrategy
from opencrane.rag.services.code_chunker import CodeChunkingStrategy
from opencrane.rag.services.table_chunker import TableChunkingStrategy
from opencrane.rag.services.list_chunker import ListChunkingStrategy
from opencrane.rag.services.prose_chunker import ProseChunkingStrategy
from my_strategies import MyCustomStrategy

class Config(OpenCraneConfig):
    chunking_strategies = [
        YamlChunkingStrategy(),   # Priority 1: YAML (delegates to tree walkers)
        MyCustomStrategy(),       # Priority 2: Your custom strategy
        CodeChunkingStrategy(),   # Priority 3: Fenced code blocks
        TableChunkingStrategy(),  # Priority 4: Markdown tables
        ListChunkingStrategy(),   # Priority 5: Markdown lists
        ProseChunkingStrategy(),  # Priority 6: Prose (fallback)
    ]
```

> [!IMPORTANT]
> The order of the strategies matters, because the first strategy that matches the content handles it. Place specific strategies before general ones.

The chunker uses your strategy the next time you run `opencrane chunk`.

## Add a tree walker for a YAML specification

To add support for a new YAML-based specification, such as AsyncAPI or AWS CloudFormation templates, complete the steps in this section. Steps 1 and 4 change the OpenCrane package itself, not only your configuration.

The walker runs on every YAML block that `YamlChunkingStrategy` handles, including fenced `yaml` and `yml` blocks and unlabeled blocks that parse as YAML.

### 1. Add the chunk type to the chunk model

Add the new chunk type, for example `"asyncapi_spec"`, to the `chunk_type` `Literal` in `opencrane/shared/models/chunk.py`. Without it, the chunk fails validation when the walker creates it.

### 2. Create a tree walker class

The following example walks AsyncAPI specifications:

```python
from typing import List, Dict, Any
from opencrane.walkers import YamlTreeWalker
from opencrane.shared.models.chunk import Chunk
from opencrane.shared.utils.token_counter import get_token_count
import yaml

class AsyncAPITreeWalker(YamlTreeWalker):
    """Walk AsyncAPI specification trees and generate element-based chunks."""

    @classmethod
    def can_handle(cls, doc: dict) -> bool:
        """Return True for AsyncAPI documents."""
        return "asyncapi" in doc and "channels" in doc

    def __init__(self, yaml_dict: Dict[str, Any], source_url: str,
                 source_file=None, original_yaml_file: str | None = None):
        """Initialize AsyncAPI tree walker."""
        super().__init__(yaml_dict, source_url, source_file, original_yaml_file)
        self.asyncapi_version = self._extract_asyncapi_version()

    def _extract_asyncapi_version(self) -> str:
        """Extract AsyncAPI version from spec."""
        return self.yaml_dict.get("asyncapi", "unknown")

    def walk(self) -> List[Chunk]:
        """Walk AsyncAPI tree and generate chunks for each element."""
        self.chunks = []

        # Process top-level elements
        if "info" in self.yaml_dict:
            self._process_info(self.yaml_dict["info"])

        if "channels" in self.yaml_dict:
            self._process_channels(self.yaml_dict["channels"])

        if "components" in self.yaml_dict:
            self._process_components(self.yaml_dict["components"])

        # Assign neighbor relationships
        self._assign_neighbor_relationships()

        return self.chunks

    def _process_info(self, info: Dict[str, Any]) -> None:
        """Process info section."""
        yaml_str = yaml.dump(info, default_flow_style=False)
        token_count = get_token_count(yaml_str)
        source_file = self.source_file or self.source_url
        metadata = {
            "source_url": self.source_url,
            "breadcrumb_path": "info",
            "logical_parent": "root",
            "neighbor_chunks": [],
            "original_format": "yaml",
            "schema_type": "asyncapi",
            "asyncapi_version": self.asyncapi_version,
            "asyncapi_element": "info"
        }

        chunk = Chunk(
            chunk_id=self._generate_chunk_id(
                content=info,
                chunk_type="asyncapi_spec",
                metadata=metadata,
                source_file=source_file
            ),
            content=info,
            source_file=source_file,
            chunk_type="asyncapi_spec",
            token_count=token_count,
            metadata=metadata
        )

        self.chunks.append(chunk)

    def _process_channels(self, channels: Dict[str, Any]) -> None:
        """Process channels section (message topics/queues)."""
        # Similar implementation to _process_info
        # Create chunks for each channel
        pass

    def _process_components(self, components: Dict[str, Any]) -> None:
        """Process reusable components (schemas, messages, and so on)."""
        # Similar implementation
        pass

    def _assign_neighbor_relationships(self) -> None:
        """Identify and assign sibling relationships."""
        # Group chunks by logical_parent
        parent_groups: Dict[str, List[Chunk]] = {}
        for chunk in self.chunks:
            parent = chunk.metadata.get("logical_parent", "")
            if parent not in parent_groups:
                parent_groups[parent] = []
            parent_groups[parent].append(chunk)

        # Set neighbors for each group
        for parent, siblings in parent_groups.items():
            if len(siblings) <= 1:
                continue
            for chunk in siblings:
                neighbor_ids = [s.chunk_id for s in siblings if s.chunk_id != chunk.chunk_id]
                chunk.metadata["neighbor_chunks"] = neighbor_ids
```

### 3. Register the walker

Save the walker class as `.opencrane/my_walkers.py`, next to `extensions.py`.

The following example adds the walker after the built-in walkers in your configuration class:

```python
# .opencrane/extensions.py
from opencrane import OpenCraneConfig
from my_walkers import AsyncAPITreeWalker

class Config(OpenCraneConfig):
    yaml_tree_walkers = [
        *OpenCraneConfig.yaml_tree_walkers,
        AsyncAPITreeWalker,
    ]
```

### 4. Document the chunk type

Document the chunk type in the following places:

- Add the new chunk type and its metadata fields to [Chunk metadata schema](metadata-schema.md).
- Add the same chunk type and fields to `opencrane/mcp/metadata-schema.md`, which the `get_metadata_schema` MCP tool returns.
- Add the chunk type to `_CHUNK_TYPE_SECTION_HEADINGS` in `opencrane/mcp/server.py`, so `get_metadata_schema(chunk_type=...)` returns its section.

The chunker uses your walker the next time you run `opencrane chunk`.
