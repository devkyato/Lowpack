# Profiles

General changes no bytes. Its magic-byte detector conservatively recognizes
PNG, JPEG, GIF, WebP/RIFF, MP3, MP4, PDF, ZIP, gzip, 7z, RAR, and LowPack.
It selects store when sample compression has no meaningful benefit.

Source changes no bytes and categorizes common source/document extensions.
Its defaults are `.git`, `.venv`, `venv`, `__pycache__`, `.mypy_cache`,
`.pytest_cache`, `.ruff_cache`, `node_modules`, `dist`, and `build`. These are
path-component matches. `--include-all` disables defaults; user `--exclude`
patterns and `--include` filters remain explicit. Exclusions are output and
stored. Related text files are grouped by language. With at least eight useful
samples, deterministic Zstandard dictionaries are trained from at most 64 KiB
per file and 1 MiB per group, capped at 8 KiB per dictionary. Dictionary bytes
needed for decoding are authenticated inside the canonical manifest.

Telemetry supports UTF-8 CSV. Exact mode stores original bytes after detection.
Canonical mode uses the transformation documented in telemetry-format.md.
