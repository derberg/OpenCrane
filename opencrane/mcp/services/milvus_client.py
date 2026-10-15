"""Milvus client service for vector database operations."""

import json
import logging
import re
from typing import List, Optional, Dict
from pymilvus import MilvusClient, DataType
from opencrane.shared.config import get_config
from opencrane.shared.models.chunk import CHUNK_TYPE_MAX_LENGTH
from opencrane.shared.models.vector_chunk import DEFAULT_EMBEDDING_DIM, VectorChunk

logger = logging.getLogger(__name__)

# Milvus VARCHAR max_length counts UTF-8 bytes, not characters. Each limit below
# matches its column's max_length in create_collection; the insert path truncates
# by bytes so multi-byte text cannot overflow a column.
MAX_CONTENT_LENGTH = 65535
MAX_METADATA_LENGTH = 65535
MAX_SOURCE_FILE_LENGTH = 512
MAX_SOURCE_NAME_LENGTH = 256
_CONTENT_TRUNCATED_SUFFIX = "\n\n[Content truncated due to size]"

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


def _truncate_utf8(value: str, max_bytes: int) -> str:
    """Cap ``value`` at ``max_bytes`` UTF-8 bytes without splitting a character."""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _safe_id(value: str) -> str:
    """Cap to the stored column width and strip to the safe id charset.

    Ids (list_id/table_id) are server-generated hex-style digests, never user
    input, so this normally changes nothing — it is defense-in-depth for the
    interpolated filter.
    """
    return _ID_UNSAFE.sub("", (value or "")[:_ID_FIELD_MAX])


# Clause ids (``5.4.1.2a``, ``Annex C``) also carry dots and spaces, neither of
# which can break out of a double-quoted filter literal.
_CLAUSE_UNSAFE = re.compile(r"[^0-9A-Za-z_. -]")


def _safe_clause(value: str) -> str:
    """Like :func:`_safe_id`, but keeps the ``.`` and space a clause id uses."""
    return _CLAUSE_UNSAFE.sub("", (value or "")[:_ID_FIELD_MAX])


# Characters that can end or escape a double-quoted filter literal, plus control
# characters. A search filter value (chunk type, source file, source name) that
# contains one is dropped instead of interpolated, so it can't close the string
# and add its own expression logic.
_LITERAL_UNSAFE = re.compile(r'["\\\x00-\x1f\x7f]')

# A scalar field name interpolated into a lookup filter.
_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _safe_literals(values: List[str]) -> List[str]:
    """Return the values that are safe inside a double-quoted filter literal.

    Values that are not strings, or that contain a quote, a backslash or a
    control character, are dropped. Dropping only narrows a filter: the caller
    must treat a non-empty list that comes back empty as "match nothing", never
    as "no filter".
    """
    return [v for v in values if isinstance(v, str) and not _LITERAL_UNSAFE.search(v)]


def _check_field(field: str) -> str:
    """Return ``field`` if it is a plain scalar field name, else raise ``ValueError``."""
    if not isinstance(field, str) or not _FIELD_NAME.fullmatch(field):
        raise ValueError(f"Invalid filter field name: {field!r}")
    return field

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
    "clause_id",
    "parent_chunk_id",
]

# Key of the embedding settings (model, prompts, vector size) in the collection
# schema description. The description is the one place that both Milvus Lite and
# server mode persist and return: Milvus Lite accepts collection properties at
# create time but drops them, and has no API to alter them later.
_EMBEDDING_METADATA_KEY = "opencrane_embedding"

# Heaviest metadata fields, dropped first when metadata would overflow the column.
_HEAVY_METADATA_FIELDS = ("neighbor_chunks", "sibling_ids", "sibling_previews")


def _truncate_metadata(metadata_json: str) -> str:
    """Keep metadata within MAX_METADATA_LENGTH while always emitting valid JSON.

    Drops the largest list-valued fields first, then falls back to scalar-only
    metadata, then to a minimal marker — never a corrupt/half-cut JSON string.
    """
    if len(metadata_json.encode("utf-8")) <= MAX_METADATA_LENGTH:
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
        # Mode selection: an explicit MILVUS_DB_PATH always wins (a file path means
        # Milvus Lite, an empty value means server mode). When MILVUS_DB_PATH is unset,
        # MILVUS_HOST selects server mode; with neither set, Lite is the default.
        # Note: We use MILVUS_DB_PATH instead of MILVUS_URI because pymilvus reads MILVUS_URI
        # at import time and fails if it's a file path
        import os
        milvus_db_path = os.getenv("MILVUS_DB_PATH")
        if milvus_db_path is None:
            milvus_db_path = "" if os.getenv("MILVUS_HOST") else ".opencrane/milvus.db"
        if milvus_db_path:
            self.uri = milvus_db_path
        else:
            self.host = host or self.config.milvus_host
            self.port = port or self.config.milvus_port
            self.uri = f"http://{self.host}:{self.port}"
        self.collection_name = collection_name or self.config.milvus_collection
        self.client = None
        # Cached vector dimension of the existing collection (see vector_dim()).
        self._vector_dim: Optional[int] = None
        # Cached embedding settings of the existing collection (see embedding_metadata()).
        self._embedding_metadata: Optional[Dict] = None
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

    def create_collection(self, dim: int = DEFAULT_EMBEDDING_DIM, embedding_metadata: Optional[Dict] = None):
        """Create the collection with schema for chunks.

        ``dim`` is the embedding vector size and must match the model that
        produced the embeddings (it is recorded in the embeddings file).
        ``embedding_metadata`` (model name, prompts, vector size) is stored as
        JSON in the schema description, where :meth:`embedding_metadata` reads
        it back so the server can embed queries the same way.
        """
        logger.info(f"Creating collection: {self.collection_name} (vector dim {dim})")

        description = ""
        if embedding_metadata is not None:
            description = json.dumps({_EMBEDDING_METADATA_KEY: embedding_metadata}, ensure_ascii=False)

        schema = self.client.create_schema(
            auto_id=False,
            enable_dynamic_field=True,
            description=description,
        )

        schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, max_length=64, is_primary=True)
        schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=dim)
        schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=MAX_CONTENT_LENGTH)
        schema.add_field(field_name="source_file", datatype=DataType.VARCHAR, max_length=MAX_SOURCE_FILE_LENGTH)
        schema.add_field(field_name="source_name", datatype=DataType.VARCHAR, max_length=MAX_SOURCE_NAME_LENGTH)
        schema.add_field(field_name="chunk_type", datatype=DataType.VARCHAR, max_length=CHUNK_TYPE_MAX_LENGTH)
        schema.add_field(field_name="metadata_json", datatype=DataType.VARCHAR, max_length=MAX_METADATA_LENGTH)
        schema.add_field(field_name="token_count", datatype=DataType.INT64)
        schema.add_field(field_name="line_start", datatype=DataType.INT64)
        # list_id / table_id are lifted out of metadata into their own scalar columns
        # so get_list_members / get_table_members can query members directly instead
        # of scanning an in-memory copy of the whole corpus.
        schema.add_field(field_name="list_id", datatype=DataType.VARCHAR, max_length=_ID_FIELD_MAX)
        schema.add_field(field_name="table_id", datatype=DataType.VARCHAR, max_length=_ID_FIELD_MAX)
        # clause_id / parent_chunk_id (prose navigation) back get_section's clause
        # lookup and sub-section listing the same way.
        schema.add_field(field_name="clause_id", datatype=DataType.VARCHAR, max_length=_ID_FIELD_MAX)
        schema.add_field(field_name="parent_chunk_id", datatype=DataType.VARCHAR, max_length=_ID_FIELD_MAX)

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
        index_params.add_index(field_name="clause_id", index_type="INVERTED")
        index_params.add_index(field_name="parent_chunk_id", index_type="INVERTED")

        try:
            self.client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
                index_params=index_params
            )
            self._vector_dim = dim
            self._embedding_metadata = embedding_metadata
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

        data = []
        for chunk in vector_chunks:
            # Truncate content if needed
            content = chunk.content or ""
            content_bytes = len(content.encode("utf-8"))
            if content_bytes > MAX_CONTENT_LENGTH:
                logger.warning(f"Truncating content for chunk {chunk.chunk_id} from {content_bytes} to {MAX_CONTENT_LENGTH} bytes")
                budget = MAX_CONTENT_LENGTH - len(_CONTENT_TRUNCATED_SUFFIX.encode("utf-8"))
                content = _truncate_utf8(content, budget) + _CONTENT_TRUNCATED_SUFFIX

            # Truncate other fields if needed
            source_file = _truncate_utf8(chunk.source_file or "", MAX_SOURCE_FILE_LENGTH)
            metadata_json = _truncate_metadata(chunk.metadata_json or "{}")

            data.append({
                "chunk_id": chunk.chunk_id,
                "embedding": chunk.embedding,
                "content": content,
                "source_file": source_file,
                "source_name": _truncate_utf8(chunk.source_name or "", MAX_SOURCE_NAME_LENGTH),
                "chunk_type": chunk.chunk_type,
                "metadata_json": metadata_json,
                "token_count": chunk.token_count,
                "line_start": chunk.line_start if chunk.line_start is not None else 0,
                "list_id": _truncate_utf8(chunk.list_id or "", _ID_FIELD_MAX),
                "table_id": _truncate_utf8(chunk.table_id or "", _ID_FIELD_MAX),
                "clause_id": _truncate_utf8(chunk.clause_id or "", _ID_FIELD_MAX),
                "parent_chunk_id": _truncate_utf8(chunk.parent_chunk_id or "", _ID_FIELD_MAX),
            })

        # Insert in batches: a single call covering a whole corpus can outlive
        # milvus-lite's HTTP/2 keepalive window — the connection dies with
        # GOAWAY, pymilvus retries the entire insert, and rows from every
        # attempt persist (row_count becomes an exact multiple of the corpus).
        # Each batch finishes well before the keepalive timeout, so it is
        # never retried.
        batch_size = self.config.milvus_insert_batch_size
        total = len(data)
        try:
            for start in range(0, total, batch_size):
                self.client.insert(
                    collection_name=self.collection_name,
                    data=data[start:start + batch_size]
                )
                logger.info(f"Inserted {min(start + batch_size, total)}/{total} chunks")
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

        # A query vector from a model of a different size than the indexed one
        # makes Milvus reject the search, which the handler below would turn into
        # a silent empty result. Fail loudly instead, outside that handler.
        expected_dim = self.vector_dim()
        if expected_dim is not None and len(query_vector) != expected_dim:
            raise ValueError(
                f"Query embedding has {len(query_vector)} dimensions but collection "
                f"'{self.collection_name}' was indexed with {expected_dim}-dimensional "
                "vectors. Serve with the same EMBEDDING_MODEL that built the index, "
                "or re-run 'opencrane embed' and 'opencrane index' with the new model."
            )

        search_params = {
            "metric_type": "COSINE",
            "params": {}
        }

        # Every value is interpolated into a double-quoted literal (Milvus Lite
        # has no filter_params templating), so a value that could close the
        # literal is dropped. Each clause stays in its own parentheses and the
        # clauses are ANDed, so no value can lift another clause, such as the
        # source_names restriction that enforces the source policy.
        filter_clauses = []
        for field, values in (
            ("chunk_type", chunk_types),
            ("source_file", source_files),
            ("source_name", source_names),
        ):
            if not values:
                continue
            safe = _safe_literals(values)
            if not safe:
                # Every value was unsafe. Dropping the clause would widen the
                # search, so match nothing instead.
                logger.warning(f"Search rejected: no safe {field} filter values in {values!r}")
                return []
            clause = " || ".join(f'{field} == "{v}"' for v in safe)
            filter_clauses.append(f"({clause})")
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
        self,
        field: str,
        value: str,
        chunk_type: Optional[str] = None,
        limit: int = 16384,
        source_names: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Return all chunks whose scalar ``field`` equals ``value``.

        ``value`` is sanitized to the safe id charset and capped to the stored
        column width, then interpolated into the filter — Milvus Lite (the
        default backend) does not support expression templating (filter_params),
        so interpolation is the portable path and the guard keeps it safe. The
        cap also stops a lookup missing a value the insert path truncated.
        ``field`` and ``chunk_type`` come from the server, never from user input,
        but are still checked: ``field`` must be a plain field name and
        ``chunk_type`` is stripped to the id charset. Pass ``chunk_type`` to constrain
        rows in the database instead of post-filtering in Python.

        ``source_names`` (``None`` = any source) restricts rows to the sources
        the caller may read. Names come from server config or a server-side
        middleware, never the client; a name that could break the quoted
        literal is dropped, so it fails closed, and an empty list matches
        nothing.
        """
        expr = f'{_check_field(field)} == "{_safe_id(value)}"'
        if chunk_type is not None:
            expr += f' and chunk_type == "{_safe_id(chunk_type)}"'
        if source_names is not None:
            names = sorted({
                _truncate_utf8(n, MAX_SOURCE_NAME_LENGTH)
                for n in source_names
                if '"' not in n and "\\" not in n
            })
            if not names:
                return []
            expr += " and source_name in [" + ", ".join(f'"{n}"' for n in names) + "]"
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

    def query_by_values(
        self, field: str, values: List[str], chunk_type: Optional[str] = None, limit: int = 16384
    ) -> List[Dict]:
        """Return all chunks whose scalar ``field`` is one of ``values``.

        Same safety contract as :meth:`query_by_field`: each value is capped to
        the stored column width and stripped to a safe charset (clause ids keep
        ``.`` and spaces), then interpolated as an ``in [...]`` list.
        """
        sanitize = _safe_clause if field == "clause_id" else _safe_id
        safe = sorted({sanitize(v) for v in values} - {""})
        if not safe:
            return []
        expr = f"{_check_field(field)} in [" + ", ".join(f'"{v}"' for v in safe) + "]"
        return self._query_rows(expr, chunk_type, limit)

    def query_by_prefix(
        self, field: str, prefix: str, chunk_type: Optional[str] = None, limit: int = 16384
    ) -> List[Dict]:
        """Return all chunks whose scalar ``field`` starts with ``prefix``.

        The prefix is sanitized like a clause id, and ``%`` (the LIKE wildcard)
        is never in the safe charset, so it can only be a literal prefix.
        """
        safe = _safe_clause(prefix)
        if not safe:
            return []
        return self._query_rows(f'{_check_field(field)} like "{safe}%"', chunk_type, limit)

    def _query_rows(self, expr: str, chunk_type: Optional[str], limit: int) -> List[Dict]:
        if chunk_type is not None:
            expr += f' and chunk_type == "{_safe_id(chunk_type)}"'
        try:
            rows = self.client.query(
                collection_name=self.collection_name,
                filter=expr,
                output_fields=_LOOKUP_FIELDS,
                limit=limit,
            )
        except Exception as e:
            logger.error(f"Failed to query {expr!r}: {e}")
            return []
        if len(rows) >= limit:
            logger.warning(f"Query {expr!r} returned the {limit}-row cap; some chunks may be omitted.")
        return rows

    def has_prose_navigation(self) -> bool:
        """True when indexed prose chunks carry navigation metadata.

        Reads a single prose row's metadata (never the corpus): chunks produced
        with prose navigation enabled all carry ``position``.
        """
        try:
            rows = self.client.query(
                collection_name=self.collection_name,
                filter='chunk_type == "prose"',
                output_fields=["metadata_json"],
                limit=1,
            )
            return bool(rows) and "position" in json.loads(rows[0].get("metadata_json") or "{}")
        except Exception as e:
            logger.error(f"Failed to check for prose navigation metadata: {e}")
            return False

    def field_names(self) -> set:
        """Return the set of scalar/vector field names in the existing collection."""
        try:
            desc = self.client.describe_collection(collection_name=self.collection_name)
            return {f["name"] for f in desc.get("fields", [])}
        except Exception as e:
            logger.error(f"Failed to describe collection: {e}")
            return set()

    def vector_dim(self) -> Optional[int]:
        """Return the embedding vector dimension of the existing collection.

        ``None`` when the collection does not exist or its schema cannot be read.
        A successful lookup is cached: a collection's vector dimension cannot
        change without dropping and recreating it.
        """
        if self._vector_dim is not None:
            return self._vector_dim
        try:
            desc = self.client.describe_collection(collection_name=self.collection_name)
            for field in desc.get("fields", []):
                if field.get("name") == "embedding":
                    self._vector_dim = int(field["params"]["dim"])
                    return self._vector_dim
        except Exception as e:
            logger.debug(f"Could not read vector dimension of collection: {e}")
        return None

    def embedding_metadata(self) -> Optional[Dict]:
        """Return the embedding settings that ``opencrane index`` recorded.

        A dict with ``model``, ``document_prompt``, ``dim`` and, when the
        embeddings file recorded it, ``query_prompt``. ``None`` when the
        collection is missing, unreadable, or was built before the settings
        were recorded. A successful lookup is cached: the description cannot
        change without dropping and recreating the collection.
        """
        if self._embedding_metadata is not None:
            return self._embedding_metadata
        try:
            desc = self.client.describe_collection(collection_name=self.collection_name)
            recorded = json.loads(desc.get("description") or "{}").get(_EMBEDDING_METADATA_KEY)
        except Exception as e:
            logger.debug(f"Could not read embedding settings of collection: {e}")
            return None
        if isinstance(recorded, dict):
            self._embedding_metadata = recorded
        return self._embedding_metadata

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