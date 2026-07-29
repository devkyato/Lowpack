from __future__ import annotations

import hashlib
from pathlib import Path


def main() -> None:
    rows = []
    for path in sorted(Path("dist").iterdir()):
        if path.is_file() and path.name != "SHA256SUMS":
            rows.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    Path("dist/SHA256SUMS").write_text("\n".join(rows) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
