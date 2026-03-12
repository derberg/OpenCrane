#!/usr/bin/env python3

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from opencrane.shared.config import get_config
from opencrane.shared.utils.token_counter import get_token_count


@dataclass
class TokenSummary:
    folder_name: str
    token_count: int
    file_count: int


@dataclass
class TokenReport:
    summaries: List[TokenSummary]
    total_tokens: int
    generated_at: datetime
    source_directory: str


def count_tokens_in_file(file_path: Path) -> int:
    """Count tokens in a file using configured tokenizer.
    
    Returns 0 if file cannot be read as text.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
        return get_token_count(text)
    except (UnicodeDecodeError, OSError):
        # Skip binary or unreadable files
        return 0


def generate_report(llmstxt_base: Path) -> TokenReport:
    """Generate token count report for all source directories under llmstxt/."""
    summaries = []
    total_tokens = 0

    if not llmstxt_base.exists():
        return TokenReport([], 0, datetime.now(timezone.utc), str(llmstxt_base))

    # Read root llms-full.txt directly if present (the all-projects combined file)
    root_combined = llmstxt_base / "llms-full.txt"
    has_root_combined = root_combined.exists() and root_combined.is_file()
    if has_root_combined:
        total_tokens = count_tokens_in_file(root_combined)

    # Process each source directory (e.g., external-sources, content-guidelines)
    for source_dir in sorted(llmstxt_base.iterdir()):
        if not source_dir.is_dir():
            continue

        source_name = source_dir.name
        root_tokens = None

        # Check for root-level llms-full.txt in this source
        root_llms = source_dir / "llms-full.txt"
        if root_llms.exists() and root_llms.is_file():
            root_tokens = count_tokens_in_file(root_llms)
            summaries.append(TokenSummary(source_name, root_tokens, 1))

        # Count tokens for project subdirectories (one level deep)
        project_tokens_total = 0
        for folder in sorted(source_dir.iterdir()):
            if folder.is_dir():
                # Count tokens only from llms-full.txt in this folder
                folder_llms = folder / "llms-full.txt"
                if folder_llms.exists() and folder_llms.is_file():
                    folder_tokens = count_tokens_in_file(folder_llms)
                    summaries.append(TokenSummary(f"{source_name}/{folder.name}", folder_tokens, 1))
                    project_tokens_total += folder_tokens

                # Also count subfolders one level deeper
                for subfolder in sorted(folder.iterdir()):
                    if subfolder.is_dir():
                        subfolder_llms = subfolder / "llms-full.txt"
                        if subfolder_llms.exists() and subfolder_llms.is_file():
                            subfolder_tokens = count_tokens_in_file(subfolder_llms)
                            summaries.append(TokenSummary(f"{source_name}/{folder.name}/{subfolder.name}", subfolder_tokens, 1))
                            project_tokens_total += subfolder_tokens

        # Only accumulate into total when there's no root combined file to use
        if not has_root_combined:
            if root_tokens is not None:
                total_tokens += root_tokens
            else:
                total_tokens += project_tokens_total

    return TokenReport(summaries, total_tokens, datetime.now(timezone.utc), str(llmstxt_base))


def write_report_to_markdown(report: TokenReport, output_file: Path):
    """Write the token report to a markdown file."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# Token Count Summary\n\n")
        f.write("This table lists token counts for each `llms-full.txt` file generated at various levels of the documentation hierarchy.\n\n")
        f.write("| Folder | Tokens |\n")
        f.write("|--------|--------|\n")
        
        # Write all-projects summary first
        f.write(f"| [all-projects](llms-full.txt) | {report.total_tokens:,} |\n")
        
        # Write individual project summaries
        for summary in report.summaries:
            # If no slash, it's a root-level source file
            if "/" not in summary.folder_name:
                link_target = f"{summary.folder_name}/llms-full.txt"
            else:
                link_target = f"{summary.folder_name}/llms-full.txt"
            f.write(f"| [{summary.folder_name}]({link_target}) | {summary.token_count:,} |\n")
        
        f.write("\n*Note: This file is auto-generated. Manual edits will be overwritten.*\n")


def main(source_dir=None, output_file=None):
    """Generate token count report.

    Args:
        source_dir: Directory containing llmstxt output to count. Falls back to
            ``TOKEN_SOURCE_DIR`` env var, then ``llmstxt``.
        output_file: Path for the generated markdown report. Falls back to
            ``TOKEN_OUTPUT_FILE`` env var, then ``llmstxt/README.md``.
    """
    try:
        config = get_config()
        llmstxt_base = source_dir or config.token_source_dir
        report_output = output_file or config.token_output_file
        report = generate_report(llmstxt_base)
        write_report_to_markdown(report, report_output)
        print(f"Report written to {report_output}")
    except Exception as e:
        print(f"Error generating report: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
