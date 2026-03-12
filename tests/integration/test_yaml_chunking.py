"""Integration tests for YAML chunking."""

from pathlib import Path
from opencrane.rag.services.file_processor import process_file


class TestYamlChunkingIntegration:
    """Integration tests for YAML chunking end-to-end."""

    def test_yaml_chunking(self):
        """Test chunking a document with YAML content."""
        from pathlib import Path
        test_data_dir = Path(__file__).parent.parent / "fixtures"
        sample_file = test_data_dir / "sample.yaml"
        
        chunks = process_file(sample_file)

        # Verify we have yaml chunks (non-CRD YAML uses yaml_content type)
        yaml_chunks = [c for c in chunks if c.chunk_type in ["yaml_content", "crd_definition", "openapi_spec"]]
        assert len(yaml_chunks) > 0
        assert any("apiVersion: v1" in str(c.content) for c in yaml_chunks)