from __future__ import annotations

import os
import subprocess
import sys

REPRODUCIBLE_EPOCH = "315532800"  # 1980-01-01, also valid for ZIP timestamps.


def main() -> None:
    environment = os.environ.copy()
    environment.setdefault("SOURCE_DATE_EPOCH", REPRODUCIBLE_EPOCH)
    subprocess.run([sys.executable, "-m", "pytest"], check=True)
    subprocess.run([sys.executable, "-m", "ruff", "check", "."], check=True)
    subprocess.run([sys.executable, "-m", "mypy", "src/lowpack"], check=True)
    subprocess.run([sys.executable, "-m", "build"], check=True, env=environment)


if __name__ == "__main__":
    main()
