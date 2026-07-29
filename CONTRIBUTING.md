# Contributing

Create a virtual environment and install `.[dev]`, then run:

```powershell
pytest
ruff check .
mypy src/lowpack
python -m build
```

Changes to the format require a format-version decision, byte-level docs,
corruption tests, determinism tests, and migration notes. Benchmark claims
must include the generated corpus, command, environment, and raw result file.
Do not add network access, analytics, or lossy transforms.
