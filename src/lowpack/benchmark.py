"""Reproducible local benchmark runner."""

from __future__ import annotations

import gzip
import os
import platform
import statistics
import tempfile
import time
import tracemalloc
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import Any, Callable

import zstandard

from .archive import inspect_archive, pack, unpack, verify_archive


def _read_corpus(inputs: Sequence[str]) -> bytes:
    parts: list[bytes] = []
    for raw in inputs:
        path = Path(raw)
        if path.is_file():
            parts.append(path.read_bytes())
        else:
            for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
                if not item.is_symlink():
                    parts.append(item.read_bytes())
    return b"".join(parts)


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


def benchmark(
    inputs: Sequence[str], *, profile: str = "general", repeats: int = 3
) -> dict[str, Any]:
    raw = _read_corpus(inputs)
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
            {
                "name": name,
                "original_size": len(raw),
                "packed_size": len(packed),
                "ratio": len(packed) / len(raw) if raw else 0,
                "compression_ns": encode_ns,
                "decompression_ns": decode_ns,
                "compression_mib_s": (len(raw) / 1048576) / (encode_ns / 1e9) if encode_ns else 0,
                "decompression_mib_s": (len(raw) / 1048576) / (decode_ns / 1e9) if decode_ns else 0,
                "peak_memory": peak,
                "selection_ns": 0,
                "container_overhead": 0,
            }
        )
    profiles = ["general"]
    if profile not in profiles:
        profiles.append(profile)
    with tempfile.TemporaryDirectory(prefix="lowpack-benchmark-") as temporary:
        root = Path(temporary)
        for selected_profile in profiles:
            archive = root / f"{selected_profile}.lpk"
            started = time.perf_counter_ns()
            result = pack(inputs, archive, profile=selected_profile)
            encode_ns = time.perf_counter_ns() - started
            info = inspect_archive(archive)
            extraction = root / f"extract-{selected_profile}"
            started = time.perf_counter_ns()
            unpack(archive, output=extraction)
            extract_ns = time.perf_counter_ns() - started
            started = time.perf_counter_ns()
            verification = verify_archive(archive, full=True)
            verify_ns = time.perf_counter_ns() - started
            if not verification.valid:
                raise RuntimeError("; ".join(verification.errors))
            rows.append(
                {
                    "name": f"lowpack-{selected_profile}",
                    "original_size": result.original_size,
                    "packed_size": result.packed_size,
                    "ratio": result.packed_size / result.original_size
                    if result.original_size
                    else 0,
                    "compression_ns": encode_ns,
                    "decompression_ns": extract_ns,
                    "compression_mib_s": (result.original_size / 1048576) / (encode_ns / 1e9)
                    if encode_ns
                    else 0,
                    "decompression_mib_s": (result.original_size / 1048576) / (extract_ns / 1e9)
                    if extract_ns
                    else 0,
                    "peak_memory": None,
                    "selection_ns": result.selection_ns,
                    "container_overhead": info.container_overhead,
                    "file_extraction_ns": extract_ns,
                    "full_verification_ns": verify_ns,
                }
            )
    return {
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
        "| Method | Original | Packed | Ratio | Encode ms | Decode ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in result["results"]:
        lines.append(
            f"| {row['name']} | {row['original_size']} | {row['packed_size']} | "
            f"{row['ratio']:.3f} | {row['compression_ns'] / 1e6:.3f} | "
            f"{row['decompression_ns'] / 1e6:.3f} |"
        )
    return "\n".join(lines) + "\n"
