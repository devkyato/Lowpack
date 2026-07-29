# Benchmark corpus

I wanted a corpus anyone could regenerate without trusting a download or my
choice of files. Run `python benchmarks/generate_corpus.py`, then
`python benchmarks/run_benchmarks.py`. The generator uses fixed seed 1729 and
creates Python and Arduino source, JSON, Markdown, duplicates, tiny and empty
files, timestamped telemetry, low-cardinality states, random noise, and
deterministic gzip data.

The generated `corpus/` and result files stay local and do not need to be
committed. Oh! The important reading rule is simple: a result describes only
that generated corpus and the environment printed beside it.
