import pytest

from lowpack.format import FormatError
from lowpack.manifest import decode_manifest, encode_manifest


def test_manifest_is_canonical_and_unicode() -> None:
    value = {"z": 1, "a": "雪", "nested": {"b": 2, "a": 1}}
    data = encode_manifest(value)
    assert data == b'{"a":"\xe9\x9b\xaa","nested":{"a":1,"b":2},"z":1}'
    assert decode_manifest(data) == value


def test_noncanonical_manifest_rejected() -> None:
    with pytest.raises(FormatError):
        decode_manifest(b'{"z": 1, "a": 2}')
