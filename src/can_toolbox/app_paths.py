"""Locations of bundled resources and user configuration, frozen or from source."""

from __future__ import annotations

import sys
from pathlib import Path

# Repository root in a checkout; the folder holding the archive in a zipapp.
_SOURCE_ROOT = Path(__file__).resolve().parents[2]


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_path(filename: str) -> Path:
    """Return a file under ``resources/`` in a PyInstaller bundle, zipapp or checkout.

    A zipapp ships ``resources/`` next to the archive, which is ``_SOURCE_ROOT``.
    """
    if _is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "resources" / filename
    return _SOURCE_ROOT / "resources" / filename


def changelog_path() -> Path:
    """Use packaged release history, or the full changelog in a source checkout."""
    bundled = resource_path("CHANGELOG.md")
    if bundled.is_file():
        return bundled
    return _SOURCE_ROOT / "CHANGELOG.md"


def application_directory() -> Path:
    """Folder searched for user configuration such as ``signal_mapping.yaml``.

    The executable's folder when frozen, the archive's folder for a zipapp,
    otherwise the current working directory.
    """
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    archive = _zipapp_path()
    if archive is not None:
        return archive.parent
    return Path.cwd()


def _zipapp_path() -> Path | None:
    """Return the running ``.pyz``/``.pyzw`` archive, if the package was loaded from one."""
    for parent in Path(__file__).resolve().parents:
        if parent.suffix.lower() in {".pyz", ".pyzw"} and parent.is_file():
            return parent
    return None
