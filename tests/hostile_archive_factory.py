"""Helpers for building internally authenticated hostile LowPack archives."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lowpack.archive import _read_manifest
from lowpack.format import FOOTER, FOOTER_MAGIC, VERSION_MAJOR, VERSION_MINOR
from lowpack.hashing import sha256
from lowpack.manifest import encode_manifest


def rewrite_manifest(
    source: Path,
    destination: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> Path:
    """Rewrite a valid archive with a mutated, correctly hashed manifest."""

    data = source.read_bytes()
    with source.open("rb") as stream:
        manifest, _, footer = _read_manifest(stream)
    hostile = copy.deepcopy(manifest)
    mutate(hostile)
    encoded = encode_manifest(hostile)
    body = data[: footer.manifest_offset] + encoded
    destination.write_bytes(
        body
        + FOOTER.pack(
            FOOTER_MAGIC,
            VERSION_MAJOR,
            VERSION_MINOR,
            footer.manifest_offset,
            len(encoded),
            sha256(encoded),
            sha256(body),
        )
    )
    return destination
