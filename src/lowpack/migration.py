"""Authenticated, atomic migration of earlier LowPack archives."""

from __future__ import annotations

import base64
import copy
import os
import tempfile
from pathlib import Path
from typing import Any, BinaryIO

from . import __version__
from .archive import (
    MANIFEST_SCHEMA_MAJOR,
    MANIFEST_SCHEMA_MINOR,
    _hash_body,
    _read_manifest,
    _validate_manifest,
    verify_archive,
)
from .format import (
    FOOTER,
    FOOTER_MAGIC,
    HEADER,
    MAGIC,
    VERSION_MAJOR,
    VERSION_MINOR,
    FormatError,
    read_header,
)
from .hashing import sha256, sha256_hex
from .manifest import encode_manifest
from .models import CompatibilityResult, MigrationResult

LEGACY_FORMAT = (1, 0)
GOAL_MIGRATIONS = {
    "balanced": "balanced",
    "smallest": "smallest",
    "fastest": "prefer-store",
    "fastest-decode": "prefer-zstd-low",
    "low-memory": "avoid-zlib",
}


def _copy_exact(source: BinaryIO, destination: BinaryIO, length: int) -> None:
    remaining = length
    while remaining:
        block = source.read(min(1024 * 1024, remaining))
        if not block:
            raise FormatError("archive payload was truncated during migration")
        destination.write(block)
        remaining -= len(block)


def _framing_versions(stream: BinaryIO) -> tuple[tuple[int, int], tuple[int, int]]:
    stream.seek(0)
    header_version = read_header(stream)[:2]
    stream.seek(-FOOTER.size, os.SEEK_END)
    raw_footer = stream.read(FOOTER.size)
    if len(raw_footer) != FOOTER.size:
        raise FormatError("truncated LowPack footer")
    footer_fields = FOOTER.unpack(raw_footer)
    footer_version = footer_fields[1:3]
    stream.seek(0)
    return header_version, footer_version


def _require_legacy_framing(stream: BinaryIO) -> None:
    header_version, footer_version = _framing_versions(stream)
    current_version = (VERSION_MAJOR, VERSION_MINOR)
    if header_version == current_version and footer_version == current_version:
        raise FormatError("archive is already in the current 1.1 format")
    if header_version != LEGACY_FORMAT or footer_version != LEGACY_FORMAT:
        raise FormatError(
            "migration requires matching format 1.0 header and footer"
        )


def _normalize_legacy_manifest(
    legacy: dict[str, Any], *, manifest_offset: int
) -> dict[str, Any]:
    format_record = legacy.get("format")
    if not isinstance(format_record, dict):
        raise FormatError("legacy manifest has no format record")
    source_version = (format_record.get("major"), format_record.get("minor"))
    if source_version == (VERSION_MAJOR, VERSION_MINOR):
        raise FormatError("archive is already in the current 1.1 format")
    if source_version != LEGACY_FORMAT:
        raise FormatError(
            f"migration supports format 1.0, not "
            f"{format_record.get('major')}.{format_record.get('minor')}"
        )
    if "manifest_schema" in legacy:
        raise FormatError("format 1.0 archive has an unexpected manifest schema")

    manifest = copy.deepcopy(legacy)
    chunks = manifest.get("chunks")
    files = manifest.get("files")
    legacy_sources = manifest.get("source_dictionaries")
    if (
        not isinstance(chunks, dict)
        or not isinstance(files, list)
        or not isinstance(legacy_sources, dict)
    ):
        raise FormatError("legacy manifest is missing required collections")

    dictionaries: dict[str, dict[str, Any]] = {}
    normalized_chunks: dict[str, dict[str, Any]] = {}
    for chunk_id, value in chunks.items():
        if not isinstance(chunk_id, str) or not isinstance(value, dict):
            raise FormatError("invalid legacy chunk index record")
        record = copy.deepcopy(value)
        if "dictionary_id" in record:
            raise FormatError("format 1.0 chunk has an unexpected dictionary ID")
        encoded_dictionary = record.pop("dictionary", None)
        if encoded_dictionary is not None:
            if record.get("codec") != "zstd" or not isinstance(encoded_dictionary, str):
                raise FormatError("invalid legacy compression dictionary")
            try:
                dictionary = base64.b64decode(encoded_dictionary, validate=True)
            except (TypeError, ValueError) as exc:
                raise FormatError("invalid legacy compression dictionary encoding") from exc
            if not dictionary or len(dictionary) > 64 * 1024:
                raise FormatError("invalid legacy compression dictionary size")
            dictionary_id = sha256_hex(dictionary)
            record["dictionary_id"] = dictionary_id
            dictionaries[dictionary_id] = {
                "data": encoded_dictionary,
                "hash": dictionary_id,
                "size": len(dictionary),
            }
        normalized_chunks[chunk_id] = record

    seen_chunks: set[str] = set()
    normalized_files: list[dict[str, Any]] = []
    for value in files:
        if not isinstance(value, dict):
            raise FormatError("invalid legacy file record")
        item = copy.deepcopy(value)
        refs = item.get("chunks")
        decision = item.get("decision")
        if not isinstance(refs, list) or not isinstance(decision, dict):
            raise FormatError("invalid legacy file decision or chunk references")
        if "preferred_codec" in decision or "final_codec" not in decision:
            raise FormatError("invalid format 1.0 codec decision")
        decision["preferred_codec"] = decision.pop("final_codec")
        item["decision"] = decision
        chunk_decisions: list[dict[str, Any]] = []
        for ref in refs:
            if not isinstance(ref, str) or ref not in normalized_chunks:
                raise FormatError("legacy file references an unknown chunk")
            chunk = normalized_chunks[ref]
            reused = ref in seen_chunks
            chunk_decisions.append(
                {
                    "actual_codec": chunk.get("codec"),
                    "actual_level": chunk.get("level"),
                    "chunk": ref,
                    "dictionary_id": chunk.get("dictionary_id"),
                    "reason": (
                        "reused an existing content-addressed representation"
                        if reused
                        else "preserved the representation stored by LowPack 0.1"
                    ),
                    "reused": reused,
                }
            )
            seen_chunks.add(ref)
        item["chunk_decisions"] = chunk_decisions
        if "mode" in item:
            mode = item["mode"]
            if isinstance(mode, bool) or not isinstance(mode, int) or mode < 0:
                raise FormatError("invalid legacy permission mode")
            item["mode"] = mode & 0o777
        normalized_files.append(item)

    profile = manifest.get("profile")
    source_dictionaries: dict[str, dict[str, str]] = {}
    used_dictionary_ids = {
        record["dictionary_id"]
        for record in normalized_chunks.values()
        if "dictionary_id" in record
    }
    if profile == "source":
        for group, value in legacy_sources.items():
            if not isinstance(group, str) or not isinstance(value, dict):
                raise FormatError("invalid legacy source dictionary record")
            size = value.get("bytes")
            source_dictionary_id = value.get("hash")
            if (
                isinstance(size, bool)
                or not isinstance(size, int)
                or size <= 0
                or not isinstance(source_dictionary_id, str)
            ):
                raise FormatError("invalid legacy source dictionary metadata")
            if source_dictionary_id in used_dictionary_ids:
                catalog_record = dictionaries.get(source_dictionary_id)
                if catalog_record is None or catalog_record["size"] != size:
                    raise FormatError("legacy source dictionary hash or size mismatch")
                source_dictionaries[group] = {
                    "dictionary_id": source_dictionary_id
                }
        if {
            record["dictionary_id"] for record in source_dictionaries.values()
        } != used_dictionary_ids:
            raise FormatError("legacy source dictionaries do not cover stored chunks")
    elif legacy_sources:
        raise FormatError("non-source legacy archive contains source dictionaries")

    goal = manifest.get("goal")
    if not isinstance(goal, str) or goal not in GOAL_MIGRATIONS:
        raise FormatError(f"unsupported legacy selection goal: {goal}")
    manifest["chunks"] = normalized_chunks
    manifest["dictionaries"] = dictionaries
    manifest["files"] = normalized_files
    manifest["format"] = {"major": VERSION_MAJOR, "minor": VERSION_MINOR}
    manifest["goal"] = GOAL_MIGRATIONS[goal]
    manifest["lowpack_version"] = __version__
    manifest["manifest_schema"] = {
        "major": MANIFEST_SCHEMA_MAJOR,
        "minor": MANIFEST_SCHEMA_MINOR,
    }
    manifest["source_dictionaries"] = source_dictionaries
    _validate_manifest(manifest, manifest_offset=manifest_offset)
    return manifest


def probe_compatibility(
    archive: os.PathLike[str] | str,
) -> CompatibilityResult:
    """Authenticate and classify an archive without decompressing its payload."""

    path = Path(archive)
    with path.open("rb") as stream:
        header_version, footer_version = _framing_versions(stream)
        if header_version != footer_version:
            raise FormatError("archive header and footer versions disagree")
        manifest, _data, footer = _read_manifest(stream)
        actual_body_hash = _hash_body(
            stream, footer.manifest_offset + footer.manifest_size
        )
        if actual_body_hash != footer.body_hash:
            raise FormatError("archive body hash mismatch")
        format_record = manifest.get("format")
        if not isinstance(format_record, dict):
            raise FormatError("manifest has no format record")
        manifest_version = (
            format_record.get("major"),
            format_record.get("minor"),
        )
        if manifest_version != header_version:
            raise FormatError("framing and manifest format versions disagree")
        if header_version == LEGACY_FORMAT:
            _normalize_legacy_manifest(
                manifest, manifest_offset=footer.manifest_offset
            )
            return CompatibilityResult(
                archive=path,
                format_version="1.0",
                status="migration-available",
                current=False,
                migration_supported=True,
                target_format=f"{VERSION_MAJOR}.{VERSION_MINOR}",
            )
        current_version = (VERSION_MAJOR, VERSION_MINOR)
        if header_version == current_version:
            _validate_manifest(
                manifest, manifest_offset=footer.manifest_offset
            )
            return CompatibilityResult(
                archive=path,
                format_version=f"{VERSION_MAJOR}.{VERSION_MINOR}",
                status="current",
                current=True,
                migration_supported=False,
            )
        raise FormatError(
            f"unsupported LowPack format {header_version[0]}.{header_version[1]}"
        )


def migrate_archive(
    source: os.PathLike[str] | str,
    archive: os.PathLike[str] | str,
    *,
    overwrite: bool = False,
) -> MigrationResult:
    """Migrate an authenticated format 1.0 archive to current format 1.1."""

    source_path = Path(source)
    target = Path(archive)
    source_identity = os.path.normcase(str(source_path.resolve()))
    target_identity = os.path.normcase(str(target.resolve()))
    if source_identity == target_identity:
        raise ValueError("migration output must differ from the source archive")
    if target.exists() and not overwrite:
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    with source_path.open("rb") as source_stream:
        _require_legacy_framing(source_stream)
        legacy, _data, footer = _read_manifest(source_stream)
        actual_body_hash = _hash_body(
            source_stream, footer.manifest_offset + footer.manifest_size
        )
        if actual_body_hash != footer.body_hash:
            raise FormatError("legacy archive body hash mismatch")
        manifest = _normalize_legacy_manifest(
            legacy, manifest_offset=footer.manifest_offset
        )

    encoded = encode_manifest(manifest)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        with source_path.open("rb") as source_stream, temporary.open("w+b") as output:
            output.write(HEADER.pack(MAGIC, VERSION_MAJOR, VERSION_MINOR, 0))
            source_stream.seek(HEADER.size)
            _copy_exact(
                source_stream,
                output,
                footer.manifest_offset - HEADER.size,
            )
            manifest_offset = output.tell()
            if manifest_offset != footer.manifest_offset:
                raise FormatError("migration changed the chunk payload layout")
            output.write(encoded)
            body_length = output.tell()
            body_hash = _hash_body(output, body_length)
            output.seek(body_length)
            output.write(
                FOOTER.pack(
                    FOOTER_MAGIC,
                    VERSION_MAJOR,
                    VERSION_MINOR,
                    manifest_offset,
                    len(encoded),
                    sha256(encoded),
                    body_hash,
                )
            )
            output.flush()
            os.fsync(output.fileno())
        verification = verify_archive(temporary, full=True)
        if not verification.valid:
            details = "; ".join(verification.errors) or "unknown verification error"
            raise FormatError(f"migrated archive failed full verification: {details}")
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    return MigrationResult(
        source=source_path,
        archive=target,
        source_format="1.0",
        target_format=f"{VERSION_MAJOR}.{VERSION_MINOR}",
        file_count=len(manifest["files"]),
        chunk_count=len(manifest["chunks"]),
    )
