"""Pydantic models for the Structure-Aware Hybrid Chunker."""

from typing import Dict, Any, Literal, Union
from pydantic import BaseModel, Field, field_validator, model_validator


class Chunk(BaseModel):
    """Represents a chunk of processed documentation."""

    chunk_id: str | None = Field(None, description="Unique identifier (UUID) for the chunk")
    content: Union[str, Dict[str, Any], list] = Field(..., description="Chunk payload: string for prose/code, dict/list for YAML")
    source_file: str = Field(..., description="Absolute or repo-relative path of the source file")
    chunk_type: Literal["prose", "code_snippet", "crd_definition", "openapi_spec", "yaml_content", "json_schema"] = Field(
        ..., description="Categorizes processing strategy"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Contextual data")
    token_count: int = Field(..., ge=0, description="Tokens per standard tokenizer")
    # TODO: line_start is currently unused (always None). Would require tracking line numbers during
    # document parsing. Kept for future use if line-level source tracking is implemented.
    line_start: int | None = Field(None, description="Starting line number in source file (1-indexed)")
    @model_validator(mode='after')
    def validate_content_and_metadata(self):
        """Validate content is non-empty and metadata matches chunk type."""
        # Validate content is non-empty
        if isinstance(self.content, str):
            if not self.content.strip():
                raise ValueError("string content must not be empty")
        elif isinstance(self.content, dict):
            if not self.content:
                raise ValueError("dict content must not be empty")
        elif isinstance(self.content, list):
            if not self.content:
                raise ValueError("list content must not be empty")
        
        # Validate metadata shape based on chunk_type
        if self.chunk_type == "prose":
            allowed_keys = {"source_url", "tab_value", "tab_label", "key"}
            invalid_keys = set(self.metadata.keys()) - allowed_keys
            if invalid_keys:
                raise ValueError("prose chunks must use supported metadata keys only")
        elif self.chunk_type == "code_snippet":
            if "language" not in self.metadata:
                raise ValueError("code_snippet chunks must have language in metadata")
        elif self.chunk_type == "crd_definition":
            required = ["breadcrumb_path", "logical_parent", "neighbor_chunks", 
                       "crd_kind", "crd_api_version", "crd_version", "crd_property_path"]
            missing = [f for f in required if f not in self.metadata]
            if missing:
                raise ValueError(f"crd_definition chunks must have {', '.join(missing)} in metadata")
            if not isinstance(self.content, dict):
                raise ValueError("crd_definition chunks must have dict content")
        elif self.chunk_type == "openapi_spec":
            required = ["breadcrumb_path", "logical_parent", "neighbor_chunks",
                       "openapi_version", "openapi_element"]
            missing = [f for f in required if f not in self.metadata]
            if missing:
                raise ValueError(f"openapi_spec chunks must have {', '.join(missing)} in metadata")
            if not isinstance(self.content, (dict, list)):
                raise ValueError("openapi_spec chunks must have dict or list content")
        elif self.chunk_type == "json_schema":
            required = ["breadcrumb_path", "logical_parent", "neighbor_chunks",
                       "schema_version", "schema_element"]
            missing = [f for f in required if f not in self.metadata]
            if missing:
                raise ValueError(f"json_schema chunks must have {', '.join(missing)} in metadata")
            if not isinstance(self.content, (dict, list)):
                raise ValueError("json_schema chunks must have dict or list content")

        return self

    def refresh_token_count(self) -> None:
        """Recalculate token count with current tokenizer.
        
        This is useful when the tokenizer encoding changes or when
        validating chunks loaded from storage.
        """
        from opencrane.shared.utils.token_counter import get_token_count
        
        # Convert content to string for token counting if it's a dict/list
        if isinstance(self.content, (dict, list)):
            import yaml
            content_str = yaml.dump(self.content, default_flow_style=False, allow_unicode=True)
        else:
            content_str = self.content
            
        self.token_count = get_token_count(content_str)


class RootIdentity(BaseModel):
    """Helper structure for CRD identity extraction."""

    apiVersion: str
    kind: str
    name: str
    namespace: str | None = None