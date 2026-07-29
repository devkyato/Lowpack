# Determinism

I wanted “deterministic” to mean something testable, not just “usually the
same.” LowPack omits creation time, absolute paths, owner IDs, and unstable
filesystem metadata. It normalizes separators, sorts input paths and manifest
keys, fixes JSON syntax, uses fixed codec settings, and writes chunks at first
occurrence in sorted file order. Permissions are omitted unless requested.

Oh! There is an important boundary to that promise. Byte identity also
requires identical content and normalized archive root names, metadata policy,
LowPack and format version, codec implementation versions and settings,
profile and transform options, chunk size, and platform-independent metadata
choices. Codec libraries may produce different bytes between versions. Check
two builds directly with `lowpack verify-deterministic A B`.

The policy names are intentionally literal. `prefer-store`,
`prefer-zstd-low`, and `avoid-zlib` use stable byte penalties and fixed
levels; they do not feed noisy wall-clock samples into the manifest. Candidate
timings remain diagnostic measurements, while the archived choice stays
reproducible.
