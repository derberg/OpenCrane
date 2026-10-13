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
2. Within a source block, the chunker splits pages on the `<!-- opencrane:page -->` separator. When the separator is missing, it splits on `#` H1 lines, but not on `#` lines inside fenced code blocks. The separator is an HTML comment, so a thematic break such as `---` in page content never splits a page.
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
      "breadcrumb_path": "Setup Guide > Prerequisites",
      "section_anchor": "prerequisites",
      ...
    },
    "content": "## Prerequisites\nMore content..."
  }
```

The chunker uses the URL markers inside the bundle instead of the index in the following cases:

- No companion `llms.txt` is present, for example in a bundle that an older OpenCrane version built. Regenerate the bundle with `opencrane llms` to get an index.
- The number of source blocks in `llms-full.txt` differs from the number of source sections in `llms.txt`. The chunker logs a warning.

In this mode, each URL marker heading, such as `### https://...`, starts a new page, and the chunker takes the source URL from it.

## Prose sections

By default, a prose chunk holds one `#`, `##`, or `###` section with all its deeper headings, and has no size limit. A long section can exceed the input limit of the embedding model, and the model ignores the extra text.

The following variables control how the prose chunker splits text:

| Variable | Default | Description |
|---|---|---|
| `PROSE_SPLIT_HEADING_DEPTH` | `3` | Sets the deepest heading level that starts a new chunk. A deeper heading stays in the chunk of the heading above it. For example, with `3`, a `####` section is part of its `###` chunk. Raise the value to make search return smaller sections of deeply nested docs. Lower it to keep more context in each result. Documents converted from other formats can have headings seven or eight levels deep, so values up to `8` are useful. `0` turns off splitting at headings. |
| `PROSE_MAX_CHUNK_TOKENS` | `0` | Sets a token limit for each chunk, as a positive whole number. `0` turns the limit off. Set it below the input limit of your embedding model, so the model reads all of each chunk. OpenCrane counts tokens with the `TOKEN_ENCODING` tiktoken encoding, `cl100k_base` by default, not with the tokenizer of the model, so leave a margin. A section over the limit splits at paragraphs, then at lines, and each chunk repeats the section heading. Lines and code blocks never split. |
| `PROSE_KEEP_HEADING_ONLY_SECTIONS` | `false` | `true` keeps a section that has a heading but no text, when the heading line is 15 characters or longer. Any other value drops such sections. Turn it on when headings carry meaning on their own, such as numbered clauses in a specification, so search can find them. |

The prose chunker always drops a chunk shorter than 15 characters.

The variables do not apply to the text around a Markdown list. The list chunker emits that text as prose chunks without splitting it at headings. See [Chunking strategies](#chunking-strategies).

> [!CAUTION]
> Rebuilding deletes the Milvus collection, and searches fail until the rebuild finishes. Before you rebuild, confirm that `MILVUS_COLLECTION` and the connection variables name the collection that you want to replace.

After you change a variable, run `opencrane chunk` and `opencrane embed` again, then rebuild the Milvus collection as [`opencrane index`](../README.md#index-the-embeddings-in-milvus-with-opencrane-index) describes.

## Table chunks

Every Markdown table becomes one `table_row` chunk for each data row. The chunker renders each row as natural-language `Column: value.` lines and leaves out empty cells. Each row chunk carries the section heading and the lead-in sentence from the source, so search can return the row on its own. For the fields that link the rows of a table, see [Table row metadata](metadata-schema.md#table-row-metadata).

A table ends at the first row whose number of cells differs from the header. The chunker splits cells at every `|` except an escaped `\|` and a `|` inside backticks, and stores `\|` as `|`.

A table with no heading or lead-in sentence still produces `table_row` chunks, but those chunks have no `breadcrumb_path` or `table_caption` metadata. To make them retrievable by semantic search, add a heading and a lead-in sentence to the source.

## Chunking strategies

Before the strategies run, the chunker splits each page at every fenced code block outside a list or a `<Tabs>` block, and keeps each `<Tabs>` block whole. A code block inside a list item stays in that item. The chunker then processes each code block, each `<Tabs>` block, and each stretch of text between them on its own. Each stretch of text keeps the headings that it sits under, so a list or table after a code block gets its full breadcrumb. It also takes fenced `yaml` and `yml` blocks out of the text first, when the opening fence is unindented and has nothing after the language. Structured YAML specifications go to tree walkers. A tree walker is a class that walks the YAML tree of one specification format and creates one chunk for each property or element.

The chunker evaluates the following strategies in this order. The first strategy that matches the content and returns chunks handles it:

| Strategy | Content it handles |
|---|---|
| `YamlChunkingStrategy` | Fenced `yaml` and `yml` blocks, and fenced `json` blocks that a configured tree walker accepts. The strategy skips fenced blocks in any other language. For unfenced text and for fenced blocks without a language, the strategy reads the first ten lines that are not blank or comments. It handles the text when at least two of those lines look like `key: value` pairs. Structured YAML specifications, such as Kubernetes CustomResourceDefinitions (CRDs) and OpenAPI specifications, go to the first configured tree walker whose `can_handle` method accepts them. Other YAML becomes one `yaml_content` chunk. |
| `CodeChunkingStrategy` | Fenced code blocks, with the language from the opening fence. The strategy passes CRDs and OpenAPI specifications to the built-in tree walkers only from a `yaml` or `yml` block inside a `<Tabs>` block. The chunker leaves a `yaml` block inside the `<Tabs>` block when, for example, its opening fence has a title after the language. The built-in tree walkers do not read `yaml_tree_walkers`. To have your configured tree walkers handle the block, write its opening fence unindented, with nothing after the language. In a `<Tabs>` block, the strategy emits the text between the code blocks as prose chunks, in page order. A `<Tab>` or `<TabItem>` tag with attributes stays in the prose chunk, so the chunk shows the tab label. |
| `TableChunkingStrategy` | Markdown tables. The strategy emits one `table_row` chunk for each data row. It passes the text outside the tables to the list and prose strategies. |
| `ListChunkingStrategy` | Markdown lists. The strategy emits one chunk for each list item, nested items included. It passes the text around the lists to the prose strategy. |
| `ProseChunkingStrategy` | Markdown and text with headings. This is the fallback strategy, and it splits the text as [Prose sections](#prose-sections) describes. |

To turn the tree walkers off, set `YAML_TREE_CHUNKING_ENABLED` to `false`. The default is `true`, and any other value also turns them off. Structured specifications then become `yaml_content` or `code_snippet` chunks.

## Chunk data model

Each chunk has a set of top-level fields and a `metadata` object. The fields in the `metadata` object depend on the chunk type. For every metadata field, see [Chunk metadata schema](metadata-schema.md).

### Top-level fields

Every chunk has the following top-level fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `chunk_id` | string | Unique identifier of the chunk, as a 64-character hexadecimal string. OpenCrane builds it from a SHA-256 hash of the chunk content, source file, chunk type, and selected metadata such as the source URL. The same input produces the same ID on every run. Milvus uses it as the primary key. | `"195c9565…"` (shortened) |
| `chunk_type` | string, enum | Semantic type of the chunk content. For the values, see [Chunk types](#chunk-types). | `"prose"` |
| `content` | string or object | The chunk content. Prose, code, generic YAML, list item, and table row chunks store a string. CRD, OpenAPI, and JSON Schema chunks store a JSON object or array parsed from the YAML. | `"Run the following command to install the server."` |
| `source_file` | string | Path to the source file, relative to the directory where you run `opencrane`. This is usually the `llms-full.txt` file. | `".opencrane/llmstxt/llms-full.txt"` |
| `source_name` | string, optional | Path key of the source under `sources` in `.opencrane/config.yaml`. The chunker matches the `metadata.source_url` of the chunk against the `url` and `docs_url` of each source, and the longest match wins. The value is `null` when no source matches. The `source_names` parameter of `search_docs` filters on this field. | `"MicrosoftDocs/microsoft-style-guide"` |
| `token_count` | integer | Number of tokens in the chunk content, counted with the `TOKEN_ENCODING` tiktoken encoding, `cl100k_base` by default. | `412` |

### Chunk types

The `chunk_type` field takes one of the following values:

| Value | Content |
|---|---|
| `"prose"` | Markdown or text with headings |
| `"code_snippet"` | One fenced code block |
| `"crd_definition"` | One property of a Kubernetes CRD |
| `"openapi_spec"` | One element of an OpenAPI specification |
| `"json_schema"` | One property or definition of a JSON Schema |
| `"yaml_content"` | YAML that is not a recognized structured format |
| `"list_item"` | One Markdown list item |
| `"table_row"` | One data row of a Markdown table |

### CRD chunks

The chunker splits CRDs (`chunk_type: "crd_definition"`) by property, and only the properties under `spec` produce chunks. It splits a property further only when the property exceeds 800 tokens. The following table shows how the chunker handles each property:

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

The chunker processes all CRD versions, and each version produces its own chunks with its `crd_version`. The `breadcrumb_path` and `logical_parent` of each version use the index of that version, for example `versions[1]`, so `neighbor_chunks` stay within one version.

### OpenAPI chunks

The chunker splits OpenAPI 3.x and Swagger 2.0 specifications (`chunk_type: "openapi_spec"`) by element. It splits a component schema further only when the schema exceeds 800 tokens. The following table shows how the chunker handles each kind of element:

| Element | Result |
|---|---|
| `info`, `security`, and `tags` | One chunk for each element |
| `servers` | One chunk for each server |
| Path operations, such as GET and POST | One chunk for each method |
| Components, such as schemas, security schemes, and responses | One chunk for each named component |
| Component schema of more than 800 tokens, with nested `properties` | The chunker recurses into the properties and creates separate chunks |
| Component schema of more than 800 tokens, with `items.properties` (an array schema) | The chunker recurses into the array item properties and creates separate chunks |

When the chunker splits a schema, the schema itself gets no chunk of its own. The chunker never splits a path operation, however large it is. The following table shows examples of the result:

| Element | Size and structure | Chunks |
|---|---|---|
| `components.schemas.User` | 200 tokens | One chunk |
| `components.schemas.Order` | 1,500 tokens, nested properties | Separate chunks for `Order.customer` and `Order.items` |
| Path operation `/users.post` | Large request and response | One chunk |

### JSON Schema chunks

The chunker splits JSON Schema documents (`chunk_type: "json_schema"`) by property and definition. It splits a property further only when the property exceeds 800 tokens. The following table shows how the chunker handles each part of the schema:

| Part of the schema | Result |
|---|---|
| Root `title`, `description`, `$comment`, `examples`, or `default` | One root chunk, if any of these keys is present |
| Property of 800 tokens or fewer | One chunk with the property and its nested content |
| Property of more than 800 tokens, with nested `properties` | The chunker recurses into the nested properties |
| Property of more than 800 tokens, with `items.properties` (an array) | The chunker recurses into the array item properties |
| Definitions in `$defs`, or in `definitions` when there is no `$defs` | The same recursive logic as for properties |
| Boolean schemas and empty schemas (`{}`) | No chunk |

When the chunker splits a property or a definition, the property or definition gets no chunk of its own. Its children become property chunks. The following table shows examples of the result:

| Element | Size and structure | Chunks |
|---|---|---|
| `properties.username` | 30 tokens | One chunk |
| `properties.config` | 1,000 tokens, nested | Separate chunks for `config.database` and `config.cache` |
| `$defs.address` | 900 tokens, array items | Separate chunks for `$defs.address.items.street` and `$defs.address.items.city` |

## Extend the chunker

To extend the chunker, add a processing strategy or a tree walker. A processing strategy adds support for a new content type. A tree walker adds support for a new structured YAML specification.

You register both kinds of extension in a subclass of `OpenCraneConfig`. To load the subclass, see [Extend OpenCrane](../README.md#extend-opencrane).

## Add a processing strategy

To add support for a new content type, such as JSON, XML, or a custom Markdown component, complete the steps in this section.

### 1. Create a strategy class

A strategy implements the `ProcessingStrategy` interface. For a reference implementation, see `CodeChunkingStrategy` in `opencrane/rag/services/code_chunker.py`. The following example shows a strategy that handles text that starts with `{{custom}}`:

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

The `chunk_type` must be one of the values in the `chunk_type` `Literal` in `opencrane/shared/models/chunk.py`. Prose chunks accept only the following metadata keys, and OpenCrane sets most of them after the strategies run:

- `source_url`
- `breadcrumb_path`
- `section_anchor`
- `tab_value`
- `tab_label`
- `key`
- `heading_path`
- `clause_id`
- `parent_chunk_id`
- `position`
- `prev_chunk_id`
- `next_chunk_id`

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
> The first strategy that matches the content and returns chunks handles it. A strategy that returns no chunks passes the content to the next strategy. Place specific strategies before general ones.

The chunker uses your strategy the next time you run `opencrane chunk`.

## Add a tree walker for a YAML specification

To add support for a new YAML-based specification, such as AsyncAPI or AWS CloudFormation templates, complete the steps in this section. Steps 1 and 4 change the OpenCrane package itself, not only your configuration.

The walker runs on every YAML document that `YamlChunkingStrategy` handles. The first walker in `yaml_tree_walkers` whose `can_handle` returns `True` processes the document.

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
- Add the same chunk type and fields to `opencrane/mcp/metadata-schema.md`, which the `get_metadata_schema` Model Context Protocol (MCP) tool returns.
- Add the chunk type to `_CHUNK_TYPE_SECTION_HEADINGS` in `opencrane/mcp/server.py`, so `get_metadata_schema(chunk_type=...)` returns its section.

The MCP server shows only `crd_definition`, `openapi_spec`, and `json_schema` chunks as YAML with location comments. To show the new chunk type the same way, add it to `_YAML_CHUNK_TYPES` and to the matching chunk type checks in `opencrane/mcp/server.py`.

The chunker uses your walker the next time you run `opencrane chunk`.
