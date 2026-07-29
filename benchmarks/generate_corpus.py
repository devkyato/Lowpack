"""Generate the deterministic, offline LowPack benchmark corpus."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 1729


def generate(root: Path) -> None:
    rng = random.Random(SEED)
    root.mkdir(parents=True, exist_ok=True)
    (root / "source").mkdir(exist_ok=True)
    for index in range(20):
        (root / "source" / f"module_{index:02d}.py").write_text(
            '"""Generated benchmark module."""\n\n'
            f"CONSTANT = {index}\n\n"
            "def calculate(value: int) -> int:\n"
            "    return value * CONSTANT\n",
            encoding="utf-8",
        )
    (root / "source" / "sensor.ino").write_text(
        "void setup() { Serial.begin(9600); }\n"
        "void loop() { Serial.println(analogRead(A0)); delay(100); }\n",
        encoding="utf-8",
    )
    (root / "records.json").write_text(
        json.dumps(
            [
                {"id": index, "name": f"sensor-{index % 8}", "value": index // 4}
                for index in range(5000)
            ],
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        ("# Generated corpus\n\nRepeated documentation paragraph for compression.\n\n" * 500),
        encoding="utf-8",
    )
    repeated = root / "repeated"
    repeated.mkdir(exist_ok=True)
    duplicate = b"identical generated file\n" * 100
    for index in range(100):
        (repeated / f"small-{index:03d}.txt").write_bytes(
            duplicate if index < 50 else f"small file {index % 10}\n".encode()
        )
    with (root / "telemetry.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["timestamp", "temperature", "pressure", "count", "ok", "status"])
        current = datetime(2026, 1, 1, tzinfo=timezone.utc)
        temperature = 20.0
        for index in range(10000):
            temperature += rng.choice((-0.01, 0.0, 0.01))
            writer.writerow(
                [
                    current.isoformat(),
                    f"{temperature:.2f}",
                    1000 + index // 100,
                    index,
                    "true" if index % 97 else "false",
                    ("ok", "warn", "offline")[index % 101 == 0],
                ]
            )
            current += timedelta(seconds=1)
    (root / "noise.bin").write_bytes(rng.randbytes(512 * 1024))
    compressed_source = rng.randbytes(256 * 1024)
    (root / "already-compressed.gz").write_bytes(gzip.compress(compressed_source, mtime=0))
    (root / "empty").write_bytes(b"")
    (root / "tiny").write_bytes(b"x")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("benchmarks/corpus"))
    args = parser.parse_args()
    generate(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
