import tempfile
from pathlib import Path
from opencrane.rag.generate_llms_txt import generate_outputs
import os
import shutil

def test_generate_outputs_one_level_deeper(tmp_path):
    """Test that generate_outputs processes one level deeper (subprojects)."""
    # Setup: source/project/subproject/file.md
    source = tmp_path / "source"
    project = source / "project"
    subproject = project / "subproject"
    llmstxt_dir = tmp_path / "llmstxt"
    subproject.mkdir(parents=True)
    (project / "file.md").write_text("# Project File", encoding="utf-8")
    (subproject / "subfile.md").write_text("# Subproject File", encoding="utf-8")

    with tempfile.TemporaryDirectory() as tempdir:
        # Set environment variables for the test
        os.environ["AI_DOCS_SOURCES_DIRS"] = str(source)
        os.environ["AI_DOCS_LLMSTXT_DIR"] = str(llmstxt_dir)
        generate_outputs()
        # Check project output
        project_out = llmstxt_dir / "source" / "project" / "llms-full.txt"
        assert project_out.exists()
        content = project_out.read_text(encoding="utf-8")
        assert "Project File" in content
        # Check subproject output
        subproject_out = llmstxt_dir / "source" / "project/subproject" / "llms-full.txt"
        assert subproject_out.exists()
        subcontent = subproject_out.read_text(encoding="utf-8")
        assert "Subproject File" in subcontent
        # Clean up env
        del os.environ["AI_DOCS_SOURCES_DIRS"]
        del os.environ["AI_DOCS_LLMSTXT_DIR"]
