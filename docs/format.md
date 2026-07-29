# `.lpk` binary format, version 1.1

This page is the precise reference. I chose a small framing format that can be
read from both ends: the front establishes identity and version, while the
footer points straight to the manifest. That is what lets LowPack list or
extract one file without unpacking everything first.

All integers are unsigned, big-endian. Offsets are absolute from byte zero.
Hashes are SHA-256 over the named bytes. Reserved values must be zero.

## File header (16 bytes)

| Offset | Size | Field |
|---:|---:|---|
| 0 | 8 | magic `LOWPACK\0` |
| 8 | 2 | major version (`1`) |
| 10 | 2 | minor version (`1`) |
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

I used canonical JSON here because it is inspectable, deterministic, and not
executable serialization. The uncompressed manifest immediately follows chunk
records. It is UTF-8 JSON
with sorted keys, compact separators, no NaN/Infinity, explicit integers, and
normalized POSIX relative paths. Re-encoding must reproduce identical bytes.
Top-level data records binary and manifest-schema versions, codec versions,
profile/policy, exclusions, directories, dictionaries, file records, and the
chunk index. Version 1.1 writes manifest schema 2.0. Readers validate exact
field types and hash syntax; aggregate references; encoded/source/output size
relationships; chunk ordering, non-overlap, and payload boundaries; transform,
permission, codec-decision, and dictionary relationships; and a total JSON
object ceiling. Canonical JSON is the wire representation, not a substitute
for this schema.

Compression dictionaries live in the top-level `dictionaries` map, keyed by
their SHA-256. A Zstandard chunk may reference one `dictionary_id`; other
codecs may not. Source-category records reference the same ID, so dictionary
bytes appear exactly once.

Every file records a preferred codec policy plus one `chunk_decisions` entry
per reference. Those entries name the actual stored codec/dictionary and say
whether content-addressed deduplication reused an earlier representation.

Format 1.0, written by LowPack 0.1.x, used embedded per-chunk dictionary bytes
and a less explicit codec-decision record. `lowpack migrate` is the supported
bridge to format 1.1 and manifest schema 2.0. The
[compatibility guide](compatibility.md) describes exactly what is preserved
and checked.

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
single-file extraction. In other words, a short footer, impossible bounds,
mismatched hash, overlapping record, inconsistent relationship, or missing
magic is a clean corruption signal rather than a guess.
