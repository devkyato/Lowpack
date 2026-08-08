# Alpha limitations

I would rather keep this list direct than hide unfinished edges behind an
“alpha” label. These are the boundaries I know about today:

- Forward compatibility is not promised across alpha releases. LowPack 0.2.3
  includes the checked migration for format 1.0 archives created by 0.1.x; it
  does not guess at unknown formats or repair corrupted archives.
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

LowPack 0.2.3 is a documentation and citation maintenance release; it does not
remove these format or implementation boundaries. I track larger follow-ups in
the [issue tracker](https://github.com/devkyato/Lowpack/issues). This page,
the [compatibility guide](compatibility.md), and open issues should tell the
same story before an archive is treated as a sole copy.
