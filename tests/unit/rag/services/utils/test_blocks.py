"""Tests for the declared content block finder."""

from opencrane.rag.services.utils.blocks import BlockSpan, find_blocks


def test_single_block():
    lines = ["intro", "<details>", "body", "</details>", "after"]
    assert find_blocks(lines, ["details"]) == [BlockSpan(1, 3, "details")]


def test_attributes_and_one_line_summary():
    lines = ["<details open><summary>More</summary>", "body", "</details>"]
    assert find_blocks(lines, ["details"]) == [BlockSpan(0, 2, "details")]


def test_closing_tag_after_content():
    assert find_blocks(["<details>", "last line</details>", "x"], ["details"]) == [BlockSpan(0, 1, "details")]


def test_open_and_close_on_one_line():
    assert find_blocks(["<details>x</details>", "after"], ["details"]) == [BlockSpan(0, 0, "details")]


def test_same_tag_nesting_is_one_block():
    lines = ["<details>", "<details>", "in", "</details>", "</details>"]
    assert find_blocks(lines, ["details"]) == [BlockSpan(0, 4, "details")]


def test_case_must_match():
    assert find_blocks(["<Details>", "x", "</Details>"], ["details"]) == []


def test_longer_tag_name_does_not_open():
    assert find_blocks(["<detailsx>", "</detailsx>"], ["details"]) == []


def test_inline_mention_and_fenced_example_do_not_open():
    lines = ["use the `<details>` tag", "```md", "<details>", "```"]
    assert find_blocks(lines, ["details"]) == []


def test_closing_tag_in_fence_inside_block_is_ignored():
    lines = ["<details>", "```", "</details>", "```", "</details>"]
    assert find_blocks(lines, ["details"]) == [BlockSpan(0, 4, "details")]


def test_unclosed_block_runs_to_end():
    assert find_blocks(["<details>", "a", "b"], ["details"]) == [BlockSpan(0, 2, "details")]


def test_other_declared_tag_inside_block_stays_inside():
    lines = ["<Tabs>", "<details>", "x", "</details>", "</Tabs>"]
    assert find_blocks(lines, ["Tabs", "details"]) == [BlockSpan(0, 4, "Tabs")]


def test_two_blocks_in_order():
    lines = ["<details>", "a", "</details>", "text", "<Tabs>", "b", "</Tabs>"]
    assert find_blocks(lines, ["details", "Tabs"]) == [BlockSpan(0, 2, "details"), BlockSpan(4, 6, "Tabs")]


def test_no_tags_declared():
    assert find_blocks(["<details>", "</details>"], []) == []
