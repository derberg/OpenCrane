# Generate embeddings

After you [chunk the documentation](chunking.md), generate vector embeddings for semantic search. To generate the embeddings, run the following command:

```bash
opencrane embed
```

## What the embed step does

The `opencrane embed` command performs the following steps:

1. Loads the chunks from `.opencrane/chunks.json`.
2. Adds the document prompt, if set, to the start of each chunk. See [Embedding prompts](#embedding-prompts).
3. Generates a vector embedding for each chunk on the CPU, in batches of `EMBEDDING_BATCH_SIZE` chunks to limit memory use. See [Model loading settings](#model-loading-settings). The default model is Nomic Embed, `nomic-ai/nomic-embed-text-v1.5`.
4. Saves the embeddings to `.opencrane/embeddings.json`, together with the model name and the document prompt.

The command skips the run when the chunks and the document prompt match the last run. The check does not compare the model. To regenerate the embeddings anyway, add the `--force` flag.

## Choose an embedding model

To use a different model, set the `EMBEDDING_MODEL` environment variable. The value is a Hugging Face model ID or a local path that the `sentence-transformers` library can load. Any vector size works, because `opencrane index` sizes the collection from the embeddings. A larger model can improve results, and a smaller one embeds faster.

Some models, such as Nomic Embed, ship their own Python code and load only with `trust_remote_code`. That code runs on your machine, so OpenCrane allows it only for models known to need it. See `EMBEDDING_TRUST_REMOTE_CODE` in [Model loading settings](#model-loading-settings).

> [!CAUTION]
> If the new model has a different vector size, `opencrane index` deletes and rebuilds the collection without `DROP_EXISTING`. If the size is the same, you must set `DROP_EXISTING=true`, which also deletes the collection. Searches fail or return poor results until the Model Context Protocol (MCP) server uses the same model as the collection. Check that `MILVUS_COLLECTION` and the [connection variables](../README.md#variables-for-the-index-and-serve-steps) point to the collection to replace.

To switch to a new model, run the following commands:

```bash
export EMBEDDING_MODEL={MODEL_ID}
opencrane embed --force && DROP_EXISTING=true opencrane index
```

If you pass `--embeddings-file` to `opencrane embed`, pass the same flag to `opencrane index`.

Then restart the MCP server with the same `EMBEDDING_MODEL`.

## Model loading settings

The following variables control how `embed` and `serve` load and run the embedding model. `embed` and the MCP server read the same variables, so set them in both places.

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_DTYPE` | `float32` | Weight precision: `float32`, `bfloat16`, or `float16`. `bfloat16` about halves the model's memory, which matters for a model with hundreds of millions of parameters on a server. OpenCrane stores the vectors as `float32` in every case. Lower precision changes the vectors slightly, so use the same value for `embed` and `serve`. |
| `EMBEDDING_DEVICE` | `cpu` | Torch device, for example `cuda`, `cuda:1`, or `mps`. The default is `cpu`, because `mps` can run out of memory on macOS. |
| `EMBEDDING_BATCH_SIZE` | `8` | Number of chunks that `embed` encodes at once. A larger batch is faster and uses more memory. |
| `EMBEDDING_MAX_SEQ_LENGTH` | `0` | Maximum tokens per input. `0` keeps the model's own limit. A long-context model can use a lot of memory on one large chunk. With a cap, OpenCrane truncates such a chunk instead. |
| `EMBEDDING_TRUST_REMOTE_CODE` | auto | `true` or `false`. When unset, OpenCrane allows remote code only for the model families that need it, `nomic-ai/*`. Set `true` for another model that ships its own code. |

An invalid value stops the command with an error that names the variable. `visualize` reads only `EMBEDDING_MODEL` and the prompts.

## Embedding prompts

Many embedding models need one prompt for documents and another for queries, or search returns less relevant results. The following environment variables set the prompts:

- `EMBEDDING_DOCUMENT_PROMPT` is a prefix that `embed` adds to every chunk.
- `EMBEDDING_QUERY_PROMPT` is a `{query}` template or a prefix that `serve` and `visualize` apply to each query.

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

A new query prompt needs only a server restart. The `.opencrane/docker-compose.yml` file from `opencrane init` passes `EMBEDDING_QUERY_PROMPT` from your shell to the container.

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
