# Alpha limitations

- Format compatibility is not promised across alpha releases.
- Chunk boundaries are fixed-size, not content-defined.
- Source dictionary grouping is recorded by category but dictionary training
  is not active.
- Telemetry timestamps must be integral for delta transforms; textual
  timestamps use string encoding. Numeric scaling is not implemented in 0.1.
- Transformed files and extracted payloads can be assembled in memory up to
  archive limits; ordinary packing is chunk-streamed.
- No symlinks, hard links, ACLs, sparse files, extended attributes, encryption,
  signatures, split archives, append mode, `.lpd`, or `.lpdict`.
- Quick verification checks framing, hashes, and bounds but not decompression.
- Safety limits are constants in the 0.1 library API.
