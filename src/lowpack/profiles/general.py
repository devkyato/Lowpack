"""Conservative already-compressed format detection."""

from __future__ import annotations

MAGICS = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"RIFF",
    b"ID3",
    b"\x00\x00\x00\x18ftyp",
    b"%PDF-",
    b"PK\x03\x04",
    b"\x1f\x8b",
    b"7z\xbc\xaf'\x1c",
    b"Rar!\x1a\x07",
    b"LOWPACK\x00",
)


def is_already_compressed(sample: bytes) -> bool:
    return any(sample.startswith(magic) for magic in MAGICS)
