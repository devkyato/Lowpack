# Alpha limitations

I would rather keep this list direct than hide unfinished edges behind an
“alpha” label. These are the boundaries I know about today:

- Format compatibility is not promised across alpha releases.
- Chunk boundaries are fixed-size, not content-defined.
- Source dictionary training is active, bounded, deterministic, and
  authenticated in the manifest, but it currently applies only to Zstandard
  chunks with enough useful same-category samples.
- Telemetry timestamps must be integral for delta transforms; textual
  timestamps use string encoding. Numeric scaling is not implemented in 0.1.
- Transformed files and extracted payloads can be assembled in memory up to
  archive limits; ordinary packing is chunk-streamed.
- No symlinks, hard links, ACLs, sparse files, extended attributes, encryption,
  signatures, split archives, append mode, `.lpd`, or `.lpdict`.
- Quick verification checks framing, hashes, and bounds but not decompression.
- Safety limits are constants in the 0.1 library API.

I am tracking the larger follow-ups in the
[v0.2.0 milestone](https://github.com/devkyato/Lowpack/milestone/1), so this
page and the issue tracker should tell the same story.
