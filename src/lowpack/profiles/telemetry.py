"""Deterministic, reversible CSV column transforms."""

from __future__ import annotations

import base64
import csv
import io
import json
import struct
from typing import Any

from .base import EncodedData, TransformOptions

MAGIC = b"LPTCSV1\n"


def _bits(values: list[bool]) -> str:
    packed = bytearray((len(values) + 7) // 8)
    for index, value in enumerate(values):
        if value:
            packed[index // 8] |= 1 << (index % 8)
    return base64.b64encode(packed).decode("ascii")


def _unbits(value: str, count: int) -> list[bool]:
    packed = base64.b64decode(value)
    return [bool(packed[index // 8] & (1 << (index % 8))) for index in range(count)]


def _delta(numbers: list[int]) -> dict[str, Any]:
    if not numbers:
        return {"first": 0, "values": []}
    differences = [right - left for left, right in zip(numbers, numbers[1:])]
    if len(differences) >= 2:
        second = [right - left for left, right in zip(differences, differences[1:])]
        if len(set(second)) <= max(4, len(second) // 8):
            return {
                "encoding": "delta-of-delta",
                "first": numbers[0],
                "first_delta": differences[0],
                "values": second,
            }
    return {"encoding": "delta", "first": numbers[0], "values": differences}


def _undelta(record: dict[str, Any]) -> list[int]:
    values = [int(record["first"])]
    if record["encoding"] == "delta":
        for difference in record["values"]:
            values.append(values[-1] + int(difference))
    else:
        difference = int(record["first_delta"])
        if record["values"] or difference:
            values.append(values[-1] + difference)
        for second in record["values"]:
            difference += int(second)
            values.append(values[-1] + difference)
    return values


def _infer(values: list[str], name: str, time_field: str | None) -> tuple[str, str]:
    non_null = [value for value in values if value != ""]
    if name == time_field:
        try:
            [int(value) for value in non_null]
            return "timestamp", "delta"
        except ValueError:
            return "timestamp-text", "dictionary"
    lowered = {value.lower() for value in non_null}
    if non_null and lowered <= {"true", "false", "0", "1"}:
        return "boolean", "bit-pack"
    try:
        numbers = [int(value) for value in non_null]
        if numbers:
            monotonic = all(a <= b for a, b in zip(numbers, numbers[1:]))
            return "integer", "delta" if monotonic else "plain"
    except ValueError:
        pass
    try:
        for value in non_null:
            float(value)
        if non_null:
            return "float", "ieee-754"
    except ValueError:
        pass
    unique = len(set(non_null))
    if non_null and unique <= max(16, len(non_null) // 4):
        return "string", "dictionary"
    if len(non_null) > 2 and unique < len(non_null) * 3 // 4:
        return "string", "rle"
    return "string", "plain"


def _encode_values(values: list[str], kind: str, encoding: str) -> dict[str, Any]:
    non_null = [value for value in values if value != ""]
    record: dict[str, Any] = {
        "encoding": encoding,
        "null_bitmap": _bits([value == "" for value in values]),
        "row_count": len(values),
        "type": kind,
    }
    if encoding == "delta":
        record.update(_delta([int(value) for value in non_null]))
    elif encoding == "bit-pack":
        record["count"] = len(non_null)
        record["values"] = _bits([value.lower() in {"true", "1"} for value in non_null])
        record["style"] = (
            "word" if any(value.lower() in {"true", "false"} for value in non_null) else "digit"
        )
    elif encoding == "dictionary":
        dictionary = sorted(set(non_null))
        record["dictionary"] = dictionary
        record["indices"] = [dictionary.index(value) for value in non_null]
    elif encoding == "rle":
        runs: list[list[Any]] = []
        for value in non_null:
            if runs and runs[-1][0] == value:
                runs[-1][1] += 1
            else:
                runs.append([value, 1])
        record["runs"] = runs
    elif encoding == "ieee-754":
        packed = b"".join(struct.pack(">d", float(value)) for value in non_null)
        record["values"] = base64.b64encode(packed).decode("ascii")
    else:
        record["values"] = non_null
    return record


def _decode_values(record: dict[str, Any]) -> list[str]:
    encoding = record["encoding"]
    if encoding in {"delta", "delta-of-delta"}:
        non_null = [str(value) for value in _undelta(record)]
    elif encoding == "bit-pack":
        words = _unbits(record["values"], int(record["count"]))
        if record["style"] == "word":
            non_null = ["true" if value else "false" for value in words]
        else:
            non_null = ["1" if value else "0" for value in words]
    elif encoding == "dictionary":
        non_null = [record["dictionary"][index] for index in record["indices"]]
    elif encoding == "rle":
        non_null = [value for value, count in record["runs"] for _ in range(int(count))]
    elif encoding == "ieee-754":
        packed = base64.b64decode(record["values"])
        non_null = [
            repr(struct.unpack(">d", packed[index : index + 8])[0])
            for index in range(0, len(packed), 8)
        ]
    else:
        non_null = list(record["values"])
    nulls = _unbits(record["null_bitmap"], int(record["row_count"]))
    iterator = iter(non_null)
    return ["" if is_null else next(iterator) for is_null in nulls]


def _parse(data: bytes) -> tuple[list[str], list[list[str]]]:
    reader = csv.reader(io.StringIO(data.decode("utf-8"), newline=""))
    rows = list(reader)
    if not rows:
        return [], []
    width = len(rows[0])
    if any(len(row) != width for row in rows[1:]):
        raise ValueError("telemetry CSV has inconsistent row widths")
    return rows[0], [[row[index] for row in rows[1:]] for index in range(width)]


class TelemetryTransformer:
    id = "telemetry-csv-v1"

    def encode(self, data: bytes, options: TransformOptions) -> EncodedData:
        header, columns = _parse(data)
        inferred = [
            (name, values, *_infer(values, name, options.time_field))
            for name, values in zip(header, columns)
        ]
        detected = [f"{kind} column {name}" for name, _values, kind, _ in inferred]
        if options.mode == "exact":
            return EncodedData(
                data,
                {
                    "applied": ["exact byte preservation"],
                    "detected": detected,
                    "id": self.id,
                    "mode": "exact",
                },
            )
        column_records: list[dict[str, Any]] = []
        applied = ["column separation", "null bitmap"]
        for name, values, kind, encoding in inferred:
            record = _encode_values(values, kind, encoding)
            record["name"] = name
            column_records.append(record)
            applied.append(f"{record['encoding']} encoding for {name}")
        payload = {
            "columns": column_records,
            "header": header,
            "row_count": len(columns[0]) if columns else 0,
        }
        encoded = MAGIC + json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return EncodedData(
            encoded,
            {
                "applied": applied,
                "detected": detected,
                "id": self.id,
                "mode": "canonical",
            },
        )

    def decode(self, encoded: EncodedData) -> bytes:
        if encoded.metadata.get("mode") == "exact":
            return encoded.data
        if not encoded.data.startswith(MAGIC):
            raise ValueError("invalid telemetry transformation")
        value = json.loads(encoded.data[len(MAGIC) :].decode("utf-8"))
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(value["header"])
        columns = [_decode_values(record) for record in value["columns"]]
        for row_index in range(value["row_count"]):
            writer.writerow([column[row_index] for column in columns])
        return output.getvalue().encode("utf-8")


TRANSFORMER = TelemetryTransformer()
