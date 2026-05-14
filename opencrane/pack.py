"""Core packing logic for the opencrane pack command."""

import importlib.metadata
import importlib.resources
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import click

from opencrane.templates import PACK_MAIN_PY, PACK_PYPROJECT, PACK_README

_PEP508_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]*$")


def _pkg_name(dep: str) -> str:
    """Normalise a PEP 508 specifier to a bare package name for comparison."""
    return re.split(r"[>=<!;\[ ]", dep)[0].strip().lower().replace("-", "_")


def _preserve_extra_deps(pyproject_path: Path, managed_deps: list[str]) -> str:
    """Return extra dependency lines from an existing pyproject.toml.

    Only deps not already covered by *managed_deps* are returned, formatted
    as indented TOML lines ready to splice into the template.
    """
    if not pyproject_path.exists():
        return ""
    try:
        with open(pyproject_path, "rb") as f:
            existing = tomllib.load(f)
    except Exception:
        return ""
    existing_deps = existing.get("project", {}).get("dependencies", [])
    managed_names = {_pkg_name(d) for d in managed_deps}
    extras = [d for d in existing_deps if _pkg_name(d) not in managed_names]
    if not extras:
        return ""
    return "".join(f'    "{dep}",\n' for dep in extras)


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
        output = Path(".opencrane/pack/")

    # 4. Derive module_name (hyphens and dots to underscores)
    module_name = re.sub(r"[-.]", "_", name)

    # 5. Get opencrane version
    opencrane_version = importlib.metadata.version("opencrane")

    # 6. Create the package structure
    module_dir = output / module_name
    data_dir = module_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Write pyproject.toml — preserve any user-added deps from a prior run
    managed_deps = [f"opencrane>={opencrane_version}"]
    extra_deps = _preserve_extra_deps(output / "pyproject.toml", managed_deps)
    (output / "pyproject.toml").write_text(
        PACK_PYPROJECT.format(
            name=name,
            module_name=module_name,
            version=version,
            opencrane_version=opencrane_version,
            extra_deps=extra_deps,
        )
    )

    # Write module files
    (module_dir / "__init__.py").write_text("")
    (module_dir / "__main__.py").write_text(PACK_MAIN_PY)

    # Copy data files
    shutil.copy2(milvus_db, data_dir / "milvus.db")
    shutil.copy2(chunks_json, data_dir / "chunks.json")

    # Copy metadata-schema.md from the installed package
    try:
        schema_content = (
            importlib.resources.files("opencrane.mcp")
            .joinpath("metadata-schema.md")
            .read_text(encoding="utf-8")
        )
        (data_dir / "metadata-schema.md").write_text(schema_content, encoding="utf-8")
    except Exception:
        pass  # Non-critical — tool will read from package at runtime

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
