# Architecture

`archive.py` owns container I/O and invariant validation. `format.py` handles
fixed binary framing; `manifest.py` handles executable-free canonical JSON.
`codecs` exposes the experimental `Codec` protocol. `profiles` detects or
reversibly prepares application data without owning compression. `selection`
measures a bounded sample and stores all candidate measurements. The CLI is a
thin adapter over the typed public API.

Pack walks normalized inputs in lexical order, samples at most 256 KiB per
file, writes each unseen raw chunk once, then emits the manifest and footer.
Extraction validates all manifest destinations before creating content,
fetches only referenced chunks, reverses the transform, verifies the file
hash, and atomically finalizes it.
