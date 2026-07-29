from __future__ import annotations

import zstandard


class ZstdCodec:
    id = "zstd"

    def compress(self, data: bytes, *, level: int | None = None) -> bytes:
        return zstandard.ZstdCompressor(level=3 if level is None else level).compress(data)

    def decompress(self, data: bytes, *, expected_size: int) -> bytes:
        result = zstandard.ZstdDecompressor().decompress(data, max_output_size=expected_size)
        if len(result) != expected_size:
            raise ValueError("zstd payload size mismatch")
        return result
