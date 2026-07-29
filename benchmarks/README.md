# Benchmark corpus

Run `python benchmarks/generate_corpus.py`, then
`python benchmarks/run_benchmarks.py`. Generation uses fixed seed 1729 and
creates Python/Arduino source, JSON, Markdown, repeated/duplicate/tiny/empty
files, timestamped numeric telemetry, low-cardinality states, random noise,
and deterministic gzip data. It never downloads data.

Generated `corpus/` and result files are local artifacts and need not be
committed. Results describe only that corpus and the reported environment.
