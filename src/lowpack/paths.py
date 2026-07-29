"""Portable archive paths and safe extraction."""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

from .format import FormatError

DRIVE = re.compile(r"^[A-Za-z]:")


def normalize_archive_path(value: str) -> str:
    value = value.replace("\\", "/")
    if "\x00" in value or value.startswith(("/", "//")) or DRIVE.match(value):
        raise FormatError(f"unsafe archive path: {value!r}")
    path = PurePosixPath(value)
    if not value or any(part in ("", ".", "..") for part in path.parts):
        raise FormatError(f"unsafe archive path: {value!r}")
    return path.as_posix()


def safe_destination(root: Path, archive_path: str) -> Path:
    normalized = normalize_archive_path(archive_path)
    root_resolved = root.resolve()
    destination = root.joinpath(*PurePosixPath(normalized).parts)
    resolved_parent = destination.parent.resolve()
    try:
        resolved_parent.relative_to(root_resolved)
    except ValueError as exc:
        raise FormatError(f"path escapes extraction root: {archive_path!r}") from exc
    current = root_resolved
    for part in PurePosixPath(normalized).parts[:-1]:
        current /= part
        if current.is_symlink():
            raise FormatError(f"symlink in extraction path: {current}")
    return destination


def collision_key(value: str) -> str:
    return os.path.normcase(value).casefold()
