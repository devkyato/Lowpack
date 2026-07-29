# Benchmark methodology

I thought about the benchmark from the skeptical reader's side: the corpus
should be visible, repeatable, and allowed to make LowPack look slower or
larger. The fixed-seed generator creates a disclosed mixed corpus locally and
never downloads data. The runner compares store, deterministic gzip level 6,
raw Zstandard levels 1/3/9, and applicable LowPack profiles. Each raw-codec
timing uses one warm-up and the median of repeated monotonic-clock runs.

I split the report into three scopes so unlike products are not collapsed into
one ranking:

1. `raw-payload` compresses only the concatenated bytes. It answers a codec
   question and makes no archive claim.
2. `tar-container` adds deterministic filenames, boundaries, and metadata,
   then compresses and reparses the tar stream.
3. `full-archive` measures LowPack packing, file extraction, and full
   verification with its manifest, hashes, deduplication, and temporary-file
   writes.

Reports include original/packed bytes, ratios, encode/decode time and
throughput, Python/OS/CPU metadata, Python-observable peak memory, selection
time, container overhead, extraction time, and full-verification time where
applicable. Filesystem cache effects are not controlled. So, when you quote a
result, please keep its scope, corpus, command, codec versions, and host
attached to it. That context is part of the measurement.
