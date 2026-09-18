"""Locates files under config/ regardless of how this package is installed.

In an editable install (`uv sync` during local dev), `__file__` points into
the repo source tree, so config/ is found by walking up to the repo root.
In a built/installed wheel (e.g. deployed to Arcade), config/ is bundled as
package data alongside this package (see pyproject.toml's
`force-include`), not at some repo root that no longer exists on disk --
so a hardcoded parent-count walk from `__file__` silently breaks the moment
this package is installed normally instead of in editable mode.
"""

from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent


def config_path(filename: str) -> Path:
    packaged = _PACKAGE_DIR / "config" / filename
    if packaged.exists():
        return packaged

    repo_root_config = _PACKAGE_DIR.parents[1] / "config" / filename
    if repo_root_config.exists():
        return repo_root_config

    raise FileNotFoundError(
        f"Could not locate config/{filename} -- checked {packaged} "
        f"(installed package data) and {repo_root_config} (editable install repo root)"
    )
