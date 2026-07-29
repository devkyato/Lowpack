"""Archive creation, inspection, verification, and extraction."""

from __future__ import annotations

import base64
import fnmatch
import hashlib
import json
import os
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
MAX_EXTRACT_SIZE = 100 * 1024 * 1024 * 1024
MAX_DICTIONARY_SAMPLE = 1024 * 1024
MAX_DICTIONARY_FILE_SAMPLE = 64 * 1024
DICTIONARY_SIZE = 8192


def _iter_file_chunks(path: Path, chunk_size: int) -> Iterator[bytes]:
    with path.open("rb") as stream:
        while True:
            data = stream.read(chunk_size)
            if not data:
                break
            yield data


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
) -> tuple[list[tuple[Path, str]], list[str], list[str]]:
    files: list[tuple[Path, str]] = []
    directories: list[str] = []
    excluded: list[str] = []
    defaults = () if include_all or profile != "source" else DEFAULT_EXCLUDES
    patterns = tuple(defaults) + tuple(excludes)
    seen: set[str] = set()
    for raw_input in inputs:
        source = Path(raw_input)
        if not source.exists():
            raise FileNotFoundError(source)
        if source.is_symlink() and not follow_symlinks:
            excluded.append(str(source))
            continue
        if source.is_file():
            archive_path = normalize_archive_path(source.name)
            if not includes or _patterns_match(archive_path, includes):
                files.append((source, archive_path))
            continue
        root_name = normalize_archive_path(source.name)
        directories.append(root_name)
        for current, dir_names, file_names in os.walk(source, followlinks=follow_symlinks):
            current_path = Path(current)
            relative = current_path.relative_to(source)
            archive_dir = (
                root_name if str(relative) == "." else f"{root_name}/{relative.as_posix()}"
            )
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
            directories.append(normalize_archive_path(archive_dir))
            for name in sorted(file_names):
                disk_path = current_path / name
                archive_path = normalize_archive_path(f"{archive_dir}/{name}")
                if disk_path.is_symlink() and not follow_symlinks:
                    excluded.append(archive_path)
                elif _patterns_match(archive_path, patterns):
                    excluded.append(archive_path)
                elif includes and not _patterns_match(archive_path, includes):
                    excluded.append(archive_path)
                else:
                    if archive_path in seen:
                        raise ValueError(f"duplicate archive path: {archive_path}")
                    seen.add(archive_path)
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
        sample = disk_path.read_bytes()[:MAX_DICTIONARY_FILE_SAMPLE]
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
    if goal not in {"balanced", "smallest", "fastest", "fastest-decode", "low-memory"}:
        raise ValueError(f"unknown goal: {goal}")
    if codec is not None and codec not in CODECS:
        raise ValueError(f"unknown codec: {codec}")
    if chunk_size < 4096 or chunk_size > 1024 * 1024 * 1024:
        raise ValueError("chunk size must be between 4 KiB and 1 GiB")
    target = Path(archive)
    if target.exists() and not overwrite:
        raise FileExistsError(target)
    files, directories, excluded = _collect_inputs(
        inputs,
        profile=profile,
        excludes=exclude,
        includes=include,
        include_all=include_all,
        follow_symlinks=follow_symlinks,
    )
    source_dictionaries = _train_source_dictionaries(files, profile)
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
        with temp_path.open("w+b") as stream:
            write_header(stream)
            for disk_path, archive_path in files:
                raw_size = disk_path.stat().st_size
                with disk_path.open("rb") as sample_stream:
                    sample = sample_stream.read(MAX_SAMPLE)
                transformed: bytes | None = None
                reconstructed: bytes | None = None
                transform_metadata: dict[str, Any] = {"id": "none", "mode": "exact"}
                if profile == "telemetry" and disk_path.suffix.lower() == ".csv":
                    raw = disk_path.read_bytes()
                    encoded = TRANSFORMER.encode(
                        raw, TransformOptions(mode=telemetry_mode, time_field=time_field)
                    )
                    transformed = encoded.data
                    transform_metadata = encoded.metadata
                    reconstructed = TRANSFORMER.decode(encoded)
                    sample = transformed[:MAX_SAMPLE]
                selection: Selection = select_codec(
                    sample,
                    goal=goal,
                    requested=codec,
                    level=level,
                    already_compressed=is_already_compressed(sample),
                )
                selection_ns += selection.elapsed_ns
                dictionary = source_dictionaries.get(category(archive_path))
                refs: list[str] = []
                file_hash = hashlib.sha256()
                encoded_hash = hashlib.sha256()
                encoded_size = 0
                chunks = (
                    (
                        transformed[index : index + chunk_size]
                        for index in range(0, len(transformed), chunk_size)
                    )
                    if transformed is not None
                    else _iter_file_chunks(disk_path, chunk_size)
                )
                for raw_chunk in chunks:
                    encoded_hash.update(raw_chunk)
                    encoded_size += len(raw_chunk)
                    chunk_id = sha256_hex(raw_chunk)
                    refs.append(chunk_id)
                    if chunk_id in chunk_records:
                        continue
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
                    chunk_records[chunk_id] = {
                        "codec": selection.codec,
                        "level": selection.level,
                        "offset": offset,
                        "packed_size": len(packed),
                        "raw_size": len(raw_chunk),
                    }
                    if selection.codec == "zstd" and dictionary is not None:
                        chunk_records[chunk_id]["dictionary"] = base64.b64encode(
                            dictionary
                        ).decode("ascii")
                if reconstructed is not None:
                    file_hash.update(reconstructed)
                    output_size = len(reconstructed)
                else:
                    for raw_chunk in _iter_file_chunks(disk_path, chunk_size):
                        file_hash.update(raw_chunk)
                    output_size = raw_size
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
                    "final_codec": selection.codec,
                    "level": selection.level,
                    "reason": selection.reason,
                }
                record: dict[str, Any] = {
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
                    record["mode"] = stat.S_IMODE(disk_path.stat().st_mode)
                file_records.append(record)
            manifest: dict[str, Any] = {
                "chunk_size": chunk_size,
                "chunks": chunk_records,
                "codec_versions": {
                    "store": "1",
                    "zlib": __import__("zlib").ZLIB_VERSION,
                    "zstd": zstandard.__version__,
                },
                "directories": directories,
                "excluded": excluded,
                "files": file_records,
                "format": {"major": VERSION_MAJOR, "minor": VERSION_MINOR},
                "goal": goal,
                "lowpack_version": __version__,
                "profile": profile,
                "source_dictionaries": {
                    group: {
                        "bytes": len(dictionary),
                        "hash": sha256_hex(dictionary),
                    }
                    for group, dictionary in sorted(source_dictionaries.items())
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


def _read_chunk(stream: BinaryIO, chunk_id: str, record: dict[str, Any]) -> bytes:
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
        if codec_name == "zstd" and "dictionary" in record:
            dictionary = base64.b64decode(record["dictionary"], validate=True)
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
) -> None:
    files = manifest.get("files")
    chunks = manifest.get("chunks")
    directories = manifest.get("directories")
    if (
        not isinstance(files, list)
        or not isinstance(chunks, dict)
        or not isinstance(directories, list)
    ):
        raise FormatError("manifest is missing required collections")
    if len(files) > max_files or len(chunks) > max_chunks:
        raise FormatError("archive exceeds object-count safety limit")
    format_record = manifest.get("format")
    chunk_size = manifest.get("chunk_size")
    if (
        not isinstance(format_record, dict)
        or format_record.get("major") != VERSION_MAJOR
        or format_record.get("minor") != VERSION_MINOR
        or not isinstance(chunk_size, int)
        or chunk_size < 4096
        or chunk_size > 1024 * 1024 * 1024
    ):
        raise FormatError("unsupported or inconsistent manifest format settings")
    for chunk_id, record in chunks.items():
        if (
            not isinstance(chunk_id, str)
            or len(chunk_id) != 64
            or not isinstance(record, dict)
            or record.get("codec") not in CODECS
            or not isinstance(record.get("offset"), int)
            or not isinstance(record.get("raw_size"), int)
            or not isinstance(record.get("packed_size"), int)
            or record["offset"] < HEADER.size
            or record["raw_size"] < 0
            or record["raw_size"] > chunk_size
            or record["packed_size"] < 0
        ):
            raise FormatError("invalid chunk index record")
        try:
            bytes.fromhex(chunk_id)
            if "dictionary" in record:
                dictionary = base64.b64decode(record["dictionary"], validate=True)
                if len(dictionary) > 64 * 1024:
                    raise FormatError("compression dictionary exceeds safety limit")
        except (ValueError, TypeError) as exc:
            raise FormatError("invalid chunk hash or dictionary") from exc
    paths: set[str] = set()
    collisions: set[str] = set()
    total = 0
    for item in files:
        if not isinstance(item, dict):
            raise FormatError("invalid file record")
        path = normalize_archive_path(str(item.get("path", "")))
        key = collision_key(path)
        if path in paths or key in collisions:
            raise FormatError(f"duplicate or case-colliding destination: {path}")
        paths.add(path)
        collisions.add(key)
        size = item.get("size")
        if not isinstance(size, int) or size < 0:
            raise FormatError(f"invalid declared file size: {path}")
        total += size
        refs = item.get("chunks")
        if not isinstance(refs, list) or len(refs) > max_chunks:
            raise FormatError(f"invalid chunk references: {path}")
        if any(ref not in chunks for ref in refs):
            raise FormatError(f"file references an unknown chunk: {path}")
    if total > max_extract_size:
        raise FormatError("archive exceeds default extraction-size safety limit")
    for directory_value in directories:
        directory = normalize_archive_path(str(directory_value))
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


def inspect_archive(archive: os.PathLike[str] | str) -> ArchiveInfo:
    path = Path(archive)
    with path.open("rb") as stream:
        manifest, _data, footer = _read_manifest(stream)
        _validate_manifest(manifest)
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
            _validate_manifest(manifest)
            actual_body_hash = _hash_body(stream, footer.manifest_offset + footer.manifest_size)
            if actual_body_hash != footer.body_hash:
                raise FormatError("archive body hash mismatch")
            chunks = manifest["chunks"]
            if full:
                cache: dict[str, bytes] = {}
                for chunk_id, record in chunks.items():
                    cache[chunk_id] = _read_chunk(stream, chunk_id, record)
                    chunks_verified += 1
                for item in manifest["files"]:
                    encoded = b"".join(cache[chunk_id] for chunk_id in item["chunks"])
                    if (
                        len(encoded) != item["encoded_size"]
                        or sha256_hex(encoded) != item["encoded_hash"]
                    ):
                        raise FormatError(f"encoded file hash mismatch: {item['path']}")
                    decoded = _decode_file(encoded, item)
                    if len(decoded) != item["size"] or sha256_hex(decoded) != item["hash"]:
                        raise FormatError(f"file reconstruction hash mismatch: {item['path']}")
                    files_verified += 1
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
        return TRANSFORMER.decode(EncodedData(encoded, transform))
    return encoded


def unpack(
    archive: os.PathLike[str] | str,
    *,
    output: os.PathLike[str] | str = ".",
    paths: Sequence[str] | None = None,
    overwrite: bool = False,
    verify: bool = True,
    restore_permissions: bool = True,
    max_extract_size: int = MAX_EXTRACT_SIZE,
    max_files: int = MAX_FILES,
    max_chunks: int = MAX_CHUNKS,
) -> list[Path]:
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    selected = tuple(normalize_archive_path(path.rstrip("/")) for path in paths or ())
    extracted: list[Path] = []
    created_dirs: list[Path] = []
    with Path(archive).open("rb") as stream:
        manifest, _data, _footer = _read_manifest(stream)
        _validate_manifest(
            manifest,
            max_extract_size=max_extract_size,
            max_files=max_files,
            max_chunks=max_chunks,
        )
        for directory in manifest["directories"]:
            if selected and not any(
                directory == value or directory.startswith(value + "/") for value in selected
            ):
                continue
            destination = safe_destination(root, directory)
            destination.mkdir(parents=True, exist_ok=True)
            created_dirs.append(destination)
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
            os.close(handle)
            temporary = Path(temporary_name)
            try:
                encoded_parts = [
                    _read_chunk(stream, chunk_id, manifest["chunks"][chunk_id])
                    for chunk_id in item["chunks"]
                ]
                decoded = _decode_file(b"".join(encoded_parts), item)
                if verify and (len(decoded) != item["size"] or sha256_hex(decoded) != item["hash"]):
                    raise FormatError(f"file integrity check failed: {path}")
                with temporary.open("wb") as output_stream:
                    output_stream.write(decoded)
                    output_stream.flush()
                    os.fsync(output_stream.fileno())
                os.replace(temporary, destination)
                if restore_permissions and "mode" in item:
                    destination.chmod(int(item["mode"]))
                extracted.append(destination)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
    return extracted
