# Architecture

I kept the architecture intentionally boring at the boundaries. Parsing,
compression, transformation, and command-line presentation each have one
clear place, which makes the security rules and format decisions easier to
review.

`archive.py` owns container I/O and invariant validation. `format.py` handles
fixed binary framing; `manifest.py` handles executable-free canonical JSON.
`codecs` exposes the experimental `Codec` protocol. `profiles` detects or
reversibly prepares application data without owning compression. `selection`
measures a bounded sample and stores all candidate measurements. The CLI is a
thin adapter over the typed public API.

Here is the flow I keep in mind: packing walks normalized inputs in lexical
order, samples at most 256 KiB per file, and writes each unseen raw chunk once
before the manifest and footer. Extraction works back from trust: it validates
every destination first, fetches only referenced chunks, reverses the
transform, verifies the file hash, and only then finalizes the output
atomically.
