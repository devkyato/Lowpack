from __future__ import annotations

import zlib


class ZlibCodec:
    id = "zlib"

    def compress(self, data: bytes, *, level: int | None = None) -> bytes:
        return zlib.compress(data, 6 if level is None else level)

    def decompress(self, data: bytes, *, expected_size: int) -> bytes:
        result = zlib.decompress(data)
        if len(result) != expected_size:
            raise ValueError("zlib payload size mismatch")
        return result
