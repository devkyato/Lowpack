import base64
import hashlib
import json
from pathlib import Path

import pytest
from legacy_archive_factory import corrupt_payload, make_legacy_archive

from lowpack import (
    migrate_archive,
    pack,
    probe_compatibility,
    unpack,
    verify_archive,
)
from lowpack.archive import _read_manifest
from lowpack.cli import main
from lowpack.format import FormatError

FIXTURES = Path(__file__).parent / "fixtures"


def test_golden_format_1_0_archive(tmp_path: Path) -> None:
    encoded = (FIXTURES / "format-1.0-minimal.b64").read_text(
        encoding="ascii"
    ).strip()
    archive = tmp_path / "golden-1.0.lpk"
    archive.write_bytes(base64.b64decode(encoded, validate=True))
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == (
        "cf8ce945907c089b490496f8d15eb371e82f20e09a4c77eedbf2e29667c6ec21"
    )
    assert probe_compatibility(archive).migration_supported

    migrated = tmp_path / "golden-1.1.lpk"
    migrate_archive(archive, migrated)
    restored = tmp_path / "golden-restored"
    unpack(migrated, output=restored)
    assert (restored / "hello.py").read_text(encoding="utf-8") == (
        'def greet(name: str) -> str:\n'
        '    return f"Hello, {name}!"\n'
    )


def test_migrate_legacy_archive_and_preserve_content(tmp_path: Path) -> None:
    source = tmp_path / "input"
    source.mkdir()
    (source / "hello.txt").write_text("hello from 0.1\n" * 200, encoding="utf-8")
    (source / "empty.bin").write_bytes(b"")
    current = tmp_path / "current.lpk"
    legacy = tmp_path / "legacy.lpk"
    migrated = tmp_path / "migrated.lpk"
    pack([source], current, goal="prefer-store")
    make_legacy_archive(
        current,
        legacy,
        lambda manifest: manifest.__setitem__(
            "legacy_note", {"kept": "when practical"}
        ),
    )

    result = migrate_archive(legacy, migrated)

    assert result.source_format == "1.0"
    assert result.target_format == "1.1"
    assert result.file_count == 2
    assert verify_archive(migrated, full=True).valid
    with migrated.open("rb") as stream:
        manifest, _, _ = _read_manifest(stream)
    assert manifest["format"] == {"major": 1, "minor": 1}
    assert manifest["manifest_schema"] == {"major": 2, "minor": 0}
    assert manifest["goal"] == "prefer-store"
    assert manifest["legacy_note"] == {"kept": "when practical"}
    assert all("preferred_codec" in item["decision"] for item in manifest["files"])
    assert all(
        len(item["chunk_decisions"]) == len(item["chunks"])
        for item in manifest["files"]
    )
    restored = tmp_path / "restored"
    unpack(migrated, output=restored)
    assert (restored / "input" / "hello.txt").read_bytes() == (
        source / "hello.txt"
    ).read_bytes()
    assert (restored / "input" / "empty.bin").read_bytes() == b""


def test_read_only_compatibility_probe(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("compatibility", encoding="utf-8")
    current = tmp_path / "current.lpk"
    legacy = tmp_path / "legacy.lpk"
    pack([source], current)
    make_legacy_archive(current, legacy)

    current_result = probe_compatibility(current)
    assert current_result.current is True
    assert current_result.status == "current"
    assert current_result.migration_supported is False
    legacy_result = probe_compatibility(legacy)
    assert legacy_result.current is False
    assert legacy_result.status == "migration-available"
    assert legacy_result.migration_supported is True
    assert legacy_result.target_format == "1.1"


def test_migrate_source_dictionary_archive(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for index in range(10):
        (source / f"module_{index}.py").write_text(
            f"def value_{index}():\n"
            f"    return {' + '.join(str(number) for number in range(200))}\n",
            encoding="utf-8",
        )
    current = tmp_path / "source-current.lpk"
    legacy = tmp_path / "source-legacy.lpk"
    migrated = tmp_path / "source-migrated.lpk"
    pack([source], current, profile="source", codec="zstd")
    make_legacy_archive(current, legacy)

    migrate_archive(legacy, migrated)

    with migrated.open("rb") as stream:
        manifest, _, _ = _read_manifest(stream)
    assert manifest["dictionaries"]
    assert {
        record["dictionary_id"]
        for record in manifest["source_dictionaries"].values()
    } == set(manifest["dictionaries"])
    assert verify_archive(migrated, full=True).valid


def test_migration_rejects_corruption_and_unsafe_manifest(tmp_path: Path) -> None:
    source = tmp_path / "file.txt"
    source.write_text("payload", encoding="utf-8")
    current = tmp_path / "current.lpk"
    pack([source], current)

    corrupt = make_legacy_archive(current, tmp_path / "corrupt.lpk")
    corrupt_payload(corrupt)
    with pytest.raises(FormatError, match="body hash mismatch"):
        probe_compatibility(corrupt)
    with pytest.raises(FormatError, match="body hash mismatch"):
        migrate_archive(corrupt, tmp_path / "corrupt-output.lpk")

    authenticated_corrupt = make_legacy_archive(
        current, tmp_path / "authenticated-corrupt.lpk"
    )
    corrupt_payload(authenticated_corrupt, reauthenticate=True)
    authenticated_output = tmp_path / "authenticated-output.lpk"
    with pytest.raises(FormatError, match="failed full verification"):
        migrate_archive(authenticated_corrupt, authenticated_output)
    assert not authenticated_output.exists()

    hostile = make_legacy_archive(
        current,
        tmp_path / "hostile.lpk",
        lambda manifest: manifest["files"][0].__setitem__("path", "../escape"),
    )
    with pytest.raises(FormatError):
        migrate_archive(hostile, tmp_path / "hostile-output.lpk")


def test_migration_output_rules_and_current_archive_rejection(
    tmp_path: Path,
) -> None:
    source = tmp_path / "file.txt"
    source.write_text("payload", encoding="utf-8")
    current = tmp_path / "current.lpk"
    legacy = tmp_path / "legacy.lpk"
    output = tmp_path / "output.lpk"
    pack([source], current)
    make_legacy_archive(current, legacy)

    with pytest.raises(ValueError, match="must differ"):
        migrate_archive(legacy, legacy)
    with pytest.raises(FormatError, match="already"):
        migrate_archive(current, output)
    output.write_bytes(b"occupied")
    with pytest.raises(FileExistsError):
        migrate_archive(legacy, output)
    result = migrate_archive(legacy, output, overwrite=True)
    assert result.archive == output
    assert verify_archive(output, full=True).valid


def test_migrate_cli_json(tmp_path: Path, capsys) -> None:
    source = tmp_path / "file.txt"
    source.write_text("payload", encoding="utf-8")
    current = tmp_path / "current.lpk"
    legacy = tmp_path / "legacy.lpk"
    migrated = tmp_path / "migrated.lpk"
    pack([source], current)
    make_legacy_archive(current, legacy)

    assert (
        main(
            [
                "migrate",
                str(legacy),
                "-o",
                str(migrated),
                "--json",
            ]
        )
        == 0
    )
    value = json.loads(capsys.readouterr().out)
    assert value["source_format"] == "1.0"
    assert value["target_format"] == "1.1"
    assert verify_archive(migrated, full=True).valid

    assert main(["compatibility", str(migrated), "--json"]) == 0
    compatibility = json.loads(capsys.readouterr().out)
    assert compatibility["current"] is True
    assert compatibility["status"] == "current"
