"""Archive creation, inspection, verification, and extraction."""

from __future__ import annotations

import base64
import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, cast

import zstandard

from . import __version__
from .codecs import CODECS
from .format import (
    CHUNK_HEADER,
    CHUNK_MAGIC,
    CODEC_IDS,
    CODEC_NAMES,
    FOOTER,
    FOOTER_MAGIC,
    HEADER,
    VERSION_MAJOR,
    VERSION_MINOR,
    FormatError,
    read_footer,
    read_header,
    write_header,
)
from .hashing import sha256, sha256_hex
from .manifest import decode_manifest, encode_manifest
from .models import ArchiveInfo, PackResult, VerificationResult
from .paths import collision_key, normalize_archive_path, safe_destination
from .profiles.base import EncodedData, TransformOptions
from .profiles.general import is_already_compressed
from .profiles.source import DEFAULT_EXCLUDES, category
from .profiles.telemetry import TRANSFORMER
from .selection import MAX_SAMPLE, Selection, select_codec

DEFAULT_CHUNK_SIZE = 1024 * 1024
MAX_MANIFEST_SIZE = 64 * 1024 * 1024
MAX_FILES = 100_000
MAX_CHUNKS = 1_000_000
MAX_EXTRACT_SIZE = 8 * 1024 * 1024 * 1024
MAX_CHUNK_SIZE = 64 * 1024 * 1024
MAX_TRANSFORM_SIZE = 64 * 1024 * 1024
MAX_DICTIONARY_SAMPLE = 1024 * 1024
MAX_DICTIONARY_FILE_SAMPLE = 64 * 1024
DICTIONARY_SIZE = 8192
MANIFEST_SCHEMA_MAJOR = 2
MANIFEST_SCHEMA_MINOR = 0
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _iter_stream_chunks(stream: BinaryIO, chunk_size: int) -> Iterator[bytes]:
    while True:
        data = stream.read(chunk_size)
        if not data:
            break
        yield data


def _file_identity(path: Path) -> tuple[int, int]:
    value = path.stat()
    return value.st_dev, value.st_ino


def _snapshot_signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _register_archive_path(registry: dict[str, tuple[str, str]], path: str, kind: str) -> None:
    key = collision_key(path)
    existing = registry.get(key)
    if existing is not None:
        raise ValueError(
            f"duplicate or case-colliding archive path: {path} "
            f"conflicts with {existing[0]}"
        )
    registry[key] = (path, kind)


def _reserved_identity(
    path: Path,
    reserved_paths: set[Path],
    reserved_identities: set[tuple[int, int]],
) -> bool:
    resolved = path.resolve(strict=False)
    if resolved in reserved_paths:
        return True
    try:
        return _file_identity(path) in reserved_identities
    except OSError:
        return False


def _patterns_match(path: str, patterns: Sequence[str]) -> bool:
    name_parts = PurePosixPath(path).parts
    return any(fnmatch.fnmatch(path, pattern) or pattern in name_parts for pattern in patterns)


def _collect_inputs(
    inputs: Sequence[os.PathLike[str] | str],
    *,
    profile: str,
    excludes: Sequence[str],
    includes: Sequence[str],
    include_all: bool,
    follow_symlinks: bool,
    reserved: Sequence[Path] = (),
) -> tuple[list[tuple[Path, str]], list[str], list[str]]:
    files: list[tuple[Path, str]] = []
    directories: list[str] = []
    excluded: list[str] = []
    defaults = () if include_all or profile != "source" else DEFAULT_EXCLUDES
    patterns = tuple(defaults) + tuple(excludes)
    registry: dict[str, tuple[str, str]] = {}
    file_identities: set[tuple[int, int]] = set()
    directory_identities: set[tuple[int, int]] = set()
    reserved_paths = {path.resolve(strict=False) for path in reserved}
    reserved_identities: set[tuple[int, int]] = set()
    for path in reserved:
        try:
            reserved_identities.add(_file_identity(path))
        except OSError:
            pass
    for raw_input in inputs:
        source = Path(raw_input)
        if not source.exists():
            raise FileNotFoundError(source)
        if source.is_symlink() and not follow_symlinks:
            excluded.append(str(source))
            continue
        if source.is_file():
            if _reserved_identity(source, reserved_paths, reserved_identities):
                raise ValueError(f"output archive cannot also be an input: {source}")
            archive_path = normalize_archive_path(source.name)
            if not includes or _patterns_match(archive_path, includes):
                identity = _file_identity(source)
                if identity in file_identities:
                    raise ValueError(f"duplicate input file identity: {source}")
                _register_archive_path(registry, archive_path, "file")
                file_identities.add(identity)
                files.append((source, archive_path))
            continue
        root_name = normalize_archive_path(source.name)
        for current, dir_names, file_names in os.walk(source, followlinks=follow_symlinks):
            current_path = Path(current)
            directory_identity = _file_identity(current_path)
            if directory_identity in directory_identities:
                raise ValueError(
                    f"directory traversal cycle or duplicate input identity: {current_path}"
                )
            directory_identities.add(directory_identity)
            relative = current_path.relative_to(source)
            archive_dir = (
                root_name if str(relative) == "." else f"{root_name}/{relative.as_posix()}"
            )
            archive_dir = normalize_archive_path(archive_dir)
            _register_archive_path(registry, archive_dir, "directory")
            directories.append(archive_dir)
            kept_dirs: list[str] = []
            for name in sorted(dir_names):
                candidate = normalize_archive_path(f"{archive_dir}/{name}")
                disk_candidate = current_path / name
                if (disk_candidate.is_symlink() and not follow_symlinks) or _patterns_match(
                    candidate, patterns
                ):
                    excluded.append(candidate)
                else:
                    kept_dirs.append(name)
            dir_names[:] = kept_dirs
            for name in sorted(file_names):
                disk_path = current_path / name
                archive_path = normalize_archive_path(f"{archive_dir}/{name}")
                if disk_path.is_symlink() and not follow_symlinks:
                    excluded.append(archive_path)
                elif _patterns_match(archive_path, patterns):
                    excluded.append(archive_path)
                elif includes and not _patterns_match(archive_path, includes):
                    excluded.append(archive_path)
                elif _reserved_identity(disk_path, reserved_paths, reserved_identities):
                    excluded.append(archive_path)
                else:
                    identity = _file_identity(disk_path)
                    if identity in file_identities:
                        raise ValueError(f"duplicate input file identity: {disk_path}")
                    _register_archive_path(registry, archive_path, "file")
                    file_identities.add(identity)
                    files.append((disk_path, archive_path))
    return sorted(files, key=lambda item: item[1]), sorted(set(directories)), sorted(set(excluded))


def _hash_body(stream: BinaryIO, length: int) -> bytes:
    stream.flush()
    stream.seek(0)
    digest = hashlib.sha256()
    remaining = length
    while remaining:
        block = stream.read(min(1024 * 1024, remaining))
        if not block:
            raise FormatError("archive body was truncated while hashing")
        digest.update(block)
        remaining -= len(block)
    return digest.digest()


def _train_source_dictionaries(
    files: list[tuple[Path, str]], profile: str
) -> dict[str, bytes]:
    if profile != "source":
        return {}
    groups: dict[str, list[bytes]] = {}
    totals: dict[str, int] = {}
    for disk_path, archive_path in files:
        group = category(archive_path)
        if group == "other" or totals.get(group, 0) >= MAX_DICTIONARY_SAMPLE:
            continue
        with disk_path.open("rb") as sample_stream:
            sample = sample_stream.read(MAX_DICTIONARY_FILE_SAMPLE)
        if not sample or b"\x00" in sample:
            continue
        sample = sample[: MAX_DICTIONARY_SAMPLE - totals.get(group, 0)]
        groups.setdefault(group, []).append(sample)
        totals[group] = totals.get(group, 0) + len(sample)
    dictionaries: dict[str, bytes] = {}
    for group, samples in sorted(groups.items()):
        total = sum(len(sample) for sample in samples)
        if len(samples) < 8 or total < 2048:
            continue
        size = min(DICTIONARY_SIZE, max(256, total // 8))
        try:
            training_samples = cast(
                "list[bytes | bytearray | memoryview[int]]",
                samples,
            )
            dictionaries[group] = zstandard.train_dictionary(
                size, training_samples
            ).as_bytes()
        except zstandard.ZstdError:
            continue
    return dictionaries


def pack(
    inputs: Sequence[os.PathLike[str] | str],
    archive: os.PathLike[str] | str,
    *,
    profile: str = "general",
    goal: str = "balanced",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    codec: str | None = None,
    level: int | None = None,
    exclude: Sequence[str] = (),
    include: Sequence[str] = (),
    include_all: bool = False,
    follow_symlinks: bool = False,
    store_permissions: bool = False,
    overwrite: bool = False,
    telemetry_mode: str = "exact",
    time_field: str | None = None,
) -> PackResult:
    if profile not in {"general", "source", "telemetry"}:
        raise ValueError(f"unknown profile: {profile}")
    if goal not in {
        "balanced",
        "smallest",
        "prefer-store",
        "prefer-zstd-low",
        "avoid-zlib",
    }:
        raise ValueError(f"unknown goal: {goal}")
    if codec is not None and codec not in CODECS:
        raise ValueError(f"unknown codec: {codec}")
    if chunk_size < 4096 or chunk_size > MAX_CHUNK_SIZE:
        raise ValueError("chunk size must be between 4 KiB and 64 MiB")
    target = Path(archive)
    if target.exists() and not overwrite:
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(temp_fd)
    temp_path = Path(temp_name)
    chunk_records: dict[str, dict[str, Any]] = {}
    file_records: list[dict[str, Any]] = []
    total_original = 0
    selection_ns = 0
    try:
        files, directories, excluded = _collect_inputs(
            inputs,
            profile=profile,
            excludes=exclude,
            includes=include,
            include_all=include_all,
            follow_symlinks=follow_symlinks,
            reserved=(target, temp_path),
        )
        source_dictionaries = _train_source_dictionaries(files, profile)
        dictionary_ids = {
            group: sha256_hex(dictionary)
            for group, dictionary in source_dictionaries.items()
        }
        with temp_path.open("w+b") as stream:
            write_header(stream)
            for disk_path, archive_path in files:
                with disk_path.open("rb") as source_stream:
                    before = os.fstat(source_stream.fileno())
                    raw_size = before.st_size
                    sample = source_stream.read(MAX_SAMPLE)
                    source_stream.seek(0)
                    transformed: bytes | None = None
                    reconstructed: bytes | None = None
                    transform_metadata: dict[str, Any] = {"id": "none", "mode": "exact"}
                    if profile == "telemetry" and disk_path.suffix.lower() == ".csv":
                        if raw_size > MAX_TRANSFORM_SIZE:
                            raise ValueError(
                                f"telemetry input exceeds {MAX_TRANSFORM_SIZE} byte "
                                f"in-memory transform limit: {disk_path}"
                            )
                        raw = source_stream.read(raw_size + 1)
                        if len(raw) != raw_size:
                            raise OSError(f"source changed while packing: {disk_path}")
                        encoded = TRANSFORMER.encode(
                            raw,
                            TransformOptions(mode=telemetry_mode, time_field=time_field),
                        )
                        transformed = encoded.data
                        transform_metadata = encoded.metadata
                        reconstructed = TRANSFORMER.decode(
                            encoded, max_output_size=MAX_TRANSFORM_SIZE
                        )
                        sample = transformed[:MAX_SAMPLE]
                        chunks: Iterator[bytes] = (
                            transformed[index : index + chunk_size]
                            for index in range(0, len(transformed), chunk_size)
                        )
                    else:
                        chunks = _iter_stream_chunks(source_stream, chunk_size)
                    selection: Selection = select_codec(
                        sample,
                        goal=goal,
                        requested=codec,
                        level=level,
                        already_compressed=is_already_compressed(sample),
                    )
                    selection_ns += selection.elapsed_ns
                    dictionary = source_dictionaries.get(category(archive_path))
                    dictionary_id = dictionary_ids.get(category(archive_path))
                    refs: list[str] = []
                    chunk_decisions: list[dict[str, Any]] = []
                    file_hash = hashlib.sha256()
                    encoded_hash = hashlib.sha256()
                    encoded_size = 0
                    for raw_chunk in chunks:
                        encoded_hash.update(raw_chunk)
                        encoded_size += len(raw_chunk)
                        if transformed is None:
                            file_hash.update(raw_chunk)
                        chunk_id = sha256_hex(raw_chunk)
                        refs.append(chunk_id)
                        reused = chunk_id in chunk_records
                        if not reused:
                            if selection.codec == "zstd" and dictionary is not None:
                                packed = zstandard.ZstdCompressor(
                                    level=3 if selection.level is None else selection.level,
                                    dict_data=zstandard.ZstdCompressionDict(dictionary),
                                ).compress(raw_chunk)
                            else:
                                packed = CODECS[selection.codec].compress(
                                    raw_chunk, level=selection.level
                                )
                            offset = stream.tell()
                            stream.write(
                                CHUNK_HEADER.pack(
                                    CHUNK_MAGIC,
                                    CODEC_IDS[selection.codec],
                                    len(raw_chunk),
                                    len(packed),
                                    bytes.fromhex(chunk_id),
                                )
                            )
                            stream.write(packed)
                            chunk_record: dict[str, Any] = {
                                "codec": selection.codec,
                                "level": selection.level,
                                "offset": offset,
                                "packed_size": len(packed),
                                "raw_size": len(raw_chunk),
                            }
                            if (
                                selection.codec == "zstd"
                                and dictionary is not None
                                and dictionary_id is not None
                            ):
                                chunk_record["dictionary_id"] = dictionary_id
                            chunk_records[chunk_id] = chunk_record
                        actual = chunk_records[chunk_id]
                        chunk_decisions.append(
                            {
                                "actual_codec": actual["codec"],
                                "actual_level": actual["level"],
                                "chunk": chunk_id,
                                "dictionary_id": actual.get("dictionary_id"),
                                "reason": (
                                    "reused an existing content-addressed representation"
                                    if reused
                                    else "stored using this file's preferred policy"
                                ),
                                "reused": reused,
                            }
                        )
                    after = os.fstat(source_stream.fileno())
                    if _snapshot_signature(before) != _snapshot_signature(after):
                        raise OSError(f"source changed while packing: {disk_path}")
                    if transformed is None:
                        if encoded_size != raw_size:
                            raise OSError(f"source changed while packing: {disk_path}")
                        output_size = encoded_size
                    else:
                        if reconstructed is None:
                            raise AssertionError("transformed source was not reconstructed")
                        file_hash.update(reconstructed)
                        output_size = len(reconstructed)
                total_original += output_size
                canonical_candidates = [
                    {
                        "codec": candidate["codec"],
                        "level": candidate["level"],
                        "packed_bytes": candidate["packed_bytes"],
                        "sample_bytes": candidate["sample_bytes"],
                        "score": candidate["score"],
                    }
                    for candidate in selection.candidates
                ]
                decision = {
                    "candidates": canonical_candidates,
                    "preferred_codec": selection.codec,
                    "level": selection.level,
                    "reason": selection.reason,
                }
                record: dict[str, Any] = {
                    "chunk_decisions": chunk_decisions,
                    "chunks": refs,
                    "encoded_hash": encoded_hash.hexdigest(),
                    "encoded_size": encoded_size,
                    "hash": file_hash.hexdigest(),
                    "path": archive_path,
                    "size": output_size,
                    "source_size": raw_size,
                    "transform": transform_metadata,
                    "decision": decision,
                }
                if profile == "source":
                    record["source_category"] = category(archive_path)
                if store_permissions:
                    record["mode"] = stat.S_IMODE(before.st_mode) & 0o777
                file_records.append(record)
            used_dictionary_ids = {
                record["dictionary_id"]
                for record in chunk_records.values()
                if "dictionary_id" in record
            }
            manifest: dict[str, Any] = {
                "chunk_size": chunk_size,
                "chunks": chunk_records,
                "codec_versions": {
                    "store": "1",
                    "zlib": __import__("zlib").ZLIB_VERSION,
                    "zstd": zstandard.__version__,
                },
                "directories": directories,
                "dictionaries": {
                    dictionary_ids[group]: {
                        "data": base64.b64encode(dictionary).decode("ascii"),
                        "hash": dictionary_ids[group],
                        "size": len(dictionary),
                    }
                    for group, dictionary in sorted(source_dictionaries.items())
                    if dictionary_ids[group] in used_dictionary_ids
                },
                "excluded": excluded,
                "files": file_records,
                "format": {"major": VERSION_MAJOR, "minor": VERSION_MINOR},
                "goal": goal,
                "lowpack_version": __version__,
                "manifest_schema": {
                    "major": MANIFEST_SCHEMA_MAJOR,
                    "minor": MANIFEST_SCHEMA_MINOR,
                },
                "profile": profile,
                "source_dictionaries": {
                    group: {
                        "dictionary_id": dictionary_ids[group],
                    }
                    for group, dictionary in sorted(source_dictionaries.items())
                    if dictionary_ids[group] in used_dictionary_ids
                },
                "store_permissions": store_permissions,
            }
            manifest_data = encode_manifest(manifest)
            manifest_offset = stream.tell()
            stream.write(manifest_data)
            body_length = stream.tell()
            body_hash = _hash_body(stream, body_length)
            stream.seek(body_length)
            stream.write(
                FOOTER.pack(
                    FOOTER_MAGIC,
                    VERSION_MAJOR,
                    VERSION_MINOR,
                    manifest_offset,
                    len(manifest_data),
                    sha256(manifest_data),
                    body_hash,
                )
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, target)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return PackResult(
        target,
        len(file_records),
        len(directories),
        total_original,
        target.stat().st_size,
        sum(len(item["chunks"]) for item in file_records),
        len(chunk_records),
        selection_ns,
        tuple(excluded),
    )


def _read_manifest(stream: BinaryIO) -> tuple[dict[str, Any], bytes, Any]:
    read_header(stream)
    footer = read_footer(stream)
    if footer.manifest_size > MAX_MANIFEST_SIZE:
        raise FormatError("manifest exceeds safety limit")
    stream.seek(footer.manifest_offset)
    data = stream.read(footer.manifest_size)
    if len(data) != footer.manifest_size or sha256(data) != footer.manifest_hash:
        raise FormatError("manifest hash mismatch")
    manifest = decode_manifest(data)
    return manifest, data, footer


def _read_chunk(
    stream: BinaryIO,
    chunk_id: str,
    record: dict[str, Any],
    dictionaries: dict[str, bytes],
) -> bytes:
    stream.seek(int(record["offset"]))
    header = stream.read(CHUNK_HEADER.size)
    if len(header) != CHUNK_HEADER.size:
        raise FormatError(f"truncated chunk {chunk_id}")
    magic, codec_id, raw_size, packed_size, raw_hash = CHUNK_HEADER.unpack(header)
    if magic != CHUNK_MAGIC or header[5:8] != b"\x00\x00\x00" or raw_hash.hex() != chunk_id:
        raise FormatError(f"invalid chunk header {chunk_id}")
    codec_name = CODEC_NAMES.get(codec_id)
    if codec_name is None or codec_name != record.get("codec"):
        raise FormatError(f"unsupported or inconsistent codec for chunk {chunk_id}")
    if raw_size != record.get("raw_size") or packed_size != record.get("packed_size"):
        raise FormatError(f"chunk sizes disagree with manifest for {chunk_id}")
    payload = stream.read(packed_size)
    if len(payload) != packed_size:
        raise FormatError(f"truncated chunk payload {chunk_id}")
    try:
        dictionary_id = record.get("dictionary_id")
        if codec_name == "zstd" and dictionary_id is not None:
            dictionary = dictionaries[dictionary_id]
            raw = zstandard.ZstdDecompressor(
                dict_data=zstandard.ZstdCompressionDict(dictionary)
            ).decompress(payload, max_output_size=raw_size)
        else:
            raw = cast(
                bytes,
                CODECS[codec_name].decompress(payload, expected_size=raw_size),
            )
    except Exception as exc:
        raise FormatError(f"cannot decompress chunk {chunk_id}") from exc
    if sha256_hex(raw) != chunk_id:
        raise FormatError(f"chunk hash mismatch {chunk_id}")
    return raw


def _validate_manifest(
    manifest: dict[str, Any],
    *,
    max_files: int = MAX_FILES,
    max_chunks: int = MAX_CHUNKS,
    max_extract_size: int = MAX_EXTRACT_SIZE,
    manifest_offset: int | None = None,
) -> None:
    def integer(value: Any, *, minimum: int = 0) -> bool:
        return not isinstance(value, bool) and isinstance(value, int) and value >= minimum

    def hash_string(value: Any) -> bool:
        return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None

    files = manifest.get("files")
    chunks = manifest.get("chunks")
    directories = manifest.get("directories")
    dictionaries = manifest.get("dictionaries")
    excluded_values = manifest.get("excluded")
    if (
        not isinstance(files, list)
        or not isinstance(chunks, dict)
        or not isinstance(directories, list)
        or not isinstance(dictionaries, dict)
    ):
        raise FormatError("manifest is missing required collections")
    if (
        len(files) + len(directories) > max_files
        or len(chunks) > max_chunks
        or len(dictionaries) > max_chunks
        or (
            isinstance(excluded_values, list)
            and len(excluded_values) > max_files
        )
    ):
        raise FormatError("archive exceeds object-count safety limit")
    format_record = manifest.get("format")
    schema_record = manifest.get("manifest_schema")
    chunk_size = manifest.get("chunk_size")
    if (
        not isinstance(format_record, dict)
        or format_record.get("major") != VERSION_MAJOR
        or format_record.get("minor") != VERSION_MINOR
        or not isinstance(schema_record, dict)
        or schema_record.get("major") != MANIFEST_SCHEMA_MAJOR
        or schema_record.get("minor") != MANIFEST_SCHEMA_MINOR
        or not integer(chunk_size)
    ):
        raise FormatError("unsupported or inconsistent manifest format settings")
    chunk_size_value = cast(int, chunk_size)
    if chunk_size_value < 4096 or chunk_size_value > MAX_CHUNK_SIZE:
        raise FormatError("unsupported or inconsistent manifest chunk size")
    if (
        manifest.get("profile") not in {"general", "source", "telemetry"}
        or manifest.get("goal")
        not in {
            "balanced",
            "smallest",
            "prefer-store",
            "prefer-zstd-low",
            "avoid-zlib",
        }
        or not isinstance(manifest.get("lowpack_version"), str)
        or not isinstance(manifest.get("store_permissions"), bool)
        or not isinstance(manifest.get("codec_versions"), dict)
        or any(
            not isinstance(name, str) or not isinstance(version, str)
            for name, version in manifest["codec_versions"].items()
        )
        or not isinstance(manifest.get("excluded"), list)
        or any(not isinstance(value, str) for value in manifest["excluded"])
        or not isinstance(manifest.get("source_dictionaries"), dict)
    ):
        raise FormatError("invalid manifest metadata")
    dictionary_data: dict[str, bytes] = {}
    for dictionary_id, record in dictionaries.items():
        if (
            not hash_string(dictionary_id)
            or not isinstance(record, dict)
            or record.get("hash") != dictionary_id
            or not integer(record.get("size"))
            or record["size"] == 0
            or record["size"] > 64 * 1024
            or not isinstance(record.get("data"), str)
        ):
            raise FormatError("invalid compression dictionary record")
        try:
            data = base64.b64decode(record["data"], validate=True)
        except (ValueError, TypeError) as exc:
            raise FormatError("invalid compression dictionary encoding") from exc
        if len(data) != record["size"] or sha256_hex(data) != dictionary_id:
            raise FormatError("compression dictionary hash or size mismatch")
        dictionary_data[dictionary_id] = data
    source_dictionary_ids: set[str] = set()
    for group, record in manifest["source_dictionaries"].items():
        if (
            not isinstance(group, str)
            or not isinstance(record, dict)
            or record.get("dictionary_id") not in dictionaries
        ):
            raise FormatError("invalid source dictionary reference")
        source_dictionary_ids.add(record["dictionary_id"])
    chunk_spans: list[tuple[int, int, str]] = []
    for chunk_id, record in chunks.items():
        if (
            not hash_string(chunk_id)
            or not isinstance(record, dict)
            or record.get("codec") not in CODECS
            or not integer(record.get("offset"))
            or not integer(record.get("raw_size"))
            or not integer(record.get("packed_size"))
            or record["offset"] < HEADER.size
            or record["raw_size"] == 0
            or record["raw_size"] > chunk_size_value
            or record["packed_size"] == 0
            or (
                record.get("level") is not None
                and (
                    isinstance(record.get("level"), bool)
                    or not isinstance(record.get("level"), int)
                )
            )
        ):
            raise FormatError("invalid chunk index record")
        dictionary_id = record.get("dictionary_id")
        if dictionary_id is not None and (
            record["codec"] != "zstd" or dictionary_id not in dictionary_data
        ):
            raise FormatError("dictionary reference is inconsistent with chunk codec")
        end = record["offset"] + CHUNK_HEADER.size + record["packed_size"]
        if manifest_offset is not None and end > manifest_offset:
            raise FormatError(f"chunk boundary outside payload area: {chunk_id}")
        chunk_spans.append((record["offset"], end, chunk_id))
    used_dictionary_ids = {
        record["dictionary_id"]
        for record in chunks.values()
        if "dictionary_id" in record
    }
    if used_dictionary_ids != set(dictionaries):
        raise FormatError("manifest contains unused or missing compression dictionaries")
    if (
        manifest["profile"] == "source"
        and source_dictionary_ids != used_dictionary_ids
    ) or (manifest["profile"] != "source" and source_dictionary_ids):
        raise FormatError("source dictionary table is inconsistent with archive profile")
    if manifest_offset is not None:
        cursor = HEADER.size
        for start, end, chunk_id in sorted(chunk_spans):
            if start != cursor:
                raise FormatError(f"chunk ordering or overlap is invalid near {chunk_id}")
            cursor = end
        if cursor != manifest_offset:
            raise FormatError("payload area and manifest boundary are inconsistent")
    paths: set[str] = set()
    collisions: set[str] = set()
    total = 0
    total_refs = 0
    referenced_chunks: set[str] = set()
    representations_seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise FormatError("invalid file record")
        if not isinstance(item.get("path"), str):
            raise FormatError("invalid file path type")
        path = normalize_archive_path(item["path"])
        key = collision_key(path)
        if path in paths or key in collisions:
            raise FormatError(f"duplicate or case-colliding destination: {path}")
        paths.add(path)
        collisions.add(key)
        size = item.get("size")
        source_size = item.get("source_size")
        encoded_size = item.get("encoded_size")
        if (
            not integer(size)
            or not integer(source_size)
            or not integer(encoded_size)
            or not hash_string(item.get("hash"))
            or not hash_string(item.get("encoded_hash"))
        ):
            raise FormatError(f"invalid declared file size: {path}")
        size_value = cast(int, size)
        source_size_value = cast(int, source_size)
        encoded_size_value = cast(int, encoded_size)
        total += size_value
        refs = item.get("chunks")
        if (
            not isinstance(refs, list)
            or any(not hash_string(ref) for ref in refs)
            or len(refs) > max_chunks
        ):
            raise FormatError(f"invalid chunk references: {path}")
        if any(ref not in chunks for ref in refs):
            raise FormatError(f"file references an unknown chunk: {path}")
        total_refs += len(refs)
        if total_refs > max_chunks:
            raise FormatError("archive exceeds aggregate chunk-reference safety limit")
        if sum(chunks[ref]["raw_size"] for ref in refs) != encoded_size_value:
            raise FormatError(f"encoded size disagrees with chunk references: {path}")
        referenced_chunks.update(refs)
        transform = item.get("transform")
        if not isinstance(transform, dict):
            raise FormatError(f"invalid transform schema: {path}")
        transform_id = transform.get("id")
        transform_mode = transform.get("mode")
        if transform_id == "none":
            if transform_mode != "exact":
                raise FormatError(f"invalid identity transform: {path}")
        elif transform_id == TRANSFORMER.id:
            if transform_mode not in {"exact", "canonical"}:
                raise FormatError(f"invalid telemetry transform mode: {path}")
            for field in ("applied", "detected"):
                values = transform.get(field)
                if (
                    not isinstance(values, list)
                    or len(values) > 4096
                    or any(not isinstance(value, str) for value in values)
                ):
                    raise FormatError(f"invalid telemetry transform metadata: {path}")
            if transform_mode == "canonical" and (
                size_value > MAX_TRANSFORM_SIZE
                or encoded_size_value > MAX_TRANSFORM_SIZE
            ):
                raise FormatError(f"transformed file exceeds safety limit: {path}")
        else:
            raise FormatError(f"unsupported transform: {path}")
        if transform_mode == "exact" and (
            size_value != encoded_size_value
            or source_size_value != size_value
            or item["hash"] != item["encoded_hash"]
        ):
            raise FormatError(f"identity transform sizes or hashes disagree: {path}")
        decision = item.get("decision")
        if (
            not isinstance(decision, dict)
            or decision.get("preferred_codec") not in CODECS
            or not isinstance(decision.get("reason"), str)
            or (
                decision.get("level") is not None
                and (
                    isinstance(decision.get("level"), bool)
                    or not isinstance(decision.get("level"), int)
                )
            )
            or not isinstance(decision.get("candidates"), list)
            or not decision["candidates"]
            or len(decision["candidates"]) > 32
        ):
            raise FormatError(f"invalid codec decision schema: {path}")
        for candidate in decision["candidates"]:
            if (
                not isinstance(candidate, dict)
                or candidate.get("codec") not in CODECS
                or (
                    candidate.get("level") is not None
                    and (
                        isinstance(candidate.get("level"), bool)
                        or not isinstance(candidate.get("level"), int)
                    )
                )
                or not integer(candidate.get("packed_bytes"))
                or not integer(candidate.get("sample_bytes"))
                or candidate["sample_bytes"] > MAX_SAMPLE
                or not integer(candidate.get("score"))
            ):
                raise FormatError(f"invalid codec candidate schema: {path}")
        chunk_decisions = item.get("chunk_decisions")
        if not isinstance(chunk_decisions, list) or len(chunk_decisions) != len(refs):
            raise FormatError(f"invalid actual chunk decision list: {path}")
        for ref, actual in zip(refs, chunk_decisions):
            chunk_record = chunks[ref]
            expected_reuse = ref in representations_seen
            if (
                not isinstance(actual, dict)
                or actual.get("chunk") != ref
                or actual.get("actual_codec") != chunk_record["codec"]
                or actual.get("actual_level") != chunk_record.get("level")
                or actual.get("dictionary_id") != chunk_record.get("dictionary_id")
                or actual.get("reused") is not expected_reuse
                or not isinstance(actual.get("reason"), str)
            ):
                raise FormatError(f"inconsistent actual chunk decision: {path}")
            representations_seen.add(ref)
        if "mode" in item and (
            not manifest["store_permissions"]
            or not integer(item["mode"])
            or item["mode"] > 0o777
        ):
            raise FormatError(f"invalid stored permission mode: {path}")
        if "source_category" in item and not isinstance(item["source_category"], str):
            raise FormatError(f"invalid source category: {path}")
    if total > max_extract_size:
        raise FormatError("archive exceeds default extraction-size safety limit")
    if referenced_chunks != set(chunks):
        raise FormatError("manifest contains unreferenced chunk records")
    for directory_value in directories:
        if not isinstance(directory_value, str):
            raise FormatError("invalid directory path type")
        directory = normalize_archive_path(directory_value)
        key = collision_key(directory)
        if directory in paths or key in collisions:
            raise FormatError(f"duplicate or case-colliding destination: {directory}")
        paths.add(directory)
        collisions.add(key)
    for path in paths:
        parent = PurePosixPath(path).parent
        while str(parent) != ".":
            if parent.as_posix() in paths and parent.as_posix() not in directories:
                raise FormatError(f"file conflicts with descendant destination: {parent}")
            parent = parent.parent


def _dictionary_bytes(manifest: dict[str, Any]) -> dict[str, bytes]:
    return {
        dictionary_id: base64.b64decode(record["data"], validate=True)
        for dictionary_id, record in manifest["dictionaries"].items()
    }


def inspect_archive(archive: os.PathLike[str] | str) -> ArchiveInfo:
    path = Path(archive)
    with path.open("rb") as stream:
        manifest, _data, footer = _read_manifest(stream)
        _validate_manifest(manifest, manifest_offset=footer.manifest_offset)
        integrity = (
            "valid"
            if _hash_body(stream, footer.manifest_offset + footer.manifest_size)
            == footer.body_hash
            else "invalid"
        )
    files = manifest["files"]
    original = sum(int(item["size"]) for item in files)
    packed_size = path.stat().st_size
    payload = sum(int(item["packed_size"]) for item in manifest["chunks"].values())
    decisions = tuple({"path": item["path"], **item["decision"]} for item in files)
    return ArchiveInfo(
        path=path,
        format_version=f"{manifest['format']['major']}.{manifest['format']['minor']}",
        lowpack_version=str(manifest["lowpack_version"]),
        profile=str(manifest["profile"]),
        goal=str(manifest["goal"]),
        file_count=len(files),
        directory_count=len(manifest["directories"]),
        chunk_count=sum(len(item["chunks"]) for item in files),
        unique_chunk_count=len(manifest["chunks"]),
        original_size=original,
        packed_size=packed_size,
        container_overhead=packed_size - payload,
        compression_ratio=(packed_size / original) if original else 0.0,
        manifest_hash=footer.manifest_hash.hex(),
        codec_versions=dict(manifest["codec_versions"]),
        integrity_status=integrity,
        decisions=decisions,
    )


def verify_archive(archive: os.PathLike[str] | str, *, full: bool = True) -> VerificationResult:
    errors: list[str] = []
    files_verified = 0
    chunks_verified = 0
    try:
        with Path(archive).open("rb") as stream:
            manifest, _data, footer = _read_manifest(stream)
            _validate_manifest(manifest, manifest_offset=footer.manifest_offset)
            actual_body_hash = _hash_body(stream, footer.manifest_offset + footer.manifest_size)
            if actual_body_hash != footer.body_hash:
                raise FormatError("archive body hash mismatch")
            chunks = manifest["chunks"]
            dictionaries = _dictionary_bytes(manifest)
            if full:
                verified_chunks: set[str] = set()
                for item in manifest["files"]:
                    encoded_hash = hashlib.sha256()
                    encoded_size = 0
                    output_hash = hashlib.sha256()
                    encoded_buffer = bytearray()
                    identity = item["transform"]["mode"] == "exact"
                    for chunk_id in item["chunks"]:
                        raw = _read_chunk(
                            stream, chunk_id, chunks[chunk_id], dictionaries
                        )
                        verified_chunks.add(chunk_id)
                        encoded_hash.update(raw)
                        encoded_size += len(raw)
                        if identity:
                            output_hash.update(raw)
                        else:
                            if len(encoded_buffer) + len(raw) > MAX_TRANSFORM_SIZE:
                                raise FormatError(
                                    f"transformed input exceeds safety limit: {item['path']}"
                                )
                            encoded_buffer.extend(raw)
                    if encoded_size != item["encoded_size"] or (
                        encoded_hash.hexdigest() != item["encoded_hash"]
                    ):
                        raise FormatError(f"encoded file hash mismatch: {item['path']}")
                    if identity:
                        output_size = encoded_size
                    else:
                        decoded = _decode_file(bytes(encoded_buffer), item)
                        output_hash.update(decoded)
                        output_size = len(decoded)
                    if output_size != item["size"] or output_hash.hexdigest() != item["hash"]:
                        raise FormatError(f"file reconstruction hash mismatch: {item['path']}")
                    files_verified += 1
                chunks_verified = len(verified_chunks)
            else:
                for chunk_id, record in chunks.items():
                    offset = int(record["offset"])
                    if (
                        offset < HEADER.size
                        or offset + CHUNK_HEADER.size + int(record["packed_size"])
                        > footer.manifest_offset
                    ):
                        raise FormatError(f"chunk boundary outside payload area: {chunk_id}")
                    stream.seek(offset)
                    header = stream.read(CHUNK_HEADER.size)
                    if len(header) != CHUNK_HEADER.size:
                        raise FormatError(f"truncated chunk header: {chunk_id}")
                    magic, codec_id, raw_size, packed_size, raw_hash = CHUNK_HEADER.unpack(
                        header
                    )
                    if (
                        magic != CHUNK_MAGIC
                        or header[5:8] != b"\x00\x00\x00"
                        or CODEC_NAMES.get(codec_id) != record["codec"]
                        or raw_size != record["raw_size"]
                        or packed_size != record["packed_size"]
                        or raw_hash.hex() != chunk_id
                    ):
                        raise FormatError(f"invalid chunk header: {chunk_id}")
                chunks_verified = len(chunks)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    return VerificationResult(
        not errors, "full" if full else "quick", files_verified, chunks_verified, tuple(errors)
    )


def _decode_file(encoded: bytes, item: dict[str, Any]) -> bytes:
    transform = item.get("transform", {"id": "none"})
    if transform.get("id") == TRANSFORMER.id:
        try:
            return TRANSFORMER.decode(
                EncodedData(encoded, transform),
                max_output_size=MAX_TRANSFORM_SIZE,
                expected_output_size=int(item["size"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise FormatError(f"invalid transformed payload: {item['path']}") from exc
    return encoded


def unpack(
    archive: os.PathLike[str] | str,
    *,
    output: os.PathLike[str] | str = ".",
    paths: Sequence[str] | None = None,
    overwrite: bool = False,
    verify: bool = True,
    restore_permissions: bool = False,
    max_extract_size: int = MAX_EXTRACT_SIZE,
    max_files: int = MAX_FILES,
    max_chunks: int = MAX_CHUNKS,
) -> list[Path]:
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    selected = tuple(normalize_archive_path(path.rstrip("/")) for path in paths or ())
    extracted: list[Path] = []
    with Path(archive).open("rb") as stream:
        manifest, _data, _footer = _read_manifest(stream)
        _validate_manifest(
            manifest,
            max_extract_size=max_extract_size,
            max_files=max_files,
            max_chunks=max_chunks,
            manifest_offset=_footer.manifest_offset,
        )
        dictionaries = _dictionary_bytes(manifest)
        for directory in manifest["directories"]:
            if selected and not any(
                directory == value or directory.startswith(value + "/") for value in selected
            ):
                continue
            destination = safe_destination(root, directory)
            destination.mkdir(parents=True, exist_ok=True)
        for item in manifest["files"]:
            path = item["path"]
            if selected and not any(
                path == value or path.startswith(value + "/") for value in selected
            ):
                continue
            destination = safe_destination(root, path)
            if destination.exists() and not overwrite:
                raise FileExistsError(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(destination.parent).free < int(item["size"]):
                raise OSError(f"insufficient free disk space for {path}")
            handle, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.", suffix=".lowpack-tmp", dir=destination.parent
            )
            temporary = Path(temporary_name)
            try:
                encoded_hash = hashlib.sha256()
                output_hash = hashlib.sha256()
                encoded_size = 0
                output_size = 0
                identity = item["transform"]["mode"] == "exact"
                encoded_buffer = bytearray()
                with os.fdopen(handle, "wb") as output_stream:
                    for chunk_id in item["chunks"]:
                        raw = _read_chunk(
                            stream,
                            chunk_id,
                            manifest["chunks"][chunk_id],
                            dictionaries,
                        )
                        encoded_hash.update(raw)
                        encoded_size += len(raw)
                        if identity:
                            output_stream.write(raw)
                            output_hash.update(raw)
                            output_size += len(raw)
                        else:
                            if len(encoded_buffer) + len(raw) > MAX_TRANSFORM_SIZE:
                                raise FormatError(
                                    f"transformed input exceeds safety limit: {path}"
                                )
                            encoded_buffer.extend(raw)
                    if encoded_size != item["encoded_size"] or (
                        encoded_hash.hexdigest() != item["encoded_hash"]
                    ):
                        raise FormatError(f"encoded file hash mismatch: {path}")
                    if not identity:
                        decoded = _decode_file(bytes(encoded_buffer), item)
                        output_stream.write(decoded)
                        output_hash.update(decoded)
                        output_size = len(decoded)
                    if verify and (
                        output_size != item["size"]
                        or output_hash.hexdigest() != item["hash"]
                    ):
                        raise FormatError(f"file integrity check failed: {path}")
                    output_stream.flush()
                    os.fsync(output_stream.fileno())
                if safe_destination(root, path) != destination:
                    raise FormatError(f"destination changed during extraction: {path}")
                os.replace(temporary, destination)
                if restore_permissions and "mode" in item:
                    destination.chmod(int(item["mode"]) & 0o777)
                extracted.append(destination)
            except BaseException:
                try:
                    os.close(handle)
                except OSError:
                    pass
                temporary.unlink(missing_ok=True)
                raise
    return extracted
