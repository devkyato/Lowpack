# Profiles

Profiles are where LowPack answers “what kind of data am I preparing?” without
pretending the final codec is new. I kept the choices small enough to explain.

## General

General changes no bytes. Its magic-byte detector conservatively recognizes
PNG, JPEG, GIF, WebP/RIFF, MP3, MP4, PDF, ZIP, gzip, 7z, RAR, and LowPack.
It selects store when sample compression has no meaningful benefit. This is
the profile I expect people to reach for first.

## Source

I thought about project directories as more than one large byte stream. Source
still changes no bytes, but it categorizes common source/document extensions.
Its defaults are `.git`, `.venv`, `venv`, `__pycache__`, `.mypy_cache`,
`.pytest_cache`, `.ruff_cache`, `node_modules`, `dist`, and `build`. These are
path-component matches. `--include-all` disables defaults; user `--exclude`
patterns and `--include` filters remain explicit. Exclusions are output and
stored. Related text files are grouped by language. With at least eight useful
samples, deterministic Zstandard dictionaries are trained from at most 64 KiB
per file and 1 MiB per group, capped at 8 KiB per dictionary. Each dictionary
is stored once in the canonical manifest and chunks reference its SHA-256 ID.
The source-category table points to that same authenticated record.

## Telemetry

Telemetry supports UTF-8 CSV. Exact mode stores original bytes after
detection. Canonical mode uses the transformation documented in
[telemetry-format.md](telemetry-format.md). If byte-for-byte reconstruction is
the priority, exact mode is the simple answer.
