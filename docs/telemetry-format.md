# Telemetry CSV transformation

I split telemetry into exact and canonical modes because “lossless CSV” can
mean two different things. Exact mode identifies the transformation as
`telemetry-csv-v1` but preserves
the input byte-for-byte. Canonical mode parses UTF-8 CSV, rejects inconsistent
row widths, stores header/order and separated columns in deterministic JSON
prefixed by `LPTCSV1\n`, and reconstructs with comma delimiters, minimal
quoting, and LF records.

Each column stores a null bitmap. Monotonic integers and integral timestamps
use delta or delta-of-delta arrays; Booleans use a bit vector; low-cardinality
strings use sorted dictionary indices; repeated strings can use run lengths.
Floating-point values are stored as big-endian IEEE-754 binary64 bytes without
rounding. `--time-field` forces timestamp classification (non-integral
timestamps use a string dictionary).

Before reconstruction, the decoder validates the top-level schema, header and
column agreement, row counts, row-count-to-declared-output plausibility,
bitmap lengths and padding, dictionary indices, delta counts, Boolean bit
counts, float byte lengths, and positive run lengths whose sum exactly matches
the non-null rows. Canonical telemetry is capped at one million rows, 4,096
columns, ten million cells, and 64 MiB encoded/output data.

Canonical reconstruction is semantically equivalent CSV, not byte-identical:
line endings, quoting choices, and insignificant formatting can change. If
those original bytes matter, use exact mode—that is why I made it the default.
