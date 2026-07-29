"""Deterministic, reversible CSV column transforms."""

from __future__ import annotations

import base64
import binascii
import csv
import io
import json
import struct
from typing import Any, cast

from .base import EncodedData, TransformOptions

MAGIC = b"LPTCSV1\n"
MAX_COLUMNS = 4096
MAX_ROWS = 1_000_000
MAX_CELLS = 10_000_000


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"invalid telemetry {name}")
    return cast(int, value)


def _string_list(value: Any, name: str, *, expected: int | None = None) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"invalid telemetry {name}")
    if expected is not None and len(value) != expected:
        raise ValueError(f"invalid telemetry {name} length")
    return value


def _bits(values: list[bool]) -> str:
    packed = bytearray((len(values) + 7) // 8)
    for index, value in enumerate(values):
        if value:
            packed[index // 8] |= 1 << (index % 8)
    return base64.b64encode(packed).decode("ascii")


def _unbits(value: Any, count: int) -> list[bool]:
    if not isinstance(value, str):
        raise ValueError("invalid telemetry bitmap")
    try:
        packed = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid telemetry bitmap") from exc
    if len(packed) != (count + 7) // 8:
        raise ValueError("telemetry bitmap length mismatch")
    if count % 8 and packed and packed[-1] >> (count % 8):
        raise ValueError("telemetry bitmap has nonzero padding")
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


def _decode_values(record: dict[str, Any], row_count: int) -> list[str]:
    if not isinstance(record, dict):
        raise ValueError("invalid telemetry column")
    if _integer(record.get("row_count"), "column row count") != row_count:
        raise ValueError("telemetry column row count mismatch")
    if not isinstance(record.get("name"), str) or not isinstance(record.get("type"), str):
        raise ValueError("invalid telemetry column identity")
    encoding = record.get("encoding")
    if encoding not in {
        "delta",
        "delta-of-delta",
        "bit-pack",
        "dictionary",
        "rle",
        "ieee-754",
        "plain",
    }:
        raise ValueError("unsupported telemetry encoding")
    nulls = _unbits(record.get("null_bitmap"), row_count)
    non_null_count = row_count - sum(nulls)
    if encoding in {"delta", "delta-of-delta"}:
        _integer(record.get("first"), "delta first", minimum=-(2**63))
        values = record.get("values")
        if not isinstance(values, list) or any(
            isinstance(value, bool) or not isinstance(value, int) for value in values
        ):
            raise ValueError("invalid telemetry deltas")
        expected_values = max(0, non_null_count - (2 if encoding == "delta-of-delta" else 1))
        if len(values) != expected_values:
            raise ValueError("telemetry delta count mismatch")
        if encoding == "delta-of-delta":
            if non_null_count < 3:
                raise ValueError("delta-of-delta requires at least three values")
            if isinstance(record.get("first_delta"), bool) or not isinstance(
                record.get("first_delta"), int
            ):
                raise ValueError("invalid telemetry first delta")
        non_null = [str(value) for value in _undelta(record)]
    elif encoding == "bit-pack":
        count = _integer(record.get("count"), "bit count")
        if count != non_null_count:
            raise ValueError("telemetry bit count mismatch")
        words = _unbits(record.get("values"), count)
        if record.get("style") == "word":
            non_null = ["true" if value else "false" for value in words]
        elif record.get("style") == "digit":
            non_null = ["1" if value else "0" for value in words]
        else:
            raise ValueError("invalid telemetry boolean style")
    elif encoding == "dictionary":
        dictionary = _string_list(record.get("dictionary"), "dictionary")
        indices = record.get("indices")
        if (
            not isinstance(indices, list)
            or len(indices) != non_null_count
            or any(isinstance(index, bool) or not isinstance(index, int) for index in indices)
            or any(index < 0 or index >= len(dictionary) for index in indices)
        ):
            raise ValueError("invalid telemetry dictionary indices")
        non_null = [dictionary[index] for index in indices]
    elif encoding == "rle":
        runs = record.get("runs")
        if not isinstance(runs, list):
            raise ValueError("invalid telemetry runs")
        non_null = []
        run_total = 0
        for run in runs:
            if (
                not isinstance(run, list)
                or len(run) != 2
                or not isinstance(run[0], str)
            ):
                raise ValueError("invalid telemetry run")
            count = _integer(run[1], "run length", minimum=1)
            run_total += count
            if run_total > non_null_count:
                raise ValueError("telemetry runs exceed row count")
            non_null.extend([run[0]] * count)
        if run_total != non_null_count:
            raise ValueError("telemetry run count mismatch")
    elif encoding == "ieee-754":
        if not isinstance(record.get("values"), str):
            raise ValueError("invalid telemetry float payload")
        try:
            packed = base64.b64decode(record["values"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid telemetry float payload") from exc
        if len(packed) != non_null_count * 8:
            raise ValueError("telemetry float payload length mismatch")
        non_null = [
            repr(struct.unpack(">d", packed[index : index + 8])[0])
            for index in range(0, len(packed), 8)
        ]
    else:
        non_null = _string_list(
            record.get("values"), "plain values", expected=non_null_count
        )
    if len(non_null) != non_null_count:
        raise ValueError("telemetry non-null value count mismatch")
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

    def decode(
        self,
        encoded: EncodedData,
        *,
        max_output_size: int | None = None,
        expected_output_size: int | None = None,
    ) -> bytes:
        if encoded.metadata.get("mode") == "exact":
            if max_output_size is not None and len(encoded.data) > max_output_size:
                raise ValueError("telemetry output exceeds safety limit")
            if expected_output_size is not None and len(encoded.data) != expected_output_size:
                raise ValueError("telemetry output size mismatch")
            return encoded.data
        if not encoded.data.startswith(MAGIC):
            raise ValueError("invalid telemetry transformation")
        try:
            value = json.loads(encoded.data[len(MAGIC) :].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("invalid telemetry transformation JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("invalid telemetry transformation root")
        row_count = _integer(value.get("row_count"), "row count")
        if row_count > MAX_ROWS:
            raise ValueError("telemetry row count exceeds safety limit")
        header = _string_list(value.get("header"), "header")
        columns = value.get("columns")
        if (
            not isinstance(columns, list)
            or len(columns) != len(header)
            or len(columns) > MAX_COLUMNS
        ):
            raise ValueError("invalid telemetry columns")
        if row_count * max(1, len(columns)) > MAX_CELLS:
            raise ValueError("telemetry cell count exceeds safety limit")
        if expected_output_size is not None:
            if expected_output_size < 0:
                raise ValueError("invalid expected telemetry output size")
            if row_count > expected_output_size + 1:
                raise ValueError("telemetry row count cannot fit declared output")
            if max_output_size is not None and expected_output_size > max_output_size:
                raise ValueError("telemetry output exceeds safety limit")
        decoded_columns = [_decode_values(record, row_count) for record in columns]
        if [record.get("name") for record in columns] != header:
            raise ValueError("telemetry column names do not match header")
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(header)
        for row_index in range(row_count):
            writer.writerow([column[row_index] for column in decoded_columns])
        result = output.getvalue().encode("utf-8")
        if max_output_size is not None and len(result) > max_output_size:
            raise ValueError("telemetry output exceeds safety limit")
        if expected_output_size is not None and len(result) != expected_output_size:
            raise ValueError("telemetry output size mismatch")
        return result


TRANSFORMER = TelemetryTransformer()
