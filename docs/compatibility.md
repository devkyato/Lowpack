# Archive compatibility and migration

LowPack 0.2 writes binary format 1.1 with manifest schema 2.0. LowPack 0.1.x
wrote format 1.0. I did not want a security-driven schema change to leave the
earliest test archives stranded, so 0.2.1 adds one explicit bridge:

```powershell
lowpack compatibility old-project.lpk
lowpack migrate old-project.lpk -o project-1.1.lpk
lowpack verify project-1.1.lpk --full
```

The command never edits `old-project.lpk`. An existing output is refused unless
you pass `--overwrite`.

`lowpack compatibility` is the read-only half of this workflow. It checks
framing, canonical manifest structure, the manifest hash, the complete body
hash, and current schema relationships, then reports either `current` or
`migration-available`. It does not decompress chunks, extract files, or write
an output:

```powershell
lowpack compatibility old-project.lpk --json
```

## What the migration does

Oh! On this part, “migration” does not mean extracting files somewhere and
packing them again with a possibly different policy. LowPack:

1. checks the 1.0 header, footer, canonical manifest hash, and complete body
   hash;
2. converts embedded compression dictionaries into the authenticated schema 2
   catalog;
3. maps the old selection goal names to their deterministic policy names and
   records preferred-versus-actual chunk decisions;
4. validates paths, sizes, offsets, dictionaries, transforms, permissions,
   references, and payload boundaries against the current strict schema;
5. preserves the original compressed chunk payload area;
6. writes a sibling temporary 1.1 archive and fully decompresses,
   reconstructs, and hashes every file; and
7. atomically publishes the destination only after all checks pass.

Stored permission values are reduced to ordinary rwx bits during migration.
Restoring even those bits remains opt-in during extraction.

## What it deliberately does not do

Migration supports format 1.0 only. It does not guess at unknown future
formats, repair a corrupt body, bypass current safety limits, or overwrite the
source. If a 0.1 archive contains a relationship that the current validator
cannot prove safe, migration fails without publishing a partial destination.

Use `--json` when another local tool needs a stable result record:

```powershell
lowpack migrate old.lpk -o migrated.lpk --json
```

For the precise framing and schema, see the [format reference](format.md). For
the trust model, see [extraction security](security.md).
