# Generate embeddings

After you [chunk the documentation](chunking.md), generate vector embeddings for semantic search. To generate the embeddings, run the following command:

```bash
opencrane embed
```

## What the embed step does

The `opencrane embed` command performs the following steps:

1. Loads the chunks from `.opencrane/chunks.json`.
2. Adds the document prompt, if set, to the start of each chunk. See [Embedding prompts](#embedding-prompts).
3. Generates a vector embedding for each chunk on the CPU, in small batches to limit memory use. The default model is Nomic Embed, `nomic-ai/nomic-embed-text-v1.5`.
4. Saves the embeddings to `.opencrane/embeddings.json`, together with the model name, the document prompt, and the query prompt.

The command skips the run when the chunks and the document prompt match the last run. The check does not compare the model. A skipped run still writes the current `EMBEDDING_QUERY_PROMPT` to the file, because the query prompt does not change the vectors. To regenerate the embeddings anyway, add the `--force` flag.

## Choose an embedding model

To use a different model, set the `EMBEDDING_MODEL` environment variable. The value is a Hugging Face model ID or a local path that the `sentence-transformers` library can load. Any vector size works, because `opencrane index` sizes the collection from the embeddings. A larger model can improve results, and a smaller one embeds faster.

OpenCrane loads the model with `trust_remote_code=True`, so the model can run its own Python code on your machine. Use only models whose code you trust.

> [!CAUTION]
> When the embeddings come from a different model, `opencrane index` deletes and rebuilds the collection without `DROP_EXISTING`. A collection that an earlier OpenCrane version built records no model. For that collection, you must set `DROP_EXISTING=true`, which also deletes the collection. Searches fail until the rebuild finishes. Check that `MILVUS_COLLECTION` and the [connection variables](../README.md#variables-for-the-index-and-serve-steps) point to the collection to replace.

To switch to a new model, run the following commands:

```bash
export EMBEDDING_MODEL={MODEL_ID}
opencrane embed --force && DROP_EXISTING=true opencrane index
```

If you pass `--embeddings-file` to `opencrane embed`, pass the same flag to `opencrane index`.

Then restart the Model Context Protocol (MCP) server. The server reads the model from the index, so leave `EMBEDDING_MODEL` unset or set it to the same model.

## Embedding prompts

Many embedding models need one prompt for documents and another for queries, or search returns less relevant results. The following environment variables set the prompts:

- `EMBEDDING_DOCUMENT_PROMPT` is a prefix that `embed` adds to every chunk.
- `EMBEDDING_QUERY_PROMPT` is a `{query}` template or a prefix that `serve` and `visualize` apply to each query. `embed` writes it to the embeddings file, and `index` records it in the collection, where the server reads it.

Both default to empty. A literal `\n` in either value becomes a newline.

The following table lists prompts for common models:

| Model | `EMBEDDING_DOCUMENT_PROMPT` | `EMBEDDING_QUERY_PROMPT` |
|---|---|---|
| `nomic-ai/nomic-embed-text-v1.5`, the default | `search_document: ` | `search_query: ` |
| `intfloat/e5-base-v2` | `passage: ` | `query: ` |

A new document prompt needs new embeddings and a rebuilt collection.

> [!CAUTION]
> `DROP_EXISTING=true` deletes the Milvus collection before `index` rebuilds it. Searches fail until the rebuild finishes. First confirm that `MILVUS_COLLECTION` and the connection variables name the right collection.

The following commands set both prompts for the default model and rebuild the collection:

```bash
export EMBEDDING_DOCUMENT_PROMPT="search_document: "
export EMBEDDING_QUERY_PROMPT="search_query: "
opencrane embed && DROP_EXISTING=true opencrane index
```

A new query prompt needs no new vectors, but the collection must record it. `opencrane embed` writes the new prompt to the embeddings file without encoding the chunks again. `opencrane index` then rebuilds the collection, because the recorded prompt differs. Restart the server afterwards.

> [!CAUTION]
> `opencrane index` deletes the collection before it rebuilds it with the new query prompt. Searches fail until the rebuild finishes. First confirm that `MILVUS_COLLECTION` and the connection variables name the right collection.

The following commands record a new query prompt:

```bash
export EMBEDDING_QUERY_PROMPT="search_query: "
opencrane embed && opencrane index
```

## Embedding settings in the index

The server must embed each query with the model and query prompt that match the indexed chunks. A different model of the same vector size, or a missing query prompt, gives poor results and no error. To prevent this, `opencrane index` records the following values in the collection schema description:

- The embedding model
- The document prompt
- The query prompt
- The vector size

The schema description is the place that both Milvus Lite and a Milvus server persist. Milvus Lite drops collection properties.

At startup, the server resolves `EMBEDDING_MODEL` and `EMBEDDING_QUERY_PROMPT` with the following rules:

| Environment variable | Server behavior |
|---|---|
| Unset | Uses the value that the index records |
| Set to the recorded value | Uses that value |
| Set to a different value, including an empty `EMBEDDING_QUERY_PROMPT` | Does not start, and logs both values. If the server cannot read the index at startup, the first search and the `health` tool return this error. |

An empty `EMBEDDING_MODEL` counts as unset. An empty `EMBEDDING_QUERY_PROMPT` means "no prompt".

To fix a mismatch, unset the variable, or rebuild the index with the new value.

A collection that an earlier OpenCrane version built records no settings. The server then uses `EMBEDDING_MODEL` and `EMBEDDING_QUERY_PROMPT`, or their defaults, and logs a warning. `opencrane index` keeps such a collection.

> [!CAUTION]
> `DROP_EXISTING=true` deletes the Milvus collection before `index` rebuilds it. Searches fail until the rebuild finishes. First confirm that `MILVUS_COLLECTION` and the connection variables name the right collection.

The following commands rebuild the index with the current settings and record them:

```bash
opencrane embed --force && DROP_EXISTING=true opencrane index
```

An embeddings file from an earlier version has no query prompt. `opencrane index` then records no query prompt, and the server uses `EMBEDDING_QUERY_PROMPT`.

The `health` tool reports the model and the query prompt in use, and the source of each: `env`, `index`, or `default`.

## Collection schema

When the `index` step loads the embeddings into Milvus, each chunk becomes one record in the collection. For the rules that decide when `index` rebuilds the collection, see [`opencrane index`](../README.md#index-the-embeddings-in-milvus-with-opencrane-index). The following table lists the fields of each record:

| Field | Type | Notes |
|---|---|---|
| `chunk_id` | `VARCHAR` | Primary key |
| `embedding` | `FLOAT_VECTOR` | Vector size of the model, 768 by default |
| `content` | `VARCHAR` | OpenCrane truncates content longer than 65,535 characters. |
| `source_file` | `VARCHAR` | none |
| `source_name` | `VARCHAR` | none |
| `chunk_type` | `VARCHAR` | A built-in or custom chunk type, up to 32 characters. See [Chunk types](chunking.md#chunk-types). |
| `metadata_json` | `VARCHAR` | none |
| `token_count` | `INT64` | none |
| `line_start` | `INT64` | `0` when the chunk has no line number |
| `list_id` | `VARCHAR` | none |
| `table_id` | `VARCHAR` | none |
| `clause_id` | `VARCHAR` | none |
| `parent_chunk_id` | `VARCHAR` | none |

The `index` step indexes the `embedding` field with the cosine metric. For how the MCP server searches the collection, see [Vector search and the MCP server](vector-search.md).
