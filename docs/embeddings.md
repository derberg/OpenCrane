# Generate embeddings

After you [chunk the documentation](chunking.md), generate vector embeddings for semantic search. To generate the embeddings, run the following command:

```bash
opencrane embed
```

## What the embed step does

The `opencrane embed` command performs the following steps:

1. Loads the chunks from `.opencrane/chunks.json`.
2. Generates a vector embedding for each chunk, in batches to limit memory use. The default model is Nomic Embed, `nomic-ai/nomic-embed-text-v1.5`.
3. Saves the embeddings to `.opencrane/embeddings.json`.

To use a different model, set the `EMBEDDING_MODEL` environment variable.

> [!IMPORTANT]
> The Milvus collection stores 768-dimension vectors, which matches the default model. Choose a model that produces 768-dimension vectors. If the model produces vectors of another size, the `index` step cannot load them.

## Embedding prompts

Many embedding models need one prompt for documents and another for queries, or search returns less relevant results. The following environment variables set the prompts:

- `EMBEDDING_DOCUMENT_PROMPT` is a prefix that `embed` adds to every chunk.
- `EMBEDDING_QUERY_PROMPT` is a `{query}` template or a prefix that `serve` and `visualize` apply to each query.

Both default to empty. A literal `\n` in either value becomes a newline.

The following table lists prompts for common 768-dimension models:

| Model | `EMBEDDING_DOCUMENT_PROMPT` | `EMBEDDING_QUERY_PROMPT` |
|---|---|---|
| `nomic-ai/nomic-embed-text-v1.5`, the default | `search_document: ` | `search_query: ` |
| `intfloat/e5-base-v2` | `passage: ` | `query: ` |

To change the document prompt, generate new embeddings and rebuild the collection.

> [!CAUTION]
> `DROP_EXISTING=true` deletes the Milvus collection before `index` rebuilds it. First confirm that `MILVUS_COLLECTION` and the connection variables name the right collection.

The following commands do both for the default model:

```bash
export EMBEDDING_DOCUMENT_PROMPT="search_document: "
export EMBEDDING_QUERY_PROMPT="search_query: "
opencrane embed && DROP_EXISTING=true opencrane index
```

A new query prompt needs only a server restart. The `docker-compose.yml` file from `opencrane init` passes `EMBEDDING_QUERY_PROMPT` from your shell to the container.

## Collection schema

When the `index` step loads the embeddings into Milvus, each chunk becomes one record in the collection. The following table lists the fields of each record:

| Field | Type | Notes |
|---|---|---|
| `chunk_id` | `VARCHAR` | Primary key. `max_length` 64 |
| `embedding` | `FLOAT_VECTOR` | 768 dimensions |
| `content` | `VARCHAR` | `max_length` 65,535 |
| `source_file` | `VARCHAR` | `max_length` 512 |
| `source_name` | `VARCHAR` | `max_length` 256 |
| `chunk_type` | `VARCHAR` | `max_length` 32. One of `prose`, `code_snippet`, `crd_definition`, `openapi_spec`, `json_schema`, `yaml_content`, `list_item`, or `table_row` |
| `metadata_json` | `VARCHAR` | `max_length` 65,535 |
| `token_count` | `INT64` | none |
| `line_start` | `INT64` | none |
| `list_id` | `VARCHAR` | `max_length` 64 |
| `table_id` | `VARCHAR` | `max_length` 64 |

The `index` step creates an `AUTOINDEX` vector index with the cosine metric, and `INVERTED` indexes on `list_id` and `table_id`. It then loads the collection into memory. For how the MCP server searches the collection, see [Vector search and the MCP server](vector-search.md).
