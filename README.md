# LowPack

![LowPack — local-first, application-aware lossless packing](docs/assets/github-cover.png)

[![CI](https://github.com/devkyato/Lowpack/actions/workflows/ci.yml/badge.svg)](https://github.com/devkyato/Lowpack/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/devkyato/Lowpack?include_prereleases)](https://github.com/devkyato/Lowpack/releases)
[![Python 3.9–3.14](https://img.shields.io/badge/python-3.9%E2%80%933.14-blue)](https://github.com/devkyato/Lowpack/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

LowPack is a local-first, application-aware lossless packer that prepares data
for how it is stored and used, then applies proven compression codecs.

> **Alpha warning:** the `.lpk` format is experimental. Archives from alpha
> releases may require migration. Do not rely on LowPack as the only copy of
> important data.

LowPack does **not** universally outperform Zstandard, gzip, ZIP, Brotli, LZ4,
or other compressors. Results depend on the data, selected profile, goal,
codec versions, and machine. Version 0.1 uses proven store, zlib, and Zstandard
codecs; LowPack's contribution is deterministic packaging, safe indexing,
deduplication, selection, and optional reversible preparation.

## Install

Python 3.9 through 3.14 is supported.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
lowpack --version
```

LowPack runs entirely on the local machine. It needs no account, website,
cloud service, daemon, database, telemetry, or background network access.

## Five-minute demonstration

```powershell
lowpack pack project -o project.lpk --profile source
lowpack list project.lpk
lowpack inspect project.lpk
lowpack verify project.lpk --full
lowpack explain project.lpk
lowpack unpack project.lpk -o restored
```

Selective extraction is `lowpack extract project.lpk project/src -o selected`.
Use `--overwrite` deliberately. `lowpack doctor` checks the environment.

## Profiles

- `general` performs content-defined codec sampling without changing content,
  detects common compressed formats by magic bytes, chunks files, and
  deduplicates identical chunks. It never silently excludes ordinary files.
- `source` keeps bytes unchanged, records a language/category manifest, and
  excludes a documented set of build/cache paths unless `--include-all` is
  used. Every exclusion is printed and stored.
- `telemetry` targets CSV. `--telemetry-mode exact` (the default) preserves
  byte-for-byte content. `canonical` separates columns, records inferred types
  and reversible encodings, and reconstructs deterministic RFC-style CSV; it
  is semantically rather than byte equivalent.

See [profile details](docs/profiles.md) and
[telemetry details](docs/telemetry-format.md).

## Determinism

Creation time and unstable filesystem metadata are omitted, paths and
manifest keys are sorted, JSON is canonical, and archive order is stable.
Identical bytes require identical inputs, normalized paths, metadata policy,
LowPack and codec versions/settings, profile/transform settings, chunk size,
and platform-independent options.

```powershell
lowpack pack source -o first.lpk
lowpack pack source -o second.lpk
lowpack verify-deterministic first.lpk second.lpk
```

See [determinism guarantees](docs/determinism.md).

## Security

Extraction rejects traversal, absolute/drive/UNC/NUL paths, duplicate and
case-colliding destinations, unknown codecs, invalid sizes, unsafe parent
symlinks, and archives exceeding conservative count/size limits. Files are
verified and written through sibling temporary files before atomic
replacement. Symlinks are neither packed by default nor restored in 0.1.

Untrusted archives should always be extracted with limits and full
verification. Review [the security model](docs/security.md) and report
vulnerabilities according to [SECURITY.md](SECURITY.md).

## Benchmarking

`lowpack benchmark corpus --json results.json --markdown benchmark.md` uses a
warm-up, repeated timed runs, monotonic clocks, environment metadata, and does
not tune results to favor LowPack. Generate the fixed-seed local corpus with
`python benchmarks/generate_corpus.py`. No data is downloaded.

The table below is populated only by a real release-check run:

<!-- BENCHMARK_START -->
# LowPack benchmark

Python 3.14.4 on Windows-11-10.0.26200-SP0 (AMD64); 1 warm-up, 3 measured runs. Fixed-seed generated corpus.

| Method | Original | Packed | Ratio | Encode ms | Decode ms |
|---|---:|---:|---:|---:|---:|
| store | 1660822 | 1660822 | 1.000 | 0.002 | 0.001 |
| gzip-6 | 1660822 | 871185 | 0.525 | 26.502 | 2.039 |
| zstd-1 | 1660822 | 839013 | 0.505 | 1.646 | 1.054 |
| zstd-3 | 1660822 | 840484 | 0.506 | 2.255 | 1.091 |
| zstd-9 | 1660822 | 835586 | 0.503 | 12.260 | 1.020 |
| lowpack-general | 1660822 | 943226 | 0.568 | 184.314 | 525.444 |
| lowpack-source | 1660822 | 948173 | 0.571 | 199.957 | 519.541 |
<!-- BENCHMARK_END -->

See [benchmark methodology](docs/benchmarking.md). Measurements apply only to
the identified corpus and environment.

## Python API

```python
from lowpack import inspect_archive, pack, unpack, verify_archive

pack(["project"], "project.lpk", profile="source", goal="balanced")
info = inspect_archive("project.lpk")
assert verify_archive("project.lpk", full=True).valid
unpack("project.lpk", output="restored")
```

Functions return typed frozen result models.

## Limitations

The format is experimental; no forward-compatibility promise exists before
1.0. Source dictionaries use bounded deterministic samples and only apply to
Zstandard chunks. Telemetry canonical mode supports UTF-8 CSV and stores exact
IEEE-754 values (original decimal spelling is preserved only by exact mode).
Extraction limits are currently library constants. File payload assembly
during extraction is bounded by declared archive limits but not yet streamed.
See [all limitations](docs/limitations.md).

## Contributing and license

Read [CONTRIBUTING.md](CONTRIBUTING.md). LowPack is released under the
[MIT License](LICENSE).
