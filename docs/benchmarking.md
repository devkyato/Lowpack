# Benchmark methodology

The fixed-seed generator creates a disclosed mixed corpus locally and never
downloads data. The runner compares store, deterministic gzip level 6, raw
Zstandard levels 1/3/9, and applicable LowPack profiles. Each raw-codec timing
uses one warm-up and the median of repeated monotonic-clock runs.

Reports include original/packed bytes, ratios, encode/decode time and
throughput, Python/OS/CPU metadata, Python-observable peak memory, selection
time, container overhead, extraction time, and full-verification time where
applicable. Filesystem cache effects are not controlled. Compare results only
for the recorded corpus, command, codec versions, and host.
