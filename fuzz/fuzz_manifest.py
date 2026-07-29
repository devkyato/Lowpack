"""Atheris target for canonical manifests and relationship validation."""

from __future__ import annotations

import sys

import atheris

with atheris.instrument_imports():
    from lowpack.archive import _validate_manifest
    from lowpack.format import FormatError
    from lowpack.manifest import decode_manifest


def test_one_input(data: bytes) -> None:
    try:
        manifest = decode_manifest(data)
        _validate_manifest(manifest, manifest_offset=16)
    except (
        FormatError,
        KeyError,
        OverflowError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        return


def main() -> None:
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
