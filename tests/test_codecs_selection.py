import os

import pytest

from lowpack.codecs import CODECS
from lowpack.selection import select_codec


@pytest.mark.parametrize("name", ["store", "zlib", "zstd"])
def test_codec_round_trip(name: str) -> None:
    data = (b"compressible data " * 1000) + os.urandom(64)
    packed = CODECS[name].compress(data)
    assert CODECS[name].decompress(packed, expected_size=len(data)) == data


def test_selection_is_explainable_and_bounded() -> None:
    selected = select_codec(b"x" * 1_000_000)
    assert selected.codec in CODECS
    assert all(candidate["sample_bytes"] <= 256 * 1024 for candidate in selected.candidates)
    assert selected.reason


def test_store_selected_for_png_magic_random_data() -> None:
    selected = select_codec(b"\x89PNG\r\n\x1a\n" + os.urandom(8192), already_compressed=True)
    assert selected.codec == "store"
