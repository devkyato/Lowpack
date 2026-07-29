from __future__ import annotations

import base64
import json
import os
import stat
import tracemalloc
from pathlib import Path

import pytest
from hostile_archive_factory import rewrite_manifest

import lowpack.archive as archive_module
from lowpack import pack, unpack, verify_archive
from lowpack.archive import MAX_TRANSFORM_SIZE, _read_manifest, _validate_manifest
from lowpack.format import FormatError
from lowpack.manifest import decode_manifest, encode_manifest
from lowpack.profiles.base import EncodedData
from lowpack.profiles.telemetry import MAGIC, TRANSFORMER


def _manifest(path: Path) -> tuple[dict, int]:
    with path.open("rb") as stream:
        value, _, footer = _read_manifest(stream)
    return value, footer.manifest_offset


def test_direct_duplicate_basenames_are_rejected(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    (first / "config.json").write_text("a", encoding="utf-8")
    (second / "config.json").write_text("b", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate or case-colliding"):
        pack([first / "config.json", second / "config.json"], tmp_path / "bad.lpk")


def test_duplicate_source_identity_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "same.txt"
    source.write_text("same", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate input file identity"):
        pack([source, source], tmp_path / "bad.lpk")


def test_output_and_temporary_file_are_excluded_from_input(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.txt").write_text("data", encoding="utf-8")
    target = source / "archive.lpk"
    target.write_bytes(b"previous archive")
    result = pack([source], target, overwrite=True)
    manifest, _ = _manifest(target)
    assert [item["path"] for item in manifest["files"]] == ["source/data.txt"]
    assert "source/archive.lpk" in result.excluded
    assert not any(".tmp" in item["path"] for item in manifest["files"])


def test_dictionary_sampling_never_uses_whole_file_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for index in range(8):
        (source / f"module_{index}.py").write_text(
            "def value():\n    return 'bounded sample'\n" * 20,
            encoding="utf-8",
        )

    def forbidden_read_bytes(_path: Path) -> bytes:
        raise AssertionError("Path.read_bytes() would read the complete source")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    pack([source], tmp_path / "bounded.lpk", profile="source")


def test_source_mutation_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "changing.bin"
    source.write_bytes(b"a" * 16_384)
    original = archive_module._iter_stream_chunks
    changed = False

    def mutate_after_first(stream: object, chunk_size: int):
        nonlocal changed
        for chunk in original(stream, chunk_size):  # type: ignore[arg-type]
            yield chunk
            if not changed:
                changed = True
                with source.open("ab") as output:
                    output.write(b"changed")

    monkeypatch.setattr(archive_module, "_iter_stream_chunks", mutate_after_first)
    with pytest.raises(OSError, match="source changed while packing"):
        pack([source], tmp_path / "changing.lpk", chunk_size=4096)


def test_followed_symlink_cycle_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "tree"
    child = source / "child"
    child.mkdir(parents=True)
    try:
        (child / "loop").symlink_to(source, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    with pytest.raises(ValueError, match="directory traversal cycle"):
        pack([source], tmp_path / "cycle.lpk", follow_symlinks=True)


def test_dedup_records_preferred_and_actual_codec(tmp_path: Path) -> None:
    source = tmp_path / "mixed"
    source.mkdir()
    common = b"C" * 4096
    first_prefix = os.urandom(256 * 1024)
    second_prefix = (b"compress-me-" * (256 * 1024))[: 256 * 1024]
    (source / "a-random.bin").write_bytes(first_prefix + common)
    (source / "b-text.txt").write_bytes(second_prefix + common)
    archive = tmp_path / "mixed.lpk"
    pack([source], archive, chunk_size=4096)
    manifest, _ = _manifest(archive)
    second = manifest["files"][1]
    assert any(
        value["reused"]
        and value["actual_codec"] != second["decision"]["preferred_codec"]
        for value in second["chunk_decisions"]
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics required")
def test_permissions_are_opt_in_and_masked(tmp_path: Path) -> None:
    source = tmp_path / "script.sh"
    source.write_text("#!/bin/sh\n", encoding="utf-8")
    source.chmod(0o4755)
    archive = tmp_path / "permissions.lpk"
    pack([source], archive, store_permissions=True)
    manifest, _ = _manifest(archive)
    assert manifest["files"][0]["mode"] == 0o755

    default_output = tmp_path / "default"
    unpack(archive, output=default_output)
    assert stat.S_IMODE((default_output / "script.sh").stat().st_mode) != 0o755

    restored_output = tmp_path / "restored"
    unpack(archive, output=restored_output, restore_permissions=True)
    assert stat.S_IMODE((restored_output / "script.sh").stat().st_mode) == 0o755


def test_telemetry_rejects_amplifying_metadata() -> None:
    payload = {
        "columns": [],
        "header": [],
        "row_count": 1_000_001,
    }
    encoded = MAGIC + json.dumps(payload, separators=(",", ":")).encode()
    with pytest.raises(ValueError, match="row count exceeds"):
        TRANSFORMER.decode(
            EncodedData(encoded, {"id": TRANSFORMER.id, "mode": "canonical"}),
            max_output_size=MAX_TRANSFORM_SIZE,
            expected_output_size=10,
        )


def test_telemetry_rejects_run_length_amplification() -> None:
    payload = {
        "columns": [
            {
                "encoding": "rle",
                "name": "value",
                "null_bitmap": base64.b64encode(b"\x00").decode(),
                "row_count": 1,
                "runs": [["x", 1_000_000]],
                "type": "string",
            }
        ],
        "header": ["value"],
        "row_count": 1,
    }
    encoded = MAGIC + json.dumps(payload, separators=(",", ":")).encode()
    with pytest.raises(ValueError, match="runs exceed"):
        TRANSFORMER.decode(
            EncodedData(encoded, {"id": TRANSFORMER.id, "mode": "canonical"}),
            expected_output_size=2,
        )


def test_manifest_relationship_validation(tmp_path: Path) -> None:
    source = tmp_path / "data.bin"
    source.write_bytes(b"a" * 9000)
    archive = tmp_path / "data.lpk"
    pack([source], archive, chunk_size=4096)
    manifest, offset = _manifest(archive)

    manifest["files"][0]["hash"] = "A" * 64
    with pytest.raises(FormatError):
        _validate_manifest(manifest, manifest_offset=offset)


def test_manifest_rejects_chunk_overlap(tmp_path: Path) -> None:
    source = tmp_path / "data.bin"
    source.write_bytes(b"A" * 9000)
    archive = tmp_path / "data.lpk"
    pack([source], archive, chunk_size=4096, codec="store")
    manifest, offset = _manifest(archive)
    records = sorted(manifest["chunks"].values(), key=lambda value: value["offset"])
    records[1]["offset"] = records[0]["offset"]
    with pytest.raises(FormatError, match="ordering or overlap"):
        _validate_manifest(manifest, manifest_offset=offset)


def test_manifest_rejects_aggregate_chunk_reference_overflow(tmp_path: Path) -> None:
    source = tmp_path / "data"
    source.mkdir()
    for index in range(3):
        (source / f"{index}.bin").write_bytes(b"A" * 4096)
    archive = tmp_path / "data.lpk"
    pack([source], archive, chunk_size=4096, codec="store")
    manifest, offset = _manifest(archive)
    with pytest.raises(FormatError, match="aggregate chunk-reference"):
        _validate_manifest(manifest, manifest_offset=offset, max_chunks=2)


def test_manifest_total_object_limit_is_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lowpack.manifest as manifest_module

    monkeypatch.setattr(manifest_module, "MAX_MANIFEST_OBJECTS", 3)
    encoded = encode_manifest({"a": [{"b": 1}]})
    with pytest.raises(FormatError, match="object count"):
        decode_manifest(encoded)


def test_dictionary_must_match_chunk_codec(tmp_path: Path) -> None:
    source = tmp_path / "dictionary-project"
    source.mkdir()
    for index in range(8):
        (source / f"module_{index}.py").write_text(
            ("def repeated(value):\n" f"    return value + {index}\n") * 30,
            encoding="utf-8",
        )
    archive = tmp_path / "dictionary.lpk"
    pack([source], archive, profile="source", codec="zstd")
    manifest, offset = _manifest(archive)
    record = next(
        value for value in manifest["chunks"].values() if "dictionary_id" in value
    )
    record["codec"] = "zlib"
    with pytest.raises(FormatError, match="dictionary reference"):
        _validate_manifest(manifest, manifest_offset=offset)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda manifest: manifest["files"][0].update(hash="A" * 64),
        lambda manifest: manifest["files"][0].update(source_size=-1),
        lambda manifest: manifest["files"][0]["decision"].pop("reason"),
        lambda manifest: manifest["files"][0].update(mode=0o4755),
        lambda manifest: manifest.update(goal=42),
    ],
)
def test_authenticated_hostile_manifests_are_rejected(
    tmp_path: Path, mutation: object
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hostile manifest seed", encoding="utf-8")
    valid = tmp_path / "valid.lpk"
    pack([source], valid)
    hostile = rewrite_manifest(valid, tmp_path / "hostile.lpk", mutation)  # type: ignore[arg-type]
    result = verify_archive(hostile)
    assert not result.valid
    assert result.errors


def test_full_verification_and_extraction_have_bounded_python_memory(tmp_path: Path) -> None:
    source = tmp_path / "large.bin"
    block = os.urandom(1024 * 1024)
    with source.open("wb") as stream:
        for _ in range(16):
            stream.write(block)
    archive = tmp_path / "large.lpk"
    pack([source], archive, codec="store")

    tracemalloc.start()
    assert verify_archive(archive, full=True).valid
    _, verify_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    tracemalloc.start()
    unpack(archive, output=tmp_path / "out")
    _, unpack_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert verify_peak < 8 * 1024 * 1024
    assert unpack_peak < 8 * 1024 * 1024


def test_interrupted_extraction_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("payload", encoding="utf-8")
    archive = tmp_path / "source.lpk"
    pack([source], archive)
    output = tmp_path / "out"

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="simulated disk failure"):
        unpack(archive, output=output)
    assert not (output / "source.txt").exists()
    assert not list(output.glob("*.lowpack-tmp"))
