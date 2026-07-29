"""Bounded, explainable codec selection."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .codecs import CODECS

MAX_SAMPLE = 256 * 1024


@dataclass(frozen=True)
class Selection:
    codec: str
    level: int | None
    elapsed_ns: int
    candidates: tuple[dict[str, Any], ...]
    reason: str


def select_codec(
    data: bytes,
    *,
    goal: str = "balanced",
    requested: str | None = None,
    level: int | None = None,
    already_compressed: bool = False,
) -> Selection:
    started = time.perf_counter_ns()
    sample = data[:MAX_SAMPLE]
    if requested:
        candidates = [(requested, level)]
    elif already_compressed:
        candidates = [("store", None), ("zstd", 1)]
    else:
        levels = {"smallest": 9, "fastest": 1, "fastest-decode": 1, "low-memory": 1}
        candidates = [("store", None), ("zlib", 6), ("zstd", levels.get(goal, 3))]
    measured: list[dict[str, Any]] = []
    for codec_name, codec_level in candidates:
        begin = time.perf_counter_ns()
        packed = CODECS[codec_name].compress(sample, level=codec_level)
        compress_ns = time.perf_counter_ns() - begin
        begin = time.perf_counter_ns()
        CODECS[codec_name].decompress(packed, expected_size=len(sample))
        decode_ns = time.perf_counter_ns() - begin
        # Selection must remain deterministic. Runtime is reported to the caller,
        # but never contributes to the archive decision or canonical manifest.
        penalty = 0
        if goal in {"fastest", "fastest-decode"}:
            penalty = {"store": 0, "zstd": 1024, "zlib": 2048}[codec_name]
        elif goal == "low-memory":
            penalty = {"store": 0, "zstd": 512, "zlib": 2048}[codec_name]
        measured.append(
            {
                "codec": codec_name,
                "level": codec_level,
                "sample_bytes": len(sample),
                "packed_bytes": len(packed),
                "compress_ns": compress_ns,
                "decompress_ns": decode_ns,
                "score": len(packed) + penalty,
            }
        )
    best = min(measured, key=lambda item: (int(item["score"]), str(item["codec"])))
    if requested is None and int(best["packed_bytes"]) >= len(sample) - max(16, len(sample) // 100):
        best = next(item for item in measured if item["codec"] == "store")
    elapsed = time.perf_counter_ns() - started
    return Selection(
        str(best["codec"]),
        best["level"],
        elapsed,
        tuple(measured),
        f"best {goal} score on a bounded {len(sample)}-byte sample",
    )
