from pathlib import Path

import pytest

from lowpack import pack, unpack, verify_archive
from lowpack.format import FormatError
from lowpack.paths import normalize_archive_path, safe_destination


@pytest.mark.parametrize(
    "value",
    ["../escape", "/absolute", r"C:\drive", r"\\server\share", "bad\x00name", "a/../b"],
)
def test_unsafe_paths_rejected(value: str) -> None:
    with pytest.raises(FormatError):
        normalize_archive_path(value)


def test_parent_symlink_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(FormatError):
        safe_destination(root, "link/file")


def test_expansion_limit_can_be_lowered(tmp_path: Path) -> None:
    source = tmp_path / "large"
    source.write_bytes(b"x" * 1024)
    archive = tmp_path / "limited.lpk"
    pack([source], archive)
    with pytest.raises(FormatError, match="extraction-size"):
        unpack(archive, output=tmp_path / "out", max_extract_size=100)


@pytest.mark.parametrize("location", ["header", "chunk", "manifest", "footer", "truncate"])
def test_corruption_is_detected(tmp_path: Path, location: str) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"payload" * 5000)
    archive = tmp_path / "archive.lpk"
    pack([source], archive, chunk_size=4096)
    data = bytearray(archive.read_bytes())
    if location == "header":
        data[0] ^= 1
    elif location == "chunk":
        data[80] ^= 1
    elif location == "manifest":
        data[-100] ^= 1
    elif location == "footer":
        data[-84] ^= 1
    else:
        data = data[:-10]
    archive.write_bytes(data)
    result = verify_archive(archive)
    assert not result.valid
    assert result.errors
