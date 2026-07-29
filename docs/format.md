# `.lpk` binary format, version 1.0

All integers are unsigned, big-endian. Offsets are absolute from byte zero.
Hashes are SHA-256 over the named bytes. Reserved values must be zero.

## File header (16 bytes)

| Offset | Size | Field |
|---:|---:|---|
| 0 | 8 | magic `LOWPACK\0` |
| 8 | 2 | major version (`1`) |
| 10 | 2 | minor version (`0`) |
| 12 | 4 | flags (`0`) |

Readers reject unknown major versions and nonzero flags.

## Chunk record

Each unique raw chunk appears once. Files reference it by its raw SHA-256.

| Offset | Size | Field |
|---:|---:|---|
| +0 | 4 | magic `LPCK` |
| +4 | 1 | codec: 0 store, 1 zlib, 2 zstd |
| +5 | 3 | reserved zero |
| +8 | 8 | raw byte length |
| +16 | 8 | packed byte length |
| +24 | 32 | SHA-256 of raw bytes |
| +56 | packed length | codec payload |

## Canonical manifest

The uncompressed manifest immediately follows chunk records. It is UTF-8 JSON
with sorted keys, compact separators, no NaN/Infinity, explicit integers, and
normalized POSIX relative paths. Re-encoding must reproduce identical bytes.
Top-level data records versions, codec versions, profile/goal, exclusions,
directories, file records, and the chunk index. Unknown optional object keys
may be preserved by tools that rewrite a manifest.

A zero-byte file has an empty chunk list and SHA-256
`e3b0c44298fc1c149afbf4c8996fb924...`.

## Footer (84 bytes)

| Offset | Size | Field |
|---:|---:|---|
| +0 | 8 | magic `LPKFOOT\0` |
| +8 | 2 | major version |
| +10 | 2 | minor version |
| +12 | 8 | manifest offset |
| +20 | 8 | manifest length |
| +28 | 32 | manifest SHA-256 |
| +60 | 32 | body SHA-256 |

The body hash covers the header, all chunk records, and the manifest, but not
the footer. A reader seeks 84 bytes from EOF, validates bounds and hashes, and
can then list files without decompressing payloads. Chunk offsets allow
single-file extraction. A short footer, impossible bounds, mismatched hash,
or missing magic identifies truncation/corruption.
