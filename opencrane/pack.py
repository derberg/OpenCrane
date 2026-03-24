"""Core packing logic for the opencrane pack command."""

import importlib.metadata
import re
import shutil
import subprocess
import sys
from pathlib import Path

import click

from opencrane.templates import PACK_MAIN_PY, PACK_PYPROJECT, PACK_README

_PEP508_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]*$")


def _find_wheel(output: Path) -> Path | None:
    dist = output / "dist"
    if dist.exists():
        wheels = list(dist.glob("*.whl"))
        if wheels:
            return wheels[0]
    return None


def pack(
    name: str, version: str = "1.0.0", output: Path | None = None
) -> tuple[Path, Path | None]:
    """Generate a standalone MCP server package from built OpenCrane data.

    Returns a tuple of (output_directory, wheel_path_or_none).
    """
    # 1. Validate name against PEP 508
    if not _PEP508_NAME_RE.match(name):
        raise click.BadParameter(
            f"Invalid package name '{name}'. "
            "Must start with a letter and contain only letters, digits, hyphens, underscores, or dots.",
            param_hint="'--name'",
        )

    # 2. Validate required data files exist
    milvus_db = Path(".opencrane/milvus.db")
    chunks_json = Path(".opencrane/chunks.json")
    if not milvus_db.exists() or not chunks_json.exists():
        raise click.ClickException(
            "Required data files not found. Run 'opencrane build' first."
        )

    # 3. Resolve output directory
    if output is None:
        output = Path(f".opencrane/pack/{name}/")

    # 4. Derive module_name (hyphens and dots to underscores)
    module_name = re.sub(r"[-.]", "_", name)

    # 5. Get opencrane version
    opencrane_version = importlib.metadata.version("opencrane")

    # 6. Create the package structure
    module_dir = output / module_name
    data_dir = module_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Write pyproject.toml
    (output / "pyproject.toml").write_text(
        PACK_PYPROJECT.format(
            name=name,
            module_name=module_name,
            version=version,
            opencrane_version=opencrane_version,
        )
    )

    # Write module files
    (module_dir / "__init__.py").write_text("")
    (module_dir / "__main__.py").write_text(PACK_MAIN_PY)

    # Copy data files
    shutil.copy2(milvus_db, data_dir / "milvus.db")
    shutil.copy2(chunks_json, data_dir / "chunks.json")

    # Copy metadata-schema.md if it exists
    for candidate in [
        Path("docs/metadata-schema.md"),
        Path(".opencrane/metadata-schema.md"),
    ]:
        if candidate.exists():
            shutil.copy2(candidate, data_dir / "metadata-schema.md")
            break

    # Write README.md
    (output / "README.md").write_text(PACK_README.format(name=name))

    # 7. Build the wheel (optional)
    wheel_path = None
    try:
        subprocess.run(
            [sys.executable, "-m", "build", "--wheel", str(output)],
            check=True,
            capture_output=True,
        )
        wheel_path = _find_wheel(output)
    except Exception:
        pass

    # 8. Return output directory and wheel path
    return output, wheel_path
