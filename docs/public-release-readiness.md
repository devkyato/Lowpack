# LowPack public release readiness

This document defines how LowPack can become easier to evaluate, safer to operate, and more discoverable without pretending that a private alpha archive format is universally better than established tools.

## Positioning

LowPack should be presented as deterministic, local-first, application-aware lossless packaging with deduplication, explainable codec decisions, strict verification, and reversible telemetry transforms. It should be compared honestly with ZIP, tar plus zstd, content-addressed stores, and backup tools.

## Release blockers

- Add optional whole-tree staged extraction so a failed archive does not leave a partially populated destination.
- Fsync the destination parent directory after atomic archive publication and staged extraction rename.
- Complete bounded streaming or bounded-spool decoding for transformed payloads.
- Expand continuous fuzzing across header, footer, chunk framing, canonical JSON, paths, decompression limits, and transforms.
- Publish benchmark methodology and representative workloads where LowPack provides measurable value.

## Usability improvements

- Add `lowpack init` to generate a project policy file with safe defaults.
- Add `lowpack doctor` for archive structure, codec availability, destination safety, disk space, case collisions, and filesystem capabilities.
- Add `lowpack compare` to compare archive size, deduplication, speed, and reproducibility against ZIP and tar plus zstd on the same input.
- Add `lowpack plan` as a dry-run that reports files, identities, collisions, transforms, estimated memory, and output recursion before writing.
- Add include/exclude profiles, reproducible manifests, JSON output, and progress reporting for large archives.
- Add an explicit private-output-directory check and warnings for shared hostile directories.

## Documentation site

Publish versioned guides for quickstart, format anatomy, threat model, deterministic builds, extraction safety, telemetry transforms, migration, benchmarking, recovery, corruption diagnosis, and format compatibility. Include examples for source snapshots, telemetry sessions, firmware artifacts, and classroom datasets.

## Discoverability

Expand accurate search terms to include `deterministic archive`, `content deduplication`, `lossless telemetry compression`, `local backup format`, `reproducible packaging`, `zstandard archive`, and `verified extraction`. Add repository topics, Open Graph artwork, comparison pages answering common search queries, and reciprocal links among GitHub, documentation, PyPI, and releases.

## Publication targets

- PyPI for `lowpack` using trusted publishing.
- GitHub Releases with wheel, sdist, checksums, SBOM, signatures, golden archives, and compatibility fixtures.
- Read the Docs or GitHub Pages for versioned documentation.
- Do not seek OS repository inclusion until the format and CLI stabilize beyond alpha.

## Release automation

A release tag should run Linux and Windows tests, hostile archive tests, deterministic fuzz smoke, clean-wheel installation, reproducibility checks, migration tests against golden archives, large-file memory tests, staged extraction tests, checksums, SBOM generation, signatures, and documentation validation.

## Success criteria

A user should be able to preview an archive plan, understand why each transform or codec was selected, compare LowPack against established alternatives, verify an archive without extraction, extract transactionally, and recover or migrate old archives with documented guarantees.