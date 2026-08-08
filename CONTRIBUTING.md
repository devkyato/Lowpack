# Contributing

Thanks for taking a look at LowPack. I keep the contribution loop deliberately
small: create a virtual environment, install `.[dev]`, then run:

```powershell
pytest
ruff check .
mypy src/lowpack
python -m build
```

For release artifacts, use `python scripts/build_release.py`. It pins the
archive timestamp through `SOURCE_DATE_EPOCH`, so a clean checkout can produce
the same wheel and source archive byte-for-byte.

I thought about format changes as a special case: once bytes become archives,
casual changes can strand somebody's data. A format change therefore needs a
version decision, byte-level docs, corruption and determinism tests, and
migration notes. Benchmark claims need the corpus, command, environment, and
raw result file. Please do not add network access, analytics, or lossy
transforms.

## Release checklist

Before I publish a LowPack release, I check:

- `pyproject.toml`, `lowpack.__version__`, `.zenodo.json`, `CITATION.cff`,
  README links/citation, changelog, and release notes agree on the version and
  date;
- `.zenodo.json` parses, its description uses only supported HTML, and citation
  metadata contains no unassigned DOI or ORCID;
- `pytest`, `ruff check .`, `mypy src/lowpack`, and `python -m build` pass;
- `python scripts/build_release.py` produces deterministic wheel and source
  artifacts from clean checkouts and `SHA256SUMS` matches them;
- the wheel installs in a fresh environment and `lowpack --version`,
  `lowpack doctor`, pack, inspect, full verify, unpack, compatibility, and
  migration smoke checks behave as documented;
- format/schema changes have migration notes and corruption, security,
  determinism, and compatibility tests;
- benchmark text names the exact corpus, command, environment, and raw result
  rather than making a general performance claim.
