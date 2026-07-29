from pathlib import Path

import pytest

from lowpack import inspect_archive, pack, unpack, verify_archive


def test_single_file_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "hello.txt"
    source.write_bytes(b"hello\0world\n" * 1000)
    archive = tmp_path / "hello.lpk"
    result = pack([source], archive)
    restored = tmp_path / "restored"
    unpack(archive, output=restored)
    assert (restored / "hello.txt").read_bytes() == source.read_bytes()
    assert result.file_count == 1
    assert verify_archive(archive).valid


def test_directory_empty_unicode_and_multiple_chunks(tmp_path: Path) -> None:
    source = tmp_path / "corpus"
    (source / "empty").mkdir(parents=True)
    (source / "unicodé").mkdir()
    (source / "unicodé" / "雪.txt").write_bytes(b"abc" * 5000)
    (source / "zero").write_bytes(b"")
    archive = tmp_path / "corpus.lpk"
    pack([source], archive, chunk_size=4096)
    info = inspect_archive(archive)
    assert info.chunk_count >= 4
    restored = tmp_path / "restored"
    unpack(archive, output=restored)
    assert (restored / "corpus" / "empty").is_dir()
    assert (restored / "corpus" / "unicodé" / "雪.txt").read_bytes() == b"abc" * 5000
    assert (restored / "corpus" / "zero").read_bytes() == b""


def test_existing_file_requires_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "item"
    source.write_text("new", encoding="utf-8")
    archive = tmp_path / "a.lpk"
    pack([source], archive)
    output = tmp_path / "out"
    output.mkdir()
    (output / "item").write_text("old", encoding="utf-8")
    with pytest.raises(FileExistsError):
        unpack(archive, output=output)
    unpack(archive, output=output, overwrite=True)
    assert (output / "item").read_text(encoding="utf-8") == "new"


def test_selective_extraction(tmp_path: Path) -> None:
    source = tmp_path / "tree"
    source.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    (source / "b.txt").write_text("b", encoding="utf-8")
    archive = tmp_path / "tree.lpk"
    pack([source], archive)
    output = tmp_path / "selected"
    unpack(archive, output=output, paths=["tree/a.txt"])
    assert (output / "tree" / "a.txt").read_text(encoding="utf-8") == "a"
    assert not (output / "tree" / "b.txt").exists()
