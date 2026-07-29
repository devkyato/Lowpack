# Extraction security model

The question I use here is, “What if every field in this archive is trying to
mislead the extractor?” Before extraction LowPack validates canonical JSON,
object-count and expansion
limits, normalized relative paths, duplicate paths, case-fold collisions,
known chunk references, declared sizes, and footer/manifest integrity.
Absolute Unix, drive, UNC, traversal, NUL, and empty-component paths are
rejected. Existing parent symlinks are rejected. Symlinks and hard links are
not restored.

Each payload is decompressed with an expected size, SHA-256 checked, reversed,
file-hash checked, fsynced to a sibling temporary file, and atomically moved.
I made existing files require `--overwrite`; temporary files are removed on
failure, and a disk-space preflight is attempted.

Default limits are a 64 MiB manifest, 100,000 files, one million unique or
per-file chunk references, and 100 GiB total output. Override extraction
limits explicitly with `--max-size`, `--max-files`, and `--max-chunks`. These
are upper safety bounds, not resource guarantees. Oh! For genuinely hostile
input, I would still use a fresh output directory plus OS-level quotas or
sandboxing. An application limit is one layer, not the whole security model.
