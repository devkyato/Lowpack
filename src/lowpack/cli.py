"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import zstandard

from . import __version__
from .archive import _read_manifest, inspect_archive, pack, unpack, verify_archive
from .benchmark import benchmark, markdown_report
from .codecs import CODECS
from .explain import explain_manifest
from .format import FormatError


def _size(value: str) -> int:
    units = {"k": 1024, "m": 1024**2, "g": 1024**3}
    lowered = value.lower().strip()
    if lowered[-1:] in units:
        return int(lowered[:-1]) * units[lowered[-1]]
    return int(lowered)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lowpack", description=__doc__)
    parser.add_argument("--version", action="version", version=f"lowpack {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    packing = subparsers.add_parser("pack", help="create a deterministic .lpk archive")
    packing.add_argument("inputs", nargs="+")
    packing.add_argument("-o", "--output", required=True)
    packing.add_argument("--profile", choices=["general", "source", "telemetry"], default="general")
    packing.add_argument(
        "--goal",
        choices=["balanced", "smallest", "fastest", "fastest-decode", "low-memory"],
        default="balanced",
    )
    packing.add_argument("--chunk-size", type=_size, default=1024 * 1024)
    packing.add_argument("--codec", choices=sorted(CODECS))
    packing.add_argument("--level", type=int)
    packing.add_argument("--exclude", action="append", default=[])
    packing.add_argument("--include", action="append", default=[])
    packing.add_argument("--include-all", action="store_true")
    packing.add_argument("--follow-symlinks", action="store_true")
    packing.add_argument("--store-permissions", action="store_true")
    packing.add_argument("--overwrite", action="store_true")
    packing.add_argument("--telemetry-mode", choices=["exact", "canonical"], default="exact")
    packing.add_argument("--time-field")
    _add_json(packing)

    unpacking = subparsers.add_parser("unpack", help="extract an archive safely")
    unpacking.add_argument("archive")
    unpacking.add_argument("-o", "--output", default=".")
    unpacking.add_argument("--overwrite", action="store_true")
    unpacking.add_argument("--verify", action=argparse.BooleanOptionalAction, default=True)
    unpacking.add_argument("--no-permissions", action="store_true")
    unpacking.add_argument("--max-size", type=_size, default=100 * 1024**3)
    unpacking.add_argument("--max-files", type=int, default=100_000)
    unpacking.add_argument("--max-chunks", type=int, default=1_000_000)
    _add_json(unpacking)

    listing = subparsers.add_parser("list", help="list archive entries")
    listing.add_argument("archive")
    _add_json(listing)

    inspecting = subparsers.add_parser("inspect", help="show archive metadata")
    inspecting.add_argument("archive")
    _add_json(inspecting)

    extracting = subparsers.add_parser("extract", help="extract selected paths")
    extracting.add_argument("archive")
    extracting.add_argument("paths", nargs="+")
    extracting.add_argument("-o", "--output", default=".")
    extracting.add_argument("--overwrite", action="store_true")
    extracting.add_argument("--max-size", type=_size, default=100 * 1024**3)
    extracting.add_argument("--max-files", type=int, default=100_000)
    extracting.add_argument("--max-chunks", type=int, default=1_000_000)
    _add_json(extracting)

    verifying = subparsers.add_parser("verify", help="verify archive integrity")
    verifying.add_argument("archive")
    mode = verifying.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true")
    mode.add_argument("--full", action="store_true")
    _add_json(verifying)

    deterministic = subparsers.add_parser(
        "verify-deterministic", help="compare two archives byte-for-byte"
    )
    deterministic.add_argument("first")
    deterministic.add_argument("second")
    _add_json(deterministic)

    explaining = subparsers.add_parser("explain", help="explain stored compression decisions")
    explaining.add_argument("archive")
    _add_json(explaining)

    doctoring = subparsers.add_parser("doctor", help="check the local LowPack environment")
    _add_json(doctoring)

    benchmarking = subparsers.add_parser("benchmark", help="run honest local benchmarks")
    benchmarking.add_argument("inputs", nargs="+")
    benchmarking.add_argument(
        "--profile", choices=["general", "source", "telemetry"], default="general"
    )
    benchmarking.add_argument("--repeats", type=int, default=3)
    benchmarking.add_argument("--json", nargs="?", const="-")
    benchmarking.add_argument("--markdown")
    return parser


def _load_manifest(path: str) -> dict[str, Any]:
    with Path(path).open("rb") as stream:
        manifest, _, _ = _read_manifest(stream)
    return manifest


def _list_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    chunk_use: dict[str, int] = {}
    for item in manifest["files"]:
        for ref in item["chunks"]:
            chunk_use[ref] = chunk_use.get(ref, 0) + 1
    rows: list[dict[str, Any]] = []
    for item in manifest["files"]:
        records = [manifest["chunks"][ref] for ref in item["chunks"]]
        rows.append(
            {
                "path": item["path"],
                "original_size": item["size"],
                "packed_contribution": sum(
                    record["packed_size"] / chunk_use[ref]
                    for ref, record in zip(item["chunks"], records)
                ),
                "codec": item["decision"]["final_codec"],
                "transformation": item["transform"].get("id", "none"),
                "chunk_count": len(item["chunks"]),
                "deduplicated": any(chunk_use[ref] > 1 for ref in item["chunks"]),
                "hash": item["hash"][:12],
            }
        )
    return rows


def _doctor() -> tuple[dict[str, Any], bool]:
    checks: dict[str, Any] = {
        "lowpack_version": __version__,
        "python": platform.python_version(),
        "python_supported": sys.version_info >= (3, 9),
        "zstandard": zstandard.__version__,
        "temporary_directory": tempfile.gettempdir(),
    }
    try:
        sysconf: Any = getattr(os, "sysconf")  # noqa: B009 - optional on Windows
        pages = sysconf("SC_AVPHYS_PAGES")
        page_size = sysconf("SC_PAGE_SIZE")
        checks["available_memory_bytes"] = int(pages) * int(page_size)
    except (AttributeError, OSError, ValueError):
        checks["available_memory_bytes"] = None
    try:
        with tempfile.TemporaryDirectory(prefix="lowpack-doctor-") as temporary:
            path = Path(temporary) / "probe"
            path.write_bytes(b"probe")
            checks["temporary_read_write"] = path.read_bytes() == b"probe"
    except OSError as exc:
        checks["temporary_read_write"] = False
        checks["temporary_error"] = str(exc)
    codec_checks: dict[str, bool] = {}
    for name, codec in CODECS.items():
        data = b"lowpack-codec-self-test" * 64
        packed = codec.compress(data)
        codec_checks[name] = codec.decompress(packed, expected_size=len(data)) == data
    checks["codec_self_tests"] = codec_checks
    with tempfile.TemporaryDirectory(prefix="lowpack-determinism-") as temporary:
        root = Path(temporary)
        source = root / "input.txt"
        source.write_text("determinism\n", encoding="utf-8")
        first, second = root / "a.lpk", root / "b.lpk"
        pack([source], first)
        pack([source], second)
        checks["determinism_self_test"] = first.read_bytes() == second.read_bytes()
    ok = bool(
        checks["python_supported"]
        and checks["temporary_read_write"]
        and all(codec_checks.values())
        and checks["determinism_self_test"]
    )
    return checks, ok


def run(args: argparse.Namespace) -> int:
    command = args.command
    if command == "pack":
        pack_result = pack(
            args.inputs,
            args.output,
            profile=args.profile,
            goal=args.goal,
            chunk_size=args.chunk_size,
            codec=args.codec,
            level=args.level,
            exclude=args.exclude,
            include=args.include,
            include_all=args.include_all,
            follow_symlinks=args.follow_symlinks,
            store_permissions=args.store_permissions,
            overwrite=args.overwrite,
            telemetry_mode=args.telemetry_mode,
            time_field=args.time_field,
        )
        value = asdict(pack_result)
        print(
            _json(value)
            if args.json
            else f"Packed {pack_result.file_count} files to {pack_result.archive}"
        )
        if pack_result.excluded and not args.json:
            print("Excluded:")
            for path in pack_result.excluded:
                print(f"  {path}")
        return 0
    if command == "unpack":
        paths = unpack(
            args.archive,
            output=args.output,
            overwrite=args.overwrite,
            verify=args.verify,
            restore_permissions=not args.no_permissions,
            max_extract_size=args.max_size,
            max_files=args.max_files,
            max_chunks=args.max_chunks,
        )
        print(
            _json([str(path) for path in paths]) if args.json else f"Extracted {len(paths)} files"
        )
        return 0
    if command == "extract":
        paths = unpack(
            args.archive,
            output=args.output,
            paths=args.paths,
            overwrite=args.overwrite,
            max_extract_size=args.max_size,
            max_files=args.max_files,
            max_chunks=args.max_chunks,
        )
        print(
            _json([str(path) for path in paths]) if args.json else f"Extracted {len(paths)} files"
        )
        return 0
    if command == "list":
        rows = _list_rows(_load_manifest(args.archive))
        if args.json:
            print(_json(rows))
        else:
            print("PATH\tSIZE\tPACKED\tCODEC\tTRANSFORM\tCHUNKS\tDEDUP\tHASH")
            for row in rows:
                print(
                    f"{row['path']}\t{row['original_size']}\t{row['packed_contribution']:.0f}\t"
                    f"{row['codec']}\t{row['transformation']}\t{row['chunk_count']}\t"
                    f"{row['deduplicated']}\t{row['hash']}"
                )
        return 0
    if command == "inspect":
        info = inspect_archive(args.archive)
        print(
            _json(asdict(info))
            if args.json
            else "\n".join(f"{k}: {v}" for k, v in asdict(info).items())
        )
        return 0
    if command == "verify":
        verification_result = verify_archive(args.archive, full=not args.quick)
        print(
            _json(asdict(verification_result))
            if args.json
            else (
                "OK"
                if verification_result.valid
                else "\n".join(verification_result.errors)
            )
        )
        return 0 if verification_result.valid else 2
    if command == "verify-deterministic":
        same = Path(args.first).read_bytes() == Path(args.second).read_bytes()
        value = {"deterministic": same, "first": args.first, "second": args.second}
        print(
            _json(value) if args.json else ("Archives are identical" if same else "Archives differ")
        )
        return 0 if same else 2
    if command == "explain":
        manifest = _load_manifest(args.archive)
        if args.json:
            print(_json([{"path": item["path"], **item["decision"]} for item in manifest["files"]]))
        else:
            print(explain_manifest(manifest))
        return 0
    if command == "doctor":
        checks, ok = _doctor()
        print(
            _json(checks)
            if args.json
            else "\n".join(f"{key}: {value}" for key, value in checks.items())
        )
        return 0 if ok else 2
    if command == "benchmark":
        benchmark_result = benchmark(
            args.inputs, profile=args.profile, repeats=args.repeats
        )
        if args.markdown:
            Path(args.markdown).write_text(
                markdown_report(benchmark_result), encoding="utf-8"
            )
        if args.json and args.json != "-":
            Path(args.json).write_text(
                _json(benchmark_result) + "\n", encoding="utf-8"
            )
        elif args.json == "-":
            print(_json(benchmark_result))
        else:
            print(markdown_report(benchmark_result))
        return 0
    raise AssertionError(command)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(build_parser().parse_args(argv))
    except (OSError, ValueError, FormatError) as exc:
        print(f"lowpack: error: {exc}", file=sys.stderr)
        return 2
