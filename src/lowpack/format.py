"""LowPack v1 binary framing."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO

MAGIC = b"LOWPACK\x00"
CHUNK_MAGIC = b"LPCK"
FOOTER_MAGIC = b"LPKFOOT\x00"
VERSION_MAJOR = 1
VERSION_MINOR = 1
HEADER = struct.Struct(">8sHHI")
CHUNK_HEADER = struct.Struct(">4sB3xQQ32s")
FOOTER = struct.Struct(">8sHHQQ32s32s")
CODEC_IDS = {"store": 0, "zlib": 1, "zstd": 2}
CODEC_NAMES = {value: key for key, value in CODEC_IDS.items()}


class FormatError(ValueError):
    """The archive framing or manifest is invalid."""


@dataclass(frozen=True)
class Footer:
    manifest_offset: int
    manifest_size: int
    manifest_hash: bytes
    body_hash: bytes


def write_header(stream: BinaryIO) -> None:
    stream.write(HEADER.pack(MAGIC, VERSION_MAJOR, VERSION_MINOR, 0))


def read_header(stream: BinaryIO) -> tuple[int, int, int]:
    raw = stream.read(HEADER.size)
    if len(raw) != HEADER.size:
        raise FormatError("truncated LowPack header")
    magic, major, minor, flags = HEADER.unpack(raw)
    if magic != MAGIC:
        raise FormatError("invalid LowPack magic")
    if major != VERSION_MAJOR or minor > VERSION_MINOR:
        raise FormatError(f"unsupported LowPack format version {major}.{minor}")
    if flags:
        raise FormatError(f"unsupported header flags: {flags:#x}")
    return major, minor, flags


def read_footer(stream: BinaryIO) -> Footer:
    stream.seek(0, 2)
    size = stream.tell()
    if size < HEADER.size + FOOTER.size:
        raise FormatError("truncated LowPack archive")
    stream.seek(-FOOTER.size, 2)
    raw = stream.read(FOOTER.size)
    magic, major, minor, offset, length, manifest_hash, body_hash = FOOTER.unpack(raw)
    if magic != FOOTER_MAGIC:
        raise FormatError("invalid or missing LowPack footer")
    if major != VERSION_MAJOR or minor > VERSION_MINOR:
        raise FormatError(f"unsupported footer version {major}.{minor}")
    if offset < HEADER.size or length > size - FOOTER.size - offset:
        raise FormatError("manifest location is outside the archive")
    return Footer(offset, length, manifest_hash, body_hash)
