from __future__ import annotations


class StoreCodec:
    id = "store"

    def compress(self, data: bytes, *, level: int | None = None) -> bytes:
        return data

    def decompress(self, data: bytes, *, expected_size: int) -> bytes:
        if len(data) != expected_size:
            raise ValueError("stored payload size mismatch")
        return data
