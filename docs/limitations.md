# Alpha limitations

I would rather keep this list direct than hide unfinished edges behind an
“alpha” label. These are the boundaries I know about today:

- Format compatibility is not promised across alpha releases.
- Chunk boundaries are fixed-size, not content-defined.
- Source dictionary training is active, bounded, deterministic, and
  authenticated in the manifest, but it currently applies only to Zstandard
  chunks with enough useful same-category samples.
- Telemetry timestamps must be integral for delta transforms; textual
  timestamps use string encoding. Numeric scaling is not implemented in 0.2.
- Ordinary packing, full verification, and extraction are chunk-streamed.
  Canonical telemetry transformation remains memory-resident and is therefore
  capped at 64 MiB encoded and reconstructed size.
- No symlinks, hard links, ACLs, sparse files, extended attributes, encryption,
  signatures, split archives, append mode, `.lpd`, or `.lpdict`.
- Quick verification checks framing, hashes, and bounds but not decompression.
- The portable extraction path rejects existing symlink parents and rechecks
  them before replacement, but output roots must not be concurrently writable
  by attackers. A future Unix-specific backend may add `openat`/`O_NOFOLLOW`
  traversal.
- General safety limits are constants in the 0.2 library API.

I am tracking the larger follow-ups in the
[v0.2.0 milestone](https://github.com/devkyato/Lowpack/milestone/1), so this
page and the issue tracker should tell the same story.
