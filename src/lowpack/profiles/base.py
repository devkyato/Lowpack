"""Experimental transformation extension API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SourceInfo:
    path: str
    size: int
    sample: bytes


@dataclass(frozen=True)
class DetectionResult:
    confidence: int
    details: dict[str, Any]


@dataclass(frozen=True)
class TransformOptions:
    mode: str = "exact"
    time_field: str | None = None


@dataclass(frozen=True)
class EncodedData:
    data: bytes
    metadata: dict[str, Any]


class Transformer(Protocol):
    id: str

    def detect(self, source: SourceInfo) -> DetectionResult: ...

    def encode(self, data: bytes, options: TransformOptions) -> EncodedData: ...

    def decode(self, encoded: EncodedData) -> bytes: ...
