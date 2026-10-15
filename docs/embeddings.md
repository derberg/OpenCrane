# Generate embeddings

After you [chunk the documentation](chunking.md), generate vector embeddings for semantic search. To generate the embeddings, run the following command:

```bash
opencrane embed
```

## What the embed step does

The `opencrane embed` command performs the following steps:

1. Loads the chunks from `.opencrane/chunks.json`.
2. Adds the document prompt of the model, if it has one, to the start of each chunk. See [Embedding prompts](#embedding-prompts).
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

The following variables control how `embed`, `serve`, and `visualize` load and run the embedding model. Each command reads them separately, so set the same values for all of them.

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_DTYPE` | `float32` | Weight precision: `float32`, `bfloat16`, or `float16`. `bfloat16` about halves the model's memory, which matters for a model with hundreds of millions of parameters on a server. OpenCrane stores the vectors as `float32` in every case. Lower precision changes the vectors slightly, so use the same value for `embed` and `serve`. |
| `EMBEDDING_DEVICE` | `cpu` | Torch device, for example `cuda`, `cuda:1`, or `mps`. The default is `cpu`, because `mps` can run out of memory on macOS. |
| `EMBEDDING_BATCH_SIZE` | `8` | Number of chunks that `embed` encodes at once. A larger batch is faster and uses more memory. |
| `EMBEDDING_MAX_SEQ_LENGTH` | `0` | Maximum tokens per input. `0` keeps the model's own limit. A long-context model can use a lot of memory on one large chunk. With a cap, OpenCrane truncates such a chunk instead. |
| `EMBEDDING_TRUST_REMOTE_CODE` | auto | `true` or `false`. When unset, OpenCrane allows remote code only for the model families that need it, `nomic-ai/*`. Set `true` for another model that ships its own code. |

An invalid value stops the command with an error that names the variable. `visualize` ignores `EMBEDDING_BATCH_SIZE` and `EMBEDDING_MAX_SEQ_LENGTH`, because it encodes one short paragraph.

## Embedding prompts

Many embedding models need one prompt for documents and another for queries, or search returns less relevant results. For example, Nomic Embed expects `search_document: ` before each chunk and `search_query: ` before each query. OpenCrane adds a document prompt to the start of every chunk in `embed`. `serve` and `visualize` apply a query prompt to each query. A query prompt that contains `{query}` is a template, and OpenCrane puts the query in its place. Any other query prompt is a prefix.

OpenCrane resolves each prompt in the following order and uses the first match:

1. The `EMBEDDING_DOCUMENT_PROMPT` or `EMBEDDING_QUERY_PROMPT` environment variable, when it is set. An empty value means no prompt.
2. The non-empty `document` or `query` prompt that the model ships in `config_sentence_transformers.json`. OpenCrane also accepts the `passage`, `search_document`, and `search_query` prompt names. For example, `Qwen/Qwen3-Embedding-0.6B` ships a query prompt and no document prompt.
3. A built-in table of models whose model card requires prompts that the model does not ship.
4. No prompt. OpenCrane encodes the text as it is.

The following table lists the models in the built-in table:

| Model | Document prompt | Query prompt |
|---|---|---|
| `nomic-ai/nomic-embed-text-v1.5`, the default, and `nomic-ai/nomic-embed-text-v1` | `search_document: ` | `search_query: ` |
| `intfloat/e5-small-v2`, `intfloat/e5-base-v2`, `intfloat/e5-large-v2` | `passage: ` | `query: ` |
| `intfloat/multilingual-e5-small`, `intfloat/multilingual-e5-base`, `intfloat/multilingual-e5-large` | `passage: ` | `query: ` |

A literal `\n` in either environment variable becomes a newline.

`embeddings.json` records the document prompt that `embed` used. `embed` compares it with the prompt that applies now and generates new embeddings when they differ, also when only the default changed. The skip check reads the model's prompts from a local model directory or the Hugging Face cache, so it does not load the model.

The query prompt must match the document prompt that built the collection. A new document prompt needs new embeddings and a rebuilt collection.

> [!CAUTION]
> `DROP_EXISTING=true` deletes the Milvus collection before `index` rebuilds it. Searches fail until the rebuild finishes. First confirm that `MILVUS_COLLECTION` and the connection variables name the right collection.

The following commands build the embeddings and the collection with the prompts that apply now:

```bash
opencrane embed && DROP_EXISTING=true opencrane index
```

A collection built without prompts keeps working if you turn the default prompts off. The following commands turn them off for the default model:

```bash
export EMBEDDING_DOCUMENT_PROMPT=""
export EMBEDDING_QUERY_PROMPT=""
```

A new query prompt needs only a server restart. The `.opencrane/docker-compose.yml` file from `opencrane init` passes `EMBEDDING_QUERY_PROMPT` from your shell to the container only when the variable is set in your shell. When it is not set, the server uses the default query prompt of the model.

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
