"""Codec extension protocol."""

from __future__ import annotations

from typing import Protocol


class Codec(Protocol):
    id: str

    def compress(self, data: bytes, *, level: int | None = None) -> bytes: ...

    def decompress(self, data: bytes, *, expected_size: int) -> bytes: ...
