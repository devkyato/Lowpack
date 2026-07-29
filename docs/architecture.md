# Architecture

I kept the architecture intentionally boring at the boundaries. Parsing,
compression, transformation, and command-line presentation each have one
clear place, which makes the security rules and format decisions easier to
review.

`archive.py` coordinates collection, container I/O, verification, and
extraction. Its individual stages are deliberately isolated as helpers with
one-way data flow; `format.py` handles fixed binary framing and `manifest.py`
handles executable-free canonical JSON plus total JSON limits.
`codecs` exposes the experimental `Codec` protocol. `profiles` detects or
reversibly prepares application data without owning compression. `selection`
measures a bounded sample and stores all candidate measurements. The CLI is a
thin adapter over the typed public API.

Here is the flow I keep in mind: packing creates and reserves its temporary
target first, walks normalized inputs in lexical order through one collision
and filesystem-identity registry, samples at most 256 KiB per file, then opens
each source once for the accepted snapshot. It hashes while chunking, compares
descriptor metadata before and after, and writes each unseen raw chunk once.

Reading works back from trust: framing and canonical JSON come first, then the
separately versioned manifest relationships, then chunk data. Ordinary files
are verified or extracted a chunk at a time. Canonical transforms enter a
smaller explicitly bounded path with their own structural validator. A sibling
temporary output is fsynced, its parent safety is checked again, and only then
is it atomically moved into place.
