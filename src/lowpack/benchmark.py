"""Reproducible local benchmark runner with explicit comparison scopes."""

from __future__ import annotations

import gzip
import io
import os
import platform
import statistics
import tarfile
import tempfile
import time
import tracemalloc
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import Any, Callable

import zstandard

from .archive import inspect_archive, pack, unpack, verify_archive


def _corpus_entries(inputs: Sequence[str]) -> list[tuple[str, bytes]]:
    entries: list[tuple[str, bytes]] = []
    for raw in inputs:
        path = Path(raw)
        if path.is_file():
            entries.append((path.name, path.read_bytes()))
        else:
            for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
                if not item.is_symlink():
                    entries.append(
                        (f"{path.name}/{item.relative_to(path).as_posix()}", item.read_bytes())
                    )
    return entries


def _tar_payload(entries: list[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, data in entries:
            record = tarfile.TarInfo(name)
            record.size = len(data)
            record.mode = 0o644
            record.mtime = 0
            record.uid = record.gid = 0
            record.uname = record.gname = ""
            archive.addfile(record, io.BytesIO(data))
    return output.getvalue()


def _consume_tar(data: bytes) -> int:
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive:
            if member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise RuntimeError(f"cannot read tar member {member.name}")
                total += len(stream.read())
    return total


def _measure(action: Callable[[], Any], repeats: int) -> tuple[int, int]:
    action()
    times: list[int] = []
    peaks: list[int] = []
    for _ in range(repeats):
        tracemalloc.start()
        started = time.perf_counter_ns()
        action()
        times.append(time.perf_counter_ns() - started)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peaks.append(peak)
    return int(statistics.median(times)), max(peaks)


def _row(
    *,
    scope: str,
    name: str,
    original_size: int,
    packed_size: int,
    encode_ns: int,
    decode_ns: int,
    peak_memory: int | None,
    container_overhead: int = 0,
) -> dict[str, Any]:
    return {
        "scope": scope,
        "name": name,
        "original_size": original_size,
        "packed_size": packed_size,
        "ratio": packed_size / original_size if original_size else 0,
        "compression_ns": encode_ns,
        "decompression_ns": decode_ns,
        "compression_mib_s": (
            (original_size / 1048576) / (encode_ns / 1e9) if encode_ns else 0
        ),
        "decompression_mib_s": (
            (original_size / 1048576) / (decode_ns / 1e9) if decode_ns else 0
        ),
        "peak_memory": peak_memory,
        "selection_ns": 0,
        "container_overhead": container_overhead,
    }


def benchmark(
    inputs: Sequence[str], *, profile: str = "general", repeats: int = 3
) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("benchmark repeats must be positive")
    entries = _corpus_entries(inputs)
    raw = b"".join(data for _name, data in entries)
    tar_data = _tar_payload(entries)
    rows: list[dict[str, Any]] = []
    compressors: list[tuple[str, Callable[[bytes], bytes], Callable[[bytes], bytes]]] = [
        ("store", lambda data: data, lambda data: data),
        ("gzip-6", lambda data: gzip.compress(data, compresslevel=6, mtime=0), gzip.decompress),
    ]
    for level in (1, 3, 9):
        compressors.append(
            (
                f"zstd-{level}",
                zstandard.ZstdCompressor(level=level).compress,
                zstandard.ZstdDecompressor().decompress,
            )
        )
    for name, compress, decompress in compressors:
        packed = compress(raw)
        encode_ns, peak = _measure(partial(compress, raw), repeats)
        decode_ns, _ = _measure(partial(decompress, packed), repeats)
        rows.append(
            _row(
                scope="raw-payload",
                name=name,
                original_size=len(raw),
                packed_size=len(packed),
                encode_ns=encode_ns,
                decode_ns=decode_ns,
                peak_memory=peak,
            )
        )
    for name, compress, decompress in compressors[1:]:
        packed = compress(tar_data)
        encode_ns, peak = _measure(partial(compress, tar_data), repeats)

        def decode_tar(
            payload: bytes = packed,
            decoder: Callable[[bytes], bytes] = decompress,
        ) -> int:
            return _consume_tar(decoder(payload))

        decode_ns, _ = _measure(decode_tar, repeats)
        rows.append(
            _row(
                scope="tar-container",
                name=f"tar+{name}",
                original_size=len(raw),
                packed_size=len(packed),
                encode_ns=encode_ns,
                decode_ns=decode_ns,
                peak_memory=peak,
                container_overhead=len(tar_data) - len(raw),
            )
        )
    profiles = ["general"]
    if profile not in profiles:
        profiles.append(profile)
    with tempfile.TemporaryDirectory(prefix="lowpack-benchmark-") as temporary:
        root = Path(temporary)
        for selected_profile in profiles:
            archive = root / f"{selected_profile}.lpk"

            def pack_action(
                output_path: Path = archive,
                active_profile: str = selected_profile,
            ) -> Any:
                return pack(
                    inputs,
                    output_path,
                    profile=active_profile,
                    overwrite=True,
                )

            encode_ns, peak = _measure(pack_action, repeats)
            result = pack_action()
            info = inspect_archive(archive)
            extraction = root / f"extract-{selected_profile}"

            def unpack_action(
                input_path: Path = archive,
                output_path: Path = extraction,
            ) -> Any:
                return unpack(input_path, output=output_path, overwrite=True)

            extract_ns, _ = _measure(unpack_action, repeats)
            verify_ns, _ = _measure(partial(verify_archive, archive, full=True), repeats)
            verification = verify_archive(archive, full=True)
            if not verification.valid:
                raise RuntimeError("; ".join(verification.errors))
            row = _row(
                scope="full-archive",
                name=f"lowpack-{selected_profile}",
                original_size=result.original_size,
                packed_size=result.packed_size,
                encode_ns=encode_ns,
                decode_ns=extract_ns,
                peak_memory=peak,
                container_overhead=info.container_overhead,
            )
            row.update(
                {
                    "selection_ns": result.selection_ns,
                    "file_extraction_ns": extract_ns,
                    "full_verification_ns": verify_ns,
                }
            )
            rows.append(row)
    return {
        "methodology": {
            "raw-payload": "concatenated payload bytes only",
            "tar-container": "deterministic tar framing plus compressor and tar parsing",
            "full-archive": "LowPack pack, extraction, and full verification",
        },
        "environment": {
            "machine": platform.machine(),
            "os": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "repeats": repeats,
            "warmups": 1,
        },
        "results": rows,
    }


def markdown_report(result: dict[str, Any]) -> str:
    environment = result["environment"]
    lines = [
        "# LowPack benchmark",
        "",
        (
            f"Python {environment['python']} on {environment['os']} "
            f"({environment['machine']}); {environment['warmups']} warm-up, "
            f"{environment['repeats']} measured runs. Fixed-seed generated corpus."
        ),
        "",
        "| Scope | Method | Original | Packed | Ratio | Encode ms | Decode ms |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in result["results"]:
        lines.append(
            f"| {row['scope']} | {row['name']} | {row['original_size']} | "
            f"{row['packed_size']} | {row['ratio']:.3f} | "
            f"{row['compression_ns'] / 1e6:.3f} | "
            f"{row['decompression_ns'] / 1e6:.3f} |"
        )
    return "\n".join(lines) + "\n"
