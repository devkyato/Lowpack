from pathlib import Path

from lowpack import pack, unpack, verify_archive
from lowpack.archive import _read_manifest


def _manifest(path: Path) -> dict:
    with path.open("rb") as stream:
        value, _, _ = _read_manifest(stream)
    return value


def test_source_exclusions_and_include_all(tmp_path: Path) -> None:
    source = tmp_path / "project"
    (source / ".git").mkdir(parents=True)
    (source / ".git" / "config").write_text("secret", encoding="utf-8")
    (source / "app.py").write_text("print('ok')\n", encoding="utf-8")
    excluded_archive = tmp_path / "excluded.lpk"
    result = pack([source], excluded_archive, profile="source")
    assert any(".git" in value for value in result.excluded)
    assert [item["source_category"] for item in _manifest(excluded_archive)["files"]] == ["python"]
    all_archive = tmp_path / "all.lpk"
    pack([source], all_archive, profile="source", include_all=True)
    assert any(item["path"].endswith(".git/config") for item in _manifest(all_archive)["files"])


def test_source_dictionary_training_is_bounded_and_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "dictionary-project"
    source.mkdir()
    for index in range(12):
        (source / f"module_{index}.py").write_text(
            (
                "def repeated_function(value: int) -> int:\n"
                f"    return value + {index}\n"
            )
            * 20,
            encoding="utf-8",
        )
    first = tmp_path / "dictionary-one.lpk"
    second = tmp_path / "dictionary-two.lpk"
    pack([source], first, profile="source", codec="zstd")
    pack([source], second, profile="source", codec="zstd")
    manifest = _manifest(first)
    assert "python" in manifest["source_dictionaries"]
    dictionary_id = manifest["source_dictionaries"]["python"]["dictionary_id"]
    assert manifest["dictionaries"][dictionary_id]["size"] <= 8192
    assert manifest["dictionaries"][dictionary_id]["hash"] == dictionary_id
    assert all(
        "dictionary" not in chunk for chunk in manifest["chunks"].values()
    )
    assert first.read_bytes() == second.read_bytes()
    assert verify_archive(first).valid


def test_telemetry_exact_and_canonical(tmp_path: Path) -> None:
    source = tmp_path / "telemetry.csv"
    source.write_bytes(b"timestamp,value,ok,status\r\n1,1.5,true,up\r\n2,1.50,false,up\r\n")
    exact = tmp_path / "exact.lpk"
    pack([source], exact, profile="telemetry", telemetry_mode="exact", time_field="timestamp")
    exact_out = tmp_path / "exact-out"
    unpack(exact, output=exact_out)
    assert (exact_out / "telemetry.csv").read_bytes() == source.read_bytes()
    canonical = tmp_path / "canonical.lpk"
    pack(
        [source], canonical, profile="telemetry", telemetry_mode="canonical", time_field="timestamp"
    )
    canonical_out = tmp_path / "canonical-out"
    unpack(canonical, output=canonical_out)
    assert (canonical_out / "telemetry.csv").read_bytes() == (
        b"timestamp,value,ok,status\n1,1.5,true,up\n2,1.5,false,up\n"
    )
    transform = _manifest(canonical)["files"][0]["transform"]
    assert "column separation" in transform["applied"]
    assert any("dictionary encoding" in item for item in transform["applied"])
