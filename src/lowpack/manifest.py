"""Canonical manifest serialization and validation."""

from __future__ import annotations

import json
from typing import Any

from .format import FormatError


def encode_manifest(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def decode_manifest(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise FormatError("manifest is not valid canonical UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise FormatError("manifest root must be an object")
    if encode_manifest(value) != data:
        raise FormatError("manifest is not in canonical form")
    pending: list[tuple[Any, int]] = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if depth > 64:
            raise FormatError("manifest nesting exceeds safety limit")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value
