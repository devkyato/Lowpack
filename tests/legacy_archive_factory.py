"""Build format 1.0 fixtures from valid current archives."""

from __future__ import annotations

import base64
import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lowpack.archive import _read_manifest
from lowpack.format import CHUNK_HEADER, FOOTER, FOOTER_MAGIC, HEADER, MAGIC
from lowpack.hashing import sha256
from lowpack.manifest import encode_manifest

REVERSE_GOALS = {
    "balanced": "balanced",
    "smallest": "smallest",
    "prefer-store": "fastest",
    "prefer-zstd-low": "fastest-decode",
    "avoid-zlib": "low-memory",
}


def make_legacy_archive(
    current: Path,
    destination: Path,
    mutate: Callable[[dict[str, Any]], None] | None = None,
) -> Path:
    """Rewrite a current archive as an authenticated format 1.0 archive."""

    data = current.read_bytes()
    with current.open("rb") as stream:
        manifest, _, footer = _read_manifest(stream)
    legacy = copy.deepcopy(manifest)
    dictionaries = legacy.pop("dictionaries")
    legacy.pop("manifest_schema")
    legacy["format"] = {"major": 1, "minor": 0}
    legacy["goal"] = REVERSE_GOALS[legacy["goal"]]
    legacy["lowpack_version"] = "0.1.2"
    for record in legacy["chunks"].values():
        dictionary_id = record.pop("dictionary_id", None)
        if dictionary_id is not None:
            record["dictionary"] = dictionaries[dictionary_id]["data"]
    legacy["source_dictionaries"] = {
        group: {
            "bytes": dictionaries[record["dictionary_id"]]["size"],
            "hash": record["dictionary_id"],
        }
        for group, record in legacy["source_dictionaries"].items()
    }
    for item in legacy["files"]:
        item.pop("chunk_decisions")
        item["decision"]["final_codec"] = item["decision"].pop("preferred_codec")
    if mutate is not None:
        mutate(legacy)
    encoded = encode_manifest(legacy)
    header = HEADER.pack(MAGIC, 1, 0, 0)
    payload = data[HEADER.size : footer.manifest_offset]
    body = header + payload + encoded
    destination.write_bytes(
        body
        + FOOTER.pack(
            FOOTER_MAGIC,
            1,
            0,
            footer.manifest_offset,
            len(encoded),
            sha256(encoded),
            sha256(body),
        )
    )
    return destination


def corrupt_payload(archive: Path, *, reauthenticate: bool = False) -> None:
    with archive.open("rb") as stream:
        _, _, footer = _read_manifest(stream)
    data = bytearray(archive.read_bytes())
    data[HEADER.size + CHUNK_HEADER.size] ^= 0x01
    if reauthenticate:
        footer_start = len(data) - FOOTER.size
        fields = list(FOOTER.unpack(data[footer_start:]))
        fields[-1] = sha256(
            data[: footer.manifest_offset + footer.manifest_size]
        )
        data[footer_start:] = FOOTER.pack(*fields)
    archive.write_bytes(data)


def dictionary_bytes(manifest: dict[str, Any]) -> dict[str, bytes]:
    """Decode a manifest dictionary catalog for focused assertions."""

    return {
        identifier: base64.b64decode(record["data"], validate=True)
        for identifier, record in manifest["dictionaries"].items()
    }
