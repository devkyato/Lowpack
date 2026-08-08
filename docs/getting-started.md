# Getting started

I wanted the first LowPack run to answer two questions quickly: “Did I install
the real release?” and “Can I restore exactly what I packed?” This page does
both without needing an account or network connection after installation.

## Install the release

LowPack supports Python 3.9 through 3.14. On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install "https://github.com/devkyato/Lowpack/releases/download/v0.2.3/lowpack-0.2.3-py3-none-any.whl"
lowpack --version
lowpack doctor
```

On macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "https://github.com/devkyato/Lowpack/releases/download/v0.2.3/lowpack-0.2.3-py3-none-any.whl"
lowpack --version
lowpack doctor
```

The release page includes the wheel, source archive, and `SHA256SUMS`. Download
the wheel first if you want to compare its SHA-256 before installing it. I
publish the exact expected digests in the release description as well.

For a globally available but isolated terminal command, replace the virtual
environment steps with `pipx install <wheel-url>`. LowPack itself does not
contact GitHub or any other service while packing, inspecting, verifying, or
extracting.

## Make and restore an archive

```powershell
lowpack pack my-project -o my-project.lpk --profile source
lowpack inspect my-project.lpk
lowpack verify my-project.lpk --full
lowpack unpack my-project.lpk -o restored
```

For a directory containing 42 files, the `pack`, `verify`, and `unpack` lines
appear in this exact form (the count and archive path follow your input).
`inspect` prints the archive fields between the first line and `OK`:

```text
Packed 42 files to my-project.lpk
OK
Extracted 42 files
```

I thought too on the point that a successful pack should not be treated as a
successful restore. `verify --full` decompresses each stored representation
and checks reconstructed file hashes. For important data, still test the
restored directory and keep another copy outside the archive.

The `source` profile excludes documented cache/build paths. LowPack prints and
records every exclusion; use `--include-all` when the directory should be
literal. Use the `general` profile for an ordinary tree with no profile
exclusions.

## Upgrade or remove

Upgrade to a newer release by activating the same environment and installing
its wheel URL with `--upgrade`. Remove LowPack with:

```powershell
python -m pip uninstall lowpack
```

Uninstalling never removes `.lpk` files or extracted data.

If you have a 0.1.x archive, install 0.2.3 and follow the
[compatibility guide](compatibility.md). Installing a new LowPack version does
not silently rewrite existing archives.

## If `lowpack` is not found

First run `python -m lowpack --version`. If that works, LowPack is installed
for that interpreter and the environment's scripts directory is simply not on
the current shell path. Activate the virtual environment again, or use
`python -m lowpack` in place of `lowpack`.

If neither command works, compare `python -m pip --version` and
`python --version`; they should point to the environment where you intended to
install LowPack.
