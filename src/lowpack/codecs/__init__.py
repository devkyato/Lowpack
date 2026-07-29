from __future__ import annotations

from typing import Any

from .store import StoreCodec
from .zlib_codec import ZlibCodec
from .zstd_codec import ZstdCodec

CODECS: dict[str, Any] = {
    "store": StoreCodec(),
    "zlib": ZlibCodec(),
    "zstd": ZstdCodec(),
}

__all__ = ["CODECS", "StoreCodec", "ZlibCodec", "ZstdCodec"]
