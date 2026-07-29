from pathlib import Path

from lowpack import inspect_archive, pack


def test_deterministic_bytes(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "b").write_bytes(b"B" * 9000)
    (source / "a").write_bytes(b"A" * 9000)
    first, second = tmp_path / "one.lpk", tmp_path / "two.lpk"
    pack([source], first, chunk_size=4096)
    pack([source], second, chunk_size=4096)
    assert first.read_bytes() == second.read_bytes()


def test_duplicate_files_and_chunks_are_deduplicated(tmp_path: Path) -> None:
    source = tmp_path / "same"
    source.mkdir()
    payload = b"duplicate" * 2000
    (source / "one").write_bytes(payload)
    (source / "two").write_bytes(payload)
    archive = tmp_path / "same.lpk"
    pack([source], archive, chunk_size=4096)
    info = inspect_archive(archive)
    assert info.unique_chunk_count < info.chunk_count
