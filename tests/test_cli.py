import json
from pathlib import Path

from lowpack.cli import build_parser, main


def test_cli_json_and_exit_codes(tmp_path: Path, capsys) -> None:
    source = tmp_path / "hello"
    source.write_text("hello", encoding="utf-8")
    archive = tmp_path / "a.lpk"
    assert main(["pack", str(source), "-o", str(archive), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["file_count"] == 1
    assert main(["list", str(archive), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["path"] == "hello"
    assert main(["verify", str(archive), "--quick", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    archive.write_bytes(b"broken")
    assert main(["verify", str(archive)]) == 2


def test_verify_deterministic_command(tmp_path: Path, capsys) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    first.write_bytes(b"x")
    second.write_bytes(b"x")
    assert main(["verify-deterministic", str(first), str(second)]) == 0
    second.write_bytes(b"y")
    assert main(["verify-deterministic", str(first), str(second)]) == 2


def test_permission_restoration_requires_explicit_opt_in() -> None:
    parser = build_parser()
    default = parser.parse_args(["unpack", "archive.lpk"])
    opted_in = parser.parse_args(["unpack", "archive.lpk", "--restore-permissions"])
    assert default.restore_permissions is False
    assert opted_in.restore_permissions is True
