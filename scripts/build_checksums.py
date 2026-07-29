from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--version",
        help="include only lowpack artifacts for this version, such as 0.1.1",
    )
    args = parser.parse_args()
    rows = []
    for path in sorted(Path("dist").iterdir()):
        matches_version = args.version is None or path.name.startswith(
            f"lowpack-{args.version}"
        )
        if path.is_file() and path.name != "SHA256SUMS" and matches_version:
            rows.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    if not rows:
        raise SystemExit("no matching distribution artifacts found")
    Path("dist/SHA256SUMS").write_text("\n".join(rows) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
