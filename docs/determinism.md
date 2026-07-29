# Determinism

LowPack omits creation time, absolute paths, owner IDs, and unstable filesystem
metadata. It normalizes separators, sorts input paths and manifest keys, fixes
JSON syntax, uses fixed codec settings, and writes chunks at first occurrence
in sorted file order. Permissions are omitted unless requested.

Byte identity additionally requires identical content and normalized archive
root names, metadata policy, LowPack/format version, codec implementation
versions and settings, profile and transform options, chunk size, and
platform-independent metadata choices. Codec libraries may produce different
bytes between versions. Use `lowpack verify-deterministic A B`.
