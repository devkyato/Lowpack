# Contributing

Thanks for taking a look at LowPack. I keep the contribution loop deliberately
small: create a virtual environment, install `.[dev]`, then run:

```powershell
pytest
ruff check .
mypy src/lowpack
python -m build
```

I thought about format changes as a special case: once bytes become archives,
casual changes can strand somebody's data. A format change therefore needs a
version decision, byte-level docs, corruption and determinism tests, and
migration notes. Benchmark claims need the corpus, command, environment, and
raw result file. Please do not add network access, analytics, or lossy
transforms.
