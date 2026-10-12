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

## Choose an embedding model

To use a different model, set the `EMBEDDING_MODEL` environment variable. Models of any vector size work, because the `index` step creates the collection with the vector size of the embeddings file. A larger model can return better search results, and a smaller one embeds faster and uses less memory.

Run the MCP server with the same model that generated the embeddings. If the model of the MCP server produces vectors of a different size than the collection stores, semantic and hybrid searches fail with an error that names both sizes.

> [!IMPORTANT]
> After you change the model, run `opencrane embed` and `opencrane index` again. When the vector size changes, the `index` step deletes the existing collection and builds a new one. When the vector size stays the same, the `index` step keeps the existing collection. To rebuild it, set `DROP_EXISTING=true`.

## Collection schema

When the `index` step loads the embeddings into Milvus, each chunk becomes one record in the collection. The following table lists the fields of each record:

| Field | Type | Notes |
|---|---|---|
| `chunk_id` | `VARCHAR` | Primary key. `max_length` 64 |
| `embedding` | `FLOAT_VECTOR` | Vector size of the embedding model. 768 for the default model |
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
