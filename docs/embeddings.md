# Generating Embeddings

After chunking documentation, generate vector embeddings for semantic search:

```bash
opencrane embed --config yourproject.config:YourConfig
```

## What happens

- Loads chunks from `rag-chunks.json`
- Uses Nomic Embed model (nomic-ai/nomic-embed-text-v1.5)
- Generates vector embeddings (dimensions depend on model)
- Processes in batches to avoid memory issues
- Saves to `rag-embeddings.json`

## Collection Schema

When loaded into Milvus, each chunk becomes a vector with fields:
- `chunk_id` (VARCHAR, primary key)
- `embedding` (FLOAT_VECTOR, dimensions match embedding model)
- `content` (VARCHAR, up to 65KB)
- `source_file` (VARCHAR)
- `chunk_type` (VARCHAR: prose/code_snippet/crd_definition/openapi_spec)
- `metadata_json` (VARCHAR)
- `token_count` (INT64)
- `line_start` (INT64)

The system creates an HNSW index for fast similarity search and loads the collection into memory for optimal performance.
