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

Many retrieval models expect one prompt on documents and another on queries, and they return worse results without them. OpenCrane reads the prompts from the following environment variables:

- `EMBEDDING_DOCUMENT_PROMPT`: a prefix that the `embed` step adds to every chunk.
- `EMBEDDING_QUERY_PROMPT`: applied to each query by `serve` and `visualize`. Write it as a template with a `{query}` placeholder, or as a plain prefix.

Both variables are empty by default, so OpenCrane encodes text as it is. A literal `\n` in either value becomes a newline. The following table lists the prompts for common models:

| Model | `EMBEDDING_DOCUMENT_PROMPT` | `EMBEDDING_QUERY_PROMPT` |
|---|---|---|
| `nomic-ai/nomic-embed-text-v1.5`, the default | `search_document: ` | `search_query: ` |
| Qwen3-Embedding | empty | `Instruct: Given a question, retrieve passages that answer it\nQuery: {query}` |

The document prompt is part of every stored vector, so a change to `EMBEDDING_DOCUMENT_PROMPT` requires new embeddings and a new index. The `embed` step records the prompt in `embeddings.json` and regenerates the embeddings when the prompt changes. The `index` step keeps a collection that already has rows, so run it with `DROP_EXISTING=true`:

```bash
export EMBEDDING_DOCUMENT_PROMPT="search_document: "
export EMBEDDING_QUERY_PROMPT="search_query: "
opencrane embed && DROP_EXISTING=true opencrane index
```

A change to `EMBEDDING_QUERY_PROMPT` takes effect when you restart the server. When a document prompt is set without a query prompt, `serve` logs a warning.

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
