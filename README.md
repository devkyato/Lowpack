# LowPack

![LowPack — local-first, application-aware lossless packing](docs/assets/github-cover.png)

[![CI](https://github.com/devkyato/Lowpack/actions/workflows/ci.yml/badge.svg)](https://github.com/devkyato/Lowpack/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/devkyato/Lowpack?include_prereleases)](https://github.com/devkyato/Lowpack/releases)
[![Python 3.9–3.14](https://img.shields.io/badge/python-3.9%E2%80%933.14-blue)](https://github.com/devkyato/Lowpack/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

I built LowPack around one fairly simple thought: compression should understand
what it is packing before it reaches for a codec. LowPack prepares data for how
it will actually be stored and used, then hands it to proven lossless codecs.
It is a terminal tool and Python library that stays completely on your laptop.

> **A quick, honest alpha note:** the `.lpk` format is still experimental.
> Archives from alpha releases may need migration, so please do not make
> LowPack the only copy of important data.

Oh! One point I care about being clear on: LowPack does **not** universally
outperform Zstandard, gzip, ZIP, Brotli, LZ4, or anything else. Results depend
on the data, goal, codec versions, and machine. Version 0.1 uses store, zlib,
and Zstandard underneath. The LowPack part is deterministic packaging, safe
indexing, deduplication, explainable selection, and reversible preparation.

## Install

Python 3.9 through 3.14 is supported. For development, I usually start with a
fresh environment so the checks describe the project instead of my machine:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
lowpack --version
```

That is it. LowPack needs no account, website, cloud service, daemon, database,
analytics, or background network access.

## Five-minute demonstration

Here is the shortest useful tour I use when I want to see the full flow:

```powershell
lowpack pack project -o project.lpk --profile source
lowpack list project.lpk
lowpack inspect project.lpk
lowpack verify project.lpk --full
lowpack explain project.lpk
lowpack unpack project.lpk -o restored
```

Selective extraction is `lowpack extract project.lpk project/src -o selected`.
I made `--overwrite` explicit on purpose, and `lowpack doctor` is there when
you want a quick check of the local environment.

## How I think about profiles

- `general` is the honest default. It samples codecs without changing content,
  detects common compressed formats by magic bytes, chunks files, and
  deduplicates identical chunks. It never silently excludes ordinary files.
- `source` is what I use for project trees. It keeps bytes unchanged, records
  a language/category manifest, and
  excludes a documented set of build/cache paths unless `--include-all` is
  used. Every exclusion is printed and stored.
- `telemetry` is the more structured path for CSV. `--telemetry-mode exact`
  (the default) preserves
  byte-for-byte content. `canonical` separates columns, records inferred types
  and reversible encodings, and reconstructs deterministic RFC-style CSV; it
  is semantically rather than byte equivalent.

See [profile details](docs/profiles.md) and
[telemetry details](docs/telemetry-format.md).

## Determinism

I thought about the “same input, same archive” point early because reproducible
output is much easier to trust and test. LowPack omits creation time and
unstable filesystem metadata, sorts paths and manifest keys, uses canonical
JSON, and writes in a stable order. Identical bytes still require identical
inputs, normalized paths, metadata policy, LowPack and codec versions/settings,
profile/transform settings, chunk size, and platform-independent options.

```powershell
lowpack pack source -o first.lpk
lowpack pack source -o second.lpk
lowpack verify-deterministic first.lpk second.lpk
```

See [determinism guarantees](docs/determinism.md).

## Security

Archive extraction is the part I refuse to treat casually. LowPack rejects
traversal, absolute/drive/UNC/NUL paths, duplicate and case-colliding
destinations, unknown codecs, invalid sizes, unsafe parent symlinks, and
archives over conservative limits. It verifies files through sibling
temporary files before atomic replacement. Symlinks are neither packed by
default nor restored in 0.1.

Untrusted archives should always be extracted with limits and full
verification. Review [the security model](docs/security.md) and report
vulnerabilities according to [SECURITY.md](SECURITY.md).

## Benchmarking

I wanted the benchmark command to be useful even when LowPack loses. It uses a
warm-up, repeated monotonic-clock runs, and environment metadata; it does not
tune results to favor LowPack. Generate the fixed-seed local corpus with
`python benchmarks/generate_corpus.py`, then run
`lowpack benchmark corpus --json results.json --markdown benchmark.md`.
Nothing is downloaded.

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

This is where I would rather be specific than sound finished too early. The
format has no pre-1.0 forward-compatibility promise. Source dictionaries use
bounded deterministic samples and only apply to Zstandard chunks. Telemetry
canonical mode stores exact IEEE-754 values, but only exact mode preserves the
original decimal spelling. Transformed extraction is bounded by declared
limits but not yet streamed. See [all limitations](docs/limitations.md).

## Contributing and license

If the idea is useful to you, I would genuinely like the project to be easy to
question and improve. Start with [CONTRIBUTING.md](CONTRIBUTING.md). LowPack is
released under the [MIT License](LICENSE).
