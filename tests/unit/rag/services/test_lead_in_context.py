"""Tests for the lead-in sentence and breadcrumb that give list items and code chunks context."""

from pathlib import Path

import pytest

from opencrane.config import OpenCraneConfig
from opencrane.rag.services.base_strategy import ProcessingStrategy
from opencrane.rag.services.file_processor import FileProcessor
from opencrane.shared.models.chunk import register_metadata_keys

URL = "https://github.com/org/repo/blob/main/a.md"


@pytest.fixture(autouse=True)
def _reset_registry():
    yield
    register_metadata_keys({})


def _chunks(tmp_path, body, config=None):
    f = tmp_path / "llms-full.txt"
    f.write_text(f"### {URL}\n\n# Page\n\n## Install\n\n{body}\n", encoding="utf-8")
    return FileProcessor(config).process_file(f)


# --- lists ---------------------------------------------------------------------

def test_list_items_carry_the_lead_in(tmp_path):
    chunks = _chunks(tmp_path, "Prerequisites:\n\n- python3\n- pyyaml")
    items = [c for c in chunks if c.chunk_type == "list_item"]
    assert [c.content for c in items] == [
        "# Page > Install\nPrerequisites:\npython3",
        "# Page > Install\nPrerequisites:\npyyaml",
    ]
    assert all(c.metadata["list_caption"] == "Prerequisites:" for c in items)


def test_nested_items_carry_the_lead_in(tmp_path):
    chunks = _chunks(tmp_path, "Choose one:\n\n- Option A\n  - detail of A")
    nested = [c for c in chunks if c.chunk_type == "list_item" and c.metadata["depth"] == 1][0]
    assert nested.content == "# Page > Install\nChoose one:\nOption A\ndetail of A"


def test_sentence_without_colon_is_not_a_lead_in(tmp_path):
    chunks = _chunks(tmp_path, "The tool is fast and small.\n\n- python3")
    item = [c for c in chunks if c.chunk_type == "list_item"][0]
    assert item.content == "# Page > Install\npython3"
    assert "list_caption" not in item.metadata


def test_heading_right_above_list_is_not_a_lead_in(tmp_path):
    chunks = _chunks(tmp_path, "Intro text of the section.\n\n### Steps:\n\n- python3")
    item = [c for c in chunks if c.chunk_type == "list_item"][0]
    assert "list_caption" not in item.metadata


# --- code ----------------------------------------------------------------------

def test_code_chunk_carries_breadcrumb_and_lead_in(tmp_path):
    chunks = _chunks(tmp_path, "Run this command:\n\n```bash\nkubectl get pods\n```")
    code = [c for c in chunks if c.chunk_type == "code_snippet"][0]
    assert code.content == "# Page > Install\nRun this command:\n\n```bash\nkubectl get pods\n```"
    assert code.metadata["language"] == "bash"
    assert code.metadata["breadcrumb_path"] == "Page > Install"
    assert code.metadata["code_caption"] == "Run this command:"


def test_code_chunk_without_lead_in_keeps_breadcrumb(tmp_path):
    chunks = _chunks(tmp_path, "The tool is fast and small.\n\n```bash\nkubectl get pods\n```")
    code = [c for c in chunks if c.chunk_type == "code_snippet"][0]
    assert code.content == "# Page > Install\n\n```bash\nkubectl get pods\n```"
    assert "code_caption" not in code.metadata


def test_code_chunk_without_any_context_stays_raw(tmp_path):
    f = tmp_path / "llms-full.txt"
    f.write_text("```bash\nkubectl get pods\n```\n", encoding="utf-8")
    code = [c for c in FileProcessor().process_file(f) if c.chunk_type == "code_snippet"][0]
    assert code.content == "kubectl get pods"


class PanelOwner(ProcessingStrategy):
    """Declares <Panel> and leaves it to the built-in strategies."""

    block_tags = ("Panel",)

    def can_process(self, node) -> bool:
        return False

    def process(self, node, source_file: Path):
        return []


class PanelConfig(OpenCraneConfig):
    chunking_strategies = [PanelOwner(), *OpenCraneConfig.chunking_strategies]


def test_code_inside_mixed_node_takes_lead_in_from_text_before_it(tmp_path):
    body = "<Panel>\n\n### CLI\n\nCheck the status:\n\n```bash\nkubectl get jobs\n```\n\n</Panel>"
    code = [c for c in _chunks(tmp_path, body, PanelConfig()) if c.chunk_type == "code_snippet"][0]
    assert code.content == "# Page > Install > CLI\nCheck the status:\n\n```bash\nkubectl get jobs\n```"


class Wrapper(ProcessingStrategy):
    """Sends the body of its block through chunk_text."""

    block_tags = ("Wrap",)

    def can_process(self, node) -> bool:
        return False

    def process(self, node, source_file: Path):
        body = "\n".join(node.text.split("\n")[1:-1])
        return self.chunk_text(body, node, source_file)


class WrapConfig(OpenCraneConfig):
    chunking_strategies = [Wrapper(), *OpenCraneConfig.chunking_strategies]


def test_code_from_chunk_text_carries_part_heading_and_lead_in(tmp_path):
    body = "<Wrap>\n### CLI\n\nRun this command:\n\n```bash\nkubectl get netcapturejob\n```\n</Wrap>"
    code = [c for c in _chunks(tmp_path, body, WrapConfig()) if c.chunk_type == "code_snippet"][0]
    assert code.content == "# Page > Install > CLI\nRun this command:\n\n```bash\nkubectl get netcapturejob\n```"


def test_list_from_chunk_text_carries_lead_in(tmp_path):
    body = "<Wrap>\n#### CLI\n\nTo install the CDF extension using CLI:\n\n1. Create a YAML file.\n2. Apply it.\n</Wrap>"
    items = [c for c in _chunks(tmp_path, body, WrapConfig()) if c.chunk_type == "list_item"]
    assert items[0].content == "# Page > Install > CLI\nTo install the CDF extension using CLI:\n1. Create a YAML file."


def test_lead_in_line_rules():
    from opencrane.rag.services.utils.markdown_structure import lead_in_line

    assert lead_in_line("") is None
    assert lead_in_line("Intro.\n\nRun this command:\n\n") == "Run this command:"
    assert lead_in_line("| a | b |") is None
    assert lead_in_line("```") is None
