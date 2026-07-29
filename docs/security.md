# Extraction security model

The question I use here is, “What if every field in this archive is trying to
mislead the extractor?” Before extraction LowPack validates canonical JSON,
object-count and aggregate-reference limits, normalized relative paths,
duplicate paths and input identities, case-fold collisions, known chunk
references, exact hash syntax, chunk ordering and non-overlap, transform
schemas, declared-size relationships, and footer/manifest integrity.
Absolute Unix, drive, UNC, traversal, NUL, and empty-component paths are
rejected. Existing parent symlinks are rejected. Symlinks and hard links are
not restored.

Ordinary payloads are decompressed and written one bounded chunk at a time.
Each chunk is size-checked and SHA-256 checked; the encoded and reconstructed
file hashes are checked before a sibling temporary file is fsynced and
atomically moved. Canonical telemetry has separate row, column, cell, bitmap,
index, run-length, encoded-size, and reconstructed-size validation.
I made existing files require `--overwrite`; temporary files are removed on
failure, and a disk-space preflight is attempted.

Default limits are a 64 MiB manifest, two million JSON values, 100,000 files,
one million aggregate chunk references, 64 MiB chunks, and 8 GiB total output.
Canonical telemetry is capped at 64 MiB and one million rows, with a
ten-million-cell ceiling. Override general extraction limits explicitly with
`--max-size`, `--max-files`, and `--max-chunks`.

Oh! One trust boundary still belongs to the operating system: do not extract
into a directory that another untrusted user or process can modify
concurrently. Existing parents are checked again before replacement, but
portable Python path APIs cannot make the complete parent walk race-free on
every supported platform. For genuinely hostile input, use a newly created,
privately owned output directory plus OS quotas or sandboxing.

Archived permissions are ignored by default. `--restore-permissions` opts in
to ordinary user/group/other rwx bits; setuid, setgid, and sticky bits are
masked during packing and extraction.

Migration uses the same trust boundary. `lowpack migrate` first authenticates
the complete format 1.0 body, converts its manifest into the strict current
schema, rejects unsafe paths and inconsistent relationships, and writes to a
sibling temporary file. It then performs a full decompression and
reconstruction check before atomic replacement. The source archive is never
modified, and an existing destination still requires `--overwrite`.
