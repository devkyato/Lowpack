"""Typed public result models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PackResult:
    archive: Path
    file_count: int
    directory_count: int
    original_size: int
    packed_size: int
    chunk_count: int
    unique_chunk_count: int
    selection_ns: int
    excluded: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    mode: str
    files_verified: int
    chunks_verified: int
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MigrationResult:
    source: Path
    archive: Path
    source_format: str
    target_format: str
    file_count: int
    chunk_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompatibilityResult:
    archive: Path
    format_version: str
    status: str
    current: bool
    migration_supported: bool
    target_format: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArchiveInfo:
    path: Path
    format_version: str
    lowpack_version: str
    profile: str
    goal: str
    file_count: int
    directory_count: int
    chunk_count: int
    unique_chunk_count: int
    original_size: int
    packed_size: int
    container_overhead: int
    compression_ratio: float
    manifest_hash: str
    codec_versions: dict[str, str] = field(default_factory=dict)
    integrity_status: str = "not verified"
    decisions: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
