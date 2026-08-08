# Changelog

## 0.2.2 - 2026-08-09

- Add Zenodo and Citation File Format metadata for archival citation.
- Refresh release references for the 0.2.2 publication.

## 0.2.1 - 2026-07-29

- Add a read-only `lowpack compatibility` probe plus an authenticated, atomic
  `lowpack migrate` command and typed Python APIs for format 1.0 archives
  created by LowPack 0.1.x.
- Preserve legacy chunk payloads while converting embedded dictionaries,
  selection goals, and codec decisions into strict format 1.1 manifest schema
  2.0 records.
- Fully reconstruct and verify migrated archives before publishing the output,
  leaving the source untouched and requiring explicit destination overwrite.
- Separate end-user wheel installation from contributor setup, with a
  cross-platform getting-started guide, checksum guidance, upgrade steps, and
  compatibility reference.

## 0.2.0 - 2026-07-29

- Harden input collection against duplicate names and identities, symlink
  cycles, source mutation, and output-inside-input recursion.
- Stream ordinary verification and extraction with conservative defaults.
- Introduce a separately versioned strict manifest schema, centralized
  compression dictionaries, and preferred-versus-actual codec explanations.
- Validate telemetry transform structures and resource relationships before
  reconstruction.
- Make permission restoration opt-in and mask archived modes to ordinary rwx
  bits.
- Replace speed-claiming goal names with deterministic policy names and split
  benchmarks into payload, container, and full-archive comparisons.
- Add hostile-input regression coverage and a bounded fuzzing workflow.
- Pin release-build timestamps so both wheels and source archives reproduce
  byte-for-byte.
- Move the CI action runtime to the current Node 24-based v7 majors.

## 0.1.2 - 2026-07-29

- Rewrite the public documentation in a concise, personal voice that explains
  why LowPack works the way it does.
- Add clearer narrative guidance around profiles, determinism, security,
  benchmarking, and the binary format.
- Correct the alpha limitations page: bounded deterministic source dictionary
  training is active and authenticated in the manifest.

## 0.1.1 - 2026-07-29

- Prevent duplicate CI matrices when release tags are pushed.
- Add manual CI dispatch, least-privilege workflow permissions, and concurrency control.
- Add package project URLs, discoverability keywords, and live repository badges.
- Support version-scoped release checksum generation.

## 0.1.0 - 2026-07-29

- Initial alpha `.lpk` format, CLI, Python API, profiles, safe extraction,
  deterministic manifests, deduplication, verification, and benchmarks.
