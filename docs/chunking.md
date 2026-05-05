# Chunking Documentation for RAG

The Structure-Aware Hybrid Chunker processes documentation into semantically meaningful chunks optimized for Retrieval-Augmented Generation (RAG) systems.

```bash
opencrane chunk --config yourproject.config:YourConfig
```

This generates `./rag-chunks.json` with RAG-ready chunks.

## How Document Boundaries are Handled

The chunker intelligently processes llms-full.txt files:

1. Boundary markers are ignored: The `-----` separators and `### https://github.com/...` H3 markers are treated as document boundaries, not content
2. URL prefixes are captured: Each heading's text (including GitHub URL) is tracked for context

Example of how a document is chunked:
```
Input (llms-full.txt):
  ### https://github.com/.../file.md          ← Ignored (boundary marker)

  # https://github.com/.../file.md Title      ← Content
  Paragraph content...                        ← Chunk content
  ## https://github.com/.../file.md Section   ← Subheading
  More content...                             ← Another chunk

Output (rag-chunks.json):
  {
    "chunk_type": "prose",
    "metadata": {
      "source_url": "https://github.com/.../file.md"
    },
    "content": "More content..."
  }
```

This design ensures that each chunk maintains full context through its header hierarchy while document boundaries remain clear for processing.

## Architecture

The chunker uses a **Strategy Pattern** for extensible format support. It allows adding new formats (JSON, XML, etc.) without modifying core logic, using `ProcessingStrategy` interface. See `CodeChunkingStrategy` for reference implementation.

Available Strategies:
1. **YamlChunkingStrategy** - Detects and processes YAML content; delegates structured YAML specs (e.g., CRDs, OpenAPI) to tree walkers for structured chunking, falls back to generic yaml_content type for other YAML
2. **TabsChunkingStrategy** - HTML tab components (`<Tabs>`/`<Tab>`) for parallel instructions; processes each tab separately as prose
3. **CodeChunkingStrategy** - Fenced code blocks with language detection; auto-detects structured YAML specs in YAML code blocks and delegates to tree walkers
4. **ProseChunkingStrategy** - Markdown/text with hierarchical headers (fallback strategy)

Strategies are evaluated in order; first match wins.

## Data Models

### Chunk Structure

#### Top-Level Fields

##### `chunk_id` (string, UUID)
- Purpose: Unique identifier for each chunk
- Format: UUID v4 (e.g., `"d0cdceae-8ab8-4e01-82c6-aa62eb0a3179"`)
- Usage: Primary key in Milvus, cross-reference via `neighbor_chunks`, re-hydration, context expansion
- Generation: Created during chunking using Python's `uuid.uuid4()`

##### `chunk_type` (string, enum)
- Purpose: Identifies semantic type of chunk content
- Values:
  - `"prose"` - Markdown/text with hierarchical headers
  - `"code_snippet"` - Fenced code blocks with language detection
  - `"crd_definition"` - Kubernetes Custom Resource Definition properties
  - `"openapi_spec"` - OpenAPI specification elements
  - `"yaml_content"` - Generic YAML configuration (not a recognized structured format)
- Usage: Route chunks to appropriate processing logic and templates

##### `content` (string or object)
- Purpose: Actual chunk content
- Format:
  - String for prose and code_snippet chunks
  - JSON object/array for structured schema chunks (parsed YAML)
- Important: YAML chunks store structured JSON, not strings, for semantic querying

##### `source_file` (string)
- Purpose: Relative path to source file from workspace root. Typically the llms-full file.
- Example: `"llmstxt/llms-full.txt"`
- Usage: Track chunk origins for debugging and filtering

##### `source_name` (string, optional)
- Purpose: Human-readable source identifier matching a path key in `.opencrane/config.yaml` sources.
- Example: `"MicrosoftDocs/microsoft-style-guide"`
- Resolved at chunking time by matching the chunk's `metadata.source_url` against the `url` / `docs_url` of each configured source (longest prefix wins).
- Value is `null` when no configured source matches the chunk's URL.
- Stored as a top-level Milvus field, enabling fast scalar filtering via the `source_names` parameter on `search_docs`.

##### `token_count` (integer)
- Purpose: Number of tokens in chunk content
- Encoding: `cl100k_base` (tiktoken) - used by GPT-4, GPT-3.5-turbo, text-embedding-ada-002
- Usage: Enforce chunk size limits, estimate context window usage

#### Metadata Object

All chunks include a `metadata` object with type-specific fields:

##### Universal Metadata (all chunk types)

###### `source_url` (string, URL, optional)
- Purpose: Link back to original documentation page
- Format: Full URL from markdown heading (e.g., `### https://...`)
- Example: `"https://github.com/org/repo/blob/main/docs/configuration.md"`
- Usage: Provide users with source documentation link in RAG responses
- Present in: All chunk types when source URL is available

###### `original_format` (string, optional)
- Purpose: Original serialization format of content
- Value: `"yaml"` for YAML chunks
- Usage: Inform re-hydration process about expected output format
- Present in: YAML chunks (crd_definition, openapi_spec)

###### `schema_type` (string, enum, optional)
- Purpose: High-level schema category for YAML content
- Values:
  - `"k8s_crd"` - Kubernetes Custom Resource Definition
  - `"openapi"` - OpenAPI specification
- Usage: Route to appropriate schema validators and processors
- Present in: YAML chunks (crd_definition, openapi_spec)

##### Prose Chunks (`chunk_type: "prose"`)

##### Code Chunks (`chunk_type: "code_snippet"`)

###### `language` (string, required)
- Purpose: Programming language of code block
- Format: Language identifier from fenced code block (e.g., ```python)
- Examples: `"python"`, `"javascript"`, `"bash"`, `"yaml"`, `"json"`
- Usage: Syntax highlighting, language-specific filtering, code validation

###### `tab_value` (string, optional)
- Purpose: Tab identifier for parallel instructions
- Format: Value attribute from `<Tab>` component
- Usage: Filter code examples by implementation type
- Present in: Code blocks within `<Tabs>` components

###### `tab_label` (string, optional)
- Purpose: Human-readable tab label
- Format: Label attribute from `<Tab>` component
- Usage: Display tab context in RAG responses
- Present in: Code blocks within `<Tabs>` components

##### CRD Chunks (`chunk_type: "crd_definition"`)

**Chunking Strategy**: Property-based recursive chunking with token limits (300-800 tokens):
- Each `spec.properties` field is evaluated for token count
- If ≤ 800 tokens: chunk as-is with nested content
- If > 800 tokens AND has nested `properties`: recurse into nested properties, create separate chunks
- If > 800 tokens AND has `items.properties` (array): recurse into array item properties, create separate chunks
- If > 800 tokens AND no splittable structure: keep as single chunk (e.g., maps with `additionalProperties`)

Examples:
- `spec.replicas` (50 tokens) → single chunk with full definition
- `spec.config` (1200 tokens, nested properties) → split into `spec.config.database`, `spec.config.cache` chunks
- `spec.volumes` (900 tokens, array items with properties) → split into `spec.volumes.items.name`, `spec.volumes.items.path` chunks

**Multi-Version Support**: All CRD versions are processed. Each version generates separate chunks with `crd_version` metadata.

###### `breadcrumb_path` (string)
- Purpose: Exact location in YAML tree structure
- Format: Dot-separated path with array indices
- Example: `"spec.versions[0].schema.openAPIV3Schema.properties.spec.properties.replicas"`
- Usage: Reconstruct YAML tree during re-hydration, precise property lookup

###### `logical_parent` (string)
- Purpose: Parent node in tree hierarchy
- Format: Same as breadcrumb_path but without final segment
- Example: `"spec.versions[0].schema.openAPIV3Schema.properties.spec.properties"` (parent of replicas)
- Usage: Group siblings, identify neighbor relationships

###### `neighbor_chunks` (array of UUIDs)
- Purpose: Track sibling chunks at same tree level
- Format: Array of `chunk_id` UUIDs
- Definition: Neighbors = chunks sharing the same `logical_parent` (top-level spec properties only)
- Example: `spec.replicas`, `spec.image`, `spec.config` all share parent → All reference each other's UUIDs
- Empty Array: No neighbors when only child under parent exists
- Usage: Context expansion - fetch neighbors to provide additional related information

###### `crd_kind` (string)
- Purpose: Kubernetes resource kind
- Example: `"MyResource"`
- Usage: Identify which CRD this chunk belongs to

###### `crd_api_version` (string)
- Purpose: Full API group and version
- Format: `{group}/{version}`
- Example: `"mygroup.example.com/v1"`
- Usage: Distinguish between different API versions of same resource

###### `crd_version` (string)
- Purpose: Version identifier (shorter form)
- Example: `"v1"`
- Usage: Quick version filtering, distinguish chunks from different CRD versions

###### `crd_property_path` (string)
- Purpose: Shortened property path (user-friendly, top-level only)
- Format: Starts from `spec.`, only top-level properties
- Example: `"spec.replicas"`, `"spec.config"` (NOT `"spec.config.database"`)
- Usage: Display concise property paths in RAG responses, identify top-level property chunks

##### OpenAPI Chunks (`chunk_type: "openapi_spec"`)

**Chunking Strategy**: Element-based recursive chunking with token limits (300-800 tokens):
- Top-level elements (`info`, `servers`, `security`, `tags`) → single chunks
- Path operations (GET, POST, etc.) → separate chunks per method
- Component schemas:
  - If ≤ 800 tokens: chunk schema as-is
  - If > 800 tokens AND has nested `properties`: recurse into properties, create separate chunks
  - If > 800 tokens AND has `items.properties` (array schema): recurse into array item properties

Examples:
- `components.schemas.User` (200 tokens) → single chunk
- `components.schemas.Order` (1500 tokens, nested properties) → split into `Order.customer`, `Order.items` chunks
- Path operation `/users.post` with large request/response → single chunk (atomic operation unit)

##### JSON Schema Chunks (`chunk_type: "json_schema"`)

**Chunking Strategy**: Property and definition-based recursive chunking with token limits (300-800 tokens):
- Root metadata (title, description) → single chunk if present
- Properties:
  - If ≤ 800 tokens: chunk property as-is with nested content
  - If > 800 tokens AND has nested `properties`: recurse into nested properties
  - If > 800 tokens AND has `items.properties` (array): recurse into array item properties
- Definitions (`$defs` or `definitions`): same recursive logic as properties

Examples:
- `properties.username` (30 tokens) → single chunk
- `properties.config` (1000 tokens, nested) → split into `config.database`, `config.cache` chunks
- `$defs.address` (900 tokens, array items) → split into `address.items.street`, `address.items.city` chunks

###### `breadcrumb_path` (string)
- Purpose: Exact location in OpenAPI tree structure
- Format: Dot-separated path
- Examples:
  - `"info"`
  - `"paths./groups/{id}/access_requests.get"`
  - `"components.schemas.API_Entities_Badge"`
- Usage: Reconstruct OpenAPI spec during re-hydration

###### `logical_parent` (string)
- Purpose: Parent node in tree hierarchy
- Examples:
  - `"root"` (parent of info, servers, security, tags)
  - `"paths./groups/{id}/access_requests"` (parent of get, post operations)
  - `"components.schemas"` (parent of schema definitions)
- Usage: Group siblings, identify neighbor relationships

###### `neighbor_chunks` (array of UUIDs)
- Purpose: Track sibling chunks at same tree level
- Format: Array of `chunk_id` UUIDs
- Examples:
  - `info`, `servers`, `security`, `tags` (all have parent "root") → All are neighbors
  - GET and POST at same path → They are neighbors
- Empty Array: Single child under parent (e.g., one server)
- Usage: Context expansion for related API elements

###### `openapi_version` (string)
- Purpose: OpenAPI specification version
- Examples: `"3.0.1"`, `"3.1.0"`
- Usage: Ensure compatibility with spec version

###### `openapi_element` (string, enum)
- Purpose: Top-level OpenAPI element type
- Values: `"info"`, `"servers"`, `"security"`, `"tags"`, `"paths"`, `"components"`
- Usage: Categorize chunks by OpenAPI structure

###### `server_url` (string, optional)
- Purpose: Server base URL
- Present in: Server chunks
- Example: `"https://www.example.com/api/v4"`
- Usage: Display available API endpoints

###### `endpoint_path` (string, optional)
- Purpose: API endpoint path
- Present in: Path operation chunks
- Example: `"/groups/{id}/access_requests"`
- Usage: Filter by endpoint, display in RAG responses

###### `http_method` (string, optional)
- Purpose: HTTP method for operation
- Present in: Path operation chunks
- Values: `"get"`, `"post"`, `"put"`, `"delete"`, `"patch"`, `"options"`, `"head"`, `"trace"`
- Usage: Filter by operation type, display method in responses

###### `schema_name` (string, optional)
- Purpose: Schema definition name
- Present in: Schema chunks
- Example: `"API_Entities_AccessRequester"`
- Usage: Reference schemas, resolve $ref links

###### `component_type` (string, optional)
- Purpose: Component category
- Present in: Component chunks
- Values: `"schemas"`, `"securitySchemes"`, `"responses"`, `"parameters"`, `"examples"`, `"requestBodies"`, `"headers"`, `"links"`, `"callbacks"`
- Usage: Organize components by type

###### `security_scheme_name` (string, optional)
- Purpose: Security scheme identifier
- Present in: Security scheme chunks
- Example: `"ApiKeyAuth"`
- Usage: Reference security schemes

## Extending with Custom Strategies

### Adding a New Processing Strategy

To add support for a new content type (e.g., JSON, XML, custom markdown components):

1. **Create strategy class**:

   ```python
   from pathlib import Path
   from typing import List
   from opencrane.rag.base_strategy import ProcessingStrategy
   from opencrane.shared.models.chunk import Chunk

   class MyCustomStrategy(ProcessingStrategy):
       def can_process(self, node) -> bool:
           """Check if this strategy can handle the node."""
           # Return True if this strategy handles the node
           return hasattr(node, 'text') and node.text.startswith('{{custom}}')

       def process(self, node, source_file: Path) -> List[Chunk]:
           """Process node into chunks."""
           chunks = []

           # Extract content
           content = self._extract_content(node)

           # Create chunk with metadata
           metadata = {
               "custom_field": "value",
           }

           chunk = Chunk(
               content=content,
               source_file=str(source_file),
               chunk_type="custom_type",
               metadata=metadata,
               token_count=self._count_tokens(content)
           )

           chunks.append(chunk)
           return chunks
   ```

2. **Register in FileProcessor**:

   ```python
   # opencrane/rag/services/file_processor.py
   self.strategies = [
       YamlChunkingStrategy(),      # Priority 1: YAML (delegates to tree walkers)
       TabsChunkingStrategy(),       # Priority 2: HTML tabs
       MyCustomStrategy(),           # Priority 3: Your custom strategy
       CodeChunkingStrategy(),       # Priority 4: Fenced code blocks
       ProseChunkingStrategy(),      # Priority 5: Prose (fallback)
   ]
   ```

   **Important**: Strategy order matters! First matching strategy wins. Place specific strategies before general ones.

### Adding a Tree Walker for YAML Standards

To add support for new YAML-based specifications (e.g., AsyncAPI, GraphQL schemas, Terraform):

1. **Create tree walker class**:

   ```python
   from typing import List, Dict, Any
   from opencrane.walkers.yaml_tree_walker import YamlTreeWalker
   from opencrane.shared.models.chunk import Chunk
   from opencrane.shared.utils.token_counter import get_token_count
   import yaml

   class AsyncAPITreeWalker(YamlTreeWalker):
       """Walk AsyncAPI specification trees and generate element-based chunks."""

       def __init__(self, yaml_dict: Dict[str, Any], source_url: str,
                    original_yaml_file: str | None = None):
           """Initialize AsyncAPI tree walker."""
           super().__init__(yaml_dict, source_url, original_yaml_file)
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

           chunk = Chunk(
               chunk_id=self._generate_chunk_id(),
               content=info,
               source_file=self.source_url,
               chunk_type="asyncapi_spec",
               token_count=token_count,
               metadata={
                   "source_url": self.source_url,
                   "breadcrumb_path": "info",
                   "logical_parent": "root",
                   "neighbor_chunks": [],
                   "original_format": "yaml",
                   "schema_type": "asyncapi",
                   "asyncapi_version": self.asyncapi_version,
                   "asyncapi_element": "info"
               }
           )

           self.chunks.append(chunk)

       def _process_channels(self, channels: Dict[str, Any]) -> None:
           """Process channels section (message topics/queues)."""
           # Similar implementation to _process_info
           # Create chunks for each channel
           pass

       def _process_components(self, components: Dict[str, Any]) -> None:
           """Process reusable components (schemas, messages, etc)."""
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

2. **Add detection logic**:

   ```python
   # Add to opencrane/rag/services/code_chunker.py or opencrane/shared/utils/yaml_detection.py

   def is_asyncapi_spec(yaml_dict: dict) -> bool:
       """Detect if YAML is an AsyncAPI specification."""
       return "asyncapi" in yaml_dict and "channels" in yaml_dict
   ```

3. **Integrate into CodeChunkingStrategy**:

   ```python
   # In opencrane/rag/services/code_chunker.py, _create_code_chunk method

   if language.lower() in ['yaml', 'yml']:
       try:
           yaml_data = yaml.safe_load(code)
           if isinstance(yaml_data, dict):
               config = get_config()
               if config.yaml_tree_chunking_enabled:
                   source_url = base_source_url or str(source_file)

                   # Choose appropriate walker
                   if _is_k8s_crd(yaml_data):
                       walker = K8sCRDTreeWalker(
                           yaml_dict=yaml_data,
                           source_url=source_url
                       )
                   elif is_openapi_spec(yaml_data):
                       walker = OpenAPITreeWalker(
                           yaml_dict=yaml_data,
                           source_url=source_url
                       )
                   elif is_asyncapi_spec(yaml_data):  # Add your walker
                       walker = AsyncAPITreeWalker(
                           yaml_dict=yaml_data,
                           source_url=source_url
                       )
                       return walker.walk()
                   else:
                       # Fall through to generic code_snippet
                       pass
   ```

4. **Add new chunk type to models**:

   Ensure your new chunk type is recognized:
   - Add `"asyncapi_spec"` to chunk type validation if needed
   - Update documentation to list the new chunk type
   - Add appropriate metadata fields documentation

### Key Concepts

- **Strategy Pattern**: Each strategy handles specific content types (YAML, code, prose)
- **Tree Walkers**: Specialized processors for structured YAML formats (CRDs, OpenAPI, AsyncAPI)
- **Priority Order**: Strategies execute in order; first match wins (specific before general)
- **Neighbor Relationships**: Tree walkers identify sibling chunks for context expansion
- **Chunk Types**: Use descriptive types (`asyncapi_spec`, `terraform_config`) for filtering and routing
