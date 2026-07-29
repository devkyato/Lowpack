from pathlib import Path

from lowpack.benchmark import benchmark, markdown_report


def test_benchmark_separates_comparison_scopes(tmp_path: Path) -> None:
    source = tmp_path / "corpus"
    source.mkdir()
    (source / "a.txt").write_text("repeat me\n" * 100, encoding="utf-8")
    (source / "b.bin").write_bytes(bytes(range(256)))
    result = benchmark([str(source)], repeats=1)
    scopes = {row["scope"] for row in result["results"]}
    assert scopes == {"raw-payload", "tar-container", "full-archive"}
    report = markdown_report(result)
    assert "| Scope | Method |" in report
    assert "tar+gzip-6" in report
