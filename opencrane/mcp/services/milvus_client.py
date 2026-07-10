"""Milvus client service for vector database operations."""

import json
import logging
import re
from typing import List, Optional, Dict
from pymilvus import MilvusClient, DataType
from opencrane.shared.config import get_config
from opencrane.shared.models.vector_chunk import VectorChunk

logger = logging.getLogger(__name__)

# Milvus VARCHAR fields cap at 65535 chars; keep metadata within that limit.
MAX_METADATA_LENGTH = 65535

# Stored width of the list_id / table_id scalar columns. The insert path caps
# values to this width, so the lookup path must cap by the same amount or a query
# could miss a value the insert truncated. (Today both ids are 16-char sha256
# digests, so this is a guard rather than a live truncation.)
_ID_FIELD_MAX = 64

# Characters not allowed in a scalar-id filter value. Milvus Lite doesn't support
# expression templating (filter_params), so values are interpolated into the
# filter string — this guard keeps that safe by stripping anything outside the
# id charset, so a value can neither break the filter nor inject expression logic.
_ID_UNSAFE = re.compile(r"[^0-9A-Za-z_-]")


def _safe_id(value: str) -> str:
    """Cap to the stored column width and strip to the safe id charset.

    Ids (list_id/table_id) are server-generated hex-style digests, never user
    input, so this normally changes nothing — it is defense-in-depth for the
    interpolated filter.
    """
    return _ID_UNSAFE.sub("", (value or "")[:_ID_FIELD_MAX])

# Fields returned for chunk lookups (get_chunk / query_by_field). Excludes the
# embedding vector, which is large and never needed by the MCP tools.
_LOOKUP_FIELDS = [
    "chunk_id",
    "content",
    "source_file",
    "source_name",
    "chunk_type",
    "metadata_json",
    "token_count",
    "line_start",
    "list_id",
    "table_id",
]

# Heaviest metadata fields, dropped first when metadata would overflow the column.
_HEAVY_METADATA_FIELDS = ("neighbor_chunks", "sibling_ids", "sibling_previews")


def _truncate_metadata(metadata_json: str) -> str:
    """Keep metadata within MAX_METADATA_LENGTH while always emitting valid JSON.

    Drops the largest list-valued fields first, then falls back to scalar-only
    metadata, then to a minimal marker — never a corrupt/half-cut JSON string.
    """
    if len(metadata_json) <= MAX_METADATA_LENGTH:
        return metadata_json
    try:
        meta = json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return '{"truncated": true}'

    for field in _HEAVY_METADATA_FIELDS:
        meta.pop(field, None)
    meta["truncated"] = True
    reduced = json.dumps(meta)
    if len(reduced) <= MAX_METADATA_LENGTH:
        return reduced

    scalars = {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))}
    scalars["truncated"] = True
    reduced = json.dumps(scalars)
    if len(reduced) <= MAX_METADATA_LENGTH:
        return reduced
    return '{"truncated": true}'


class MilvusService:
    """Service for interacting with Milvus vector database."""

    def __init__(self, host: str = None, port: int = None, collection_name: str = None):
        self.config = get_config()
        # Support MILVUS_DB_PATH for Milvus Lite (file path) or fallback to host/port for server mode
        # Note: We use MILVUS_DB_PATH instead of MILVUS_URI because pymilvus reads MILVUS_URI
        # at import time and fails if it's a file path
        import os
        milvus_db_path = os.getenv("MILVUS_DB_PATH", ".opencrane/milvus.db")
        if milvus_db_path:
            self.uri = milvus_db_path
        else:
            self.host = host or self.config.milvus_host
            self.port = port or self.config.milvus_port
            self.uri = f"http://{self.host}:{self.port}"
        self.collection_name = collection_name or self.config.milvus_collection
        self.client = None
        self._connect()

    def _connect(self):
        """Connect to Milvus database."""
        logger.info(f"Connecting to Milvus at {self.uri}")
        try:
            self.client = MilvusClient(uri=self.uri)
            logger.info("Connected to Milvus successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Milvus: {e}")
            raise

    def create_collection(self):
        """Create the collection with schema for chunks."""
        logger.info(f"Creating collection: {self.collection_name}")

        schema = self.client.create_schema(
            auto_id=False,
            enable_dynamic_field=True
        )

        schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, max_length=64, is_primary=True)
        schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=768)
        schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="source_file", datatype=DataType.VARCHAR, max_length=512)
        schema.add_field(field_name="source_name", datatype=DataType.VARCHAR, max_length=256)
        schema.add_field(field_name="chunk_type", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="metadata_json", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="token_count", datatype=DataType.INT64)
        schema.add_field(field_name="line_start", datatype=DataType.INT64)
        # list_id / table_id are lifted out of metadata into their own scalar columns
        # so get_list_members / get_table_members can query members directly instead
        # of scanning an in-memory copy of the whole corpus.
        schema.add_field(field_name="list_id", datatype=DataType.VARCHAR, max_length=_ID_FIELD_MAX)
        schema.add_field(field_name="table_id", datatype=DataType.VARCHAR, max_length=_ID_FIELD_MAX)

        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="AUTOINDEX",
            metric_type="COSINE"
        )
        # Scalar indexes on the fields get_list_members / get_table_members filter
        # by. Without them Milvus scans the whole collection for every member
        # lookup — defeating the point of moving members out of the in-memory
        # corpus. INVERTED is the general-purpose scalar index for VARCHAR equality
        # lookups and, unlike AUTOINDEX (vector-only on Milvus Lite), is accepted
        # by both Milvus Lite and server mode.
        index_params.add_index(field_name="list_id", index_type="INVERTED")
        index_params.add_index(field_name="table_id", index_type="INVERTED")

        try:
            self.client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
                index_params=index_params
            )
            logger.info("Collection created successfully")
        except Exception as e:
            logger.error(f"Failed to create collection: {e}")
            raise

    def load_collection(self):
        """Load the collection into memory."""
        logger.info(f"Loading collection: {self.collection_name}")
        try:
            self.client.load_collection(collection_name=self.collection_name)
            logger.info("Collection loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load collection: {e}")
            raise

    def insert_chunks(self, vector_chunks: List[VectorChunk]):
        """Insert vector chunks into the collection."""
        logger.info(f"Inserting {len(vector_chunks)} chunks into collection")

        # Milvus has a 65535 character limit for VARCHAR fields
        MAX_CONTENT_LENGTH = 65535
        MAX_SOURCE_FILE_LENGTH = 1024

        data = []
        for chunk in vector_chunks:
            # Truncate content if needed
            content = chunk.content or ""
            if len(content) > MAX_CONTENT_LENGTH:
                logger.warning(f"Truncating content for chunk {chunk.chunk_id} from {len(content)} to {MAX_CONTENT_LENGTH} chars")
                content = content[:MAX_CONTENT_LENGTH - 50] + "\n\n[Content truncated due to size]"

            # Truncate other fields if needed
            source_file = (chunk.source_file or "")[:MAX_SOURCE_FILE_LENGTH]
            metadata_json = _truncate_metadata(chunk.metadata_json or "{}")

            data.append({
                "chunk_id": chunk.chunk_id,
                "embedding": chunk.embedding,
                "content": content,
                "source_file": source_file,
                "source_name": chunk.source_name or "",
                "chunk_type": chunk.chunk_type,
                "metadata_json": metadata_json,
                "token_count": chunk.token_count,
                "line_start": chunk.line_start if chunk.line_start is not None else 0,
                "list_id": (chunk.list_id or "")[:_ID_FIELD_MAX],
                "table_id": (chunk.table_id or "")[:_ID_FIELD_MAX],
            })

        try:
            res = self.client.insert(
                collection_name=self.collection_name,
                data=data
            )
            logger.info(f"Inserted {len(data)} chunks, result: {res}")
        except Exception as e:
            logger.error(f"Failed to insert chunks: {e}")
            raise

    def search(
        self,
        query_vector: List[float],
        limit: int = 5,
        chunk_types: Optional[List[str]] = None,
        source_files: Optional[List[str]] = None,
        source_names: Optional[List[str]] = None,
        metadata_contains: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Search for similar chunks with optional scalar and metadata filters."""
        logger.info(
            f"Searching with limit {limit}, chunk_types: {chunk_types}, source_files: {source_files}, source_names: {source_names}, metadata_contains: {metadata_contains}"
        )

        search_params = {
            "metric_type": "COSINE",
            "params": {}
        }

        filter_clauses = []
        if chunk_types:
            type_filter = " || ".join(f'chunk_type == "{t}"' for t in chunk_types)
            filter_clauses.append(f"({type_filter})")
        if source_files:
            file_filter = " || ".join(f'source_file == "{s}"' for s in source_files)
            filter_clauses.append(f"({file_filter})")
        if source_names:
            name_filter = " || ".join(f'source_name == "{s}"' for s in source_names)
            filter_clauses.append(f"({name_filter})")
        filter_expr = " && ".join(filter_clauses) if filter_clauses else None

        try:
            results = self.client.search(
                collection_name=self.collection_name,
                data=[query_vector],
                filter=filter_expr,
                limit=limit,
                output_fields=[
                    "chunk_id",
                    "content",
                    "source_file",
                    "source_name",
                    "chunk_type",
                    "metadata_json",
                    "token_count",
                    "line_start",
                ],
                search_params=search_params
            )
            logger.info(f"Search completed, found {len(results[0])} results before metadata filtering")

            hits = results[0]
            
            # Milvus returns hit objects with entity attributes
            # Convert to dictionaries for consistent format
            formatted_hits = []
            for hit in hits:
                # Check if already flattened (has chunk_id at top level) vs nested (has entity key)
                if isinstance(hit, dict) and "chunk_id" in hit:
                    # Already flattened format
                    formatted_hits.append(hit)
                else:
                    # Nested format - extract fields from the entity
                    formatted_hits.append({
                        "chunk_id": hit.entity.get("chunk_id") if hasattr(hit, 'entity') else None,
                        "content": hit.entity.get("content") if hasattr(hit, 'entity') else "",
                        "source_file": hit.entity.get("source_file") if hasattr(hit, 'entity') else "",
                        "source_name": hit.entity.get("source_name") if hasattr(hit, 'entity') else "",
                        "chunk_type": hit.entity.get("chunk_type") if hasattr(hit, 'entity') else "",
                        "metadata_json": hit.entity.get("metadata_json") if hasattr(hit, 'entity') else "{}",
                        "token_count": hit.entity.get("token_count") if hasattr(hit, 'entity') else 0,
                        "line_start": hit.entity.get("line_start") if hasattr(hit, 'entity') else 0,
                        "distance": hit.distance if hasattr(hit, 'distance') else 0
                    })
            
            if metadata_contains:
                def _matches_metadata(hit_dict: dict) -> bool:
                    meta = hit_dict.get("metadata_json", "")
                    # metadata_json is stored as JSON string
                    return all(str(term) in meta for term in metadata_contains)

                formatted_hits = [h for h in formatted_hits if _matches_metadata(h)]
                logger.info(f"After metadata filtering, {len(formatted_hits)} results remain")

            return formatted_hits
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []  # Return empty list instead of None on error

    def get_collection_stats(self) -> Dict:
        """Get collection statistics."""
        try:
            stats = self.client.get_collection_stats(collection_name=self.collection_name)
            return stats
        except Exception as e:
            logger.error(f"Failed to get collection stats: {e}")
            raise

    def get_chunk(self, chunk_id: str) -> Optional[Dict]:
        """Fetch a single chunk by its primary key, or None if absent."""
        try:
            rows = self.client.get(
                collection_name=self.collection_name,
                ids=[chunk_id],
                output_fields=_LOOKUP_FIELDS,
            )
            return rows[0] if rows else None
        except Exception as e:
            logger.error(f"Failed to fetch chunk {chunk_id}: {e}")
            return None

    def query_by_field(
        self, field: str, value: str, chunk_type: Optional[str] = None, limit: int = 16384
    ) -> List[Dict]:
        """Return all chunks whose scalar ``field`` equals ``value``.

        ``value`` is sanitized to the safe id charset and capped to the stored
        column width, then interpolated into the filter — Milvus Lite (the
        default backend) does not support expression templating (filter_params),
        so interpolation is the portable path and the guard keeps it safe. The
        cap also stops a lookup missing a value the insert path truncated.
        ``field`` and ``chunk_type`` are caller-controlled (never user input), so
        they stay in the expression directly. Pass ``chunk_type`` to constrain
        rows in the database instead of post-filtering in Python.
        """
        expr = f'{field} == "{_safe_id(value)}"'
        if chunk_type is not None:
            expr += f' and chunk_type == "{chunk_type}"'
        try:
            rows = self.client.query(
                collection_name=self.collection_name,
                filter=expr,
                output_fields=_LOOKUP_FIELDS,
                limit=limit,
            )
        except Exception as e:
            logger.error(f"Failed to query {field}=={value!r}: {e}")
            return []
        if len(rows) >= limit:
            logger.warning(
                f"query_by_field({field}=={value!r}) returned the {limit}-row cap; "
                "some members may be omitted."
            )
        return rows

    def field_names(self) -> set:
        """Return the set of scalar/vector field names in the existing collection."""
        try:
            desc = self.client.describe_collection(collection_name=self.collection_name)
            return {f["name"] for f in desc.get("fields", [])}
        except Exception as e:
            logger.error(f"Failed to describe collection: {e}")
            return set()

    def distinct_chunk_types(self, batch_size: int = 1000) -> set:
        """Return the distinct ``chunk_type`` values present in the collection.

        Pages through the collection with ``query_iterator`` pulling only the
        small ``chunk_type`` column (never content/metadata), so it discovers
        every type — including custom ones emitted by extension chunking
        strategies — without loading the corpus into memory and without the
        per-query row cap. Called once at server startup to tailor the tool list;
        the caller caches the result.
        """
        types: set = set()
        try:
            iterator = self.client.query_iterator(
                collection_name=self.collection_name,
                filter="",
                output_fields=["chunk_type"],
                batch_size=batch_size,
            )
        except Exception as e:
            logger.error(f"Failed to enumerate chunk types: {e}")
            return types
        try:
            while True:
                batch = iterator.next()
                if not batch:
                    break
                types.update(row["chunk_type"] for row in batch if row.get("chunk_type"))
        except Exception as e:
            # Degrade gracefully rather than crash tool listing at startup; return
            # whatever was gathered before the failure.
            logger.error(f"Failed while enumerating chunk types: {e}")
        finally:
            iterator.close()
        return types