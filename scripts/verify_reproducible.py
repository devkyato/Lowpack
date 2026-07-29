from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args()
    if args.first.read_bytes() != args.second.read_bytes():
        raise SystemExit("archives differ")
    print("archives are byte-identical")


if __name__ == "__main__":
    main()
