"""Run the generated corpus benchmark and optionally update README."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from generate_corpus import generate

from lowpack.benchmark import benchmark, markdown_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--update-readme", action="store_true")
    args = parser.parse_args()
    corpus = Path("benchmarks/corpus")
    generate(corpus)
    result = benchmark([str(corpus)], profile="source", repeats=args.repeats)
    Path("benchmarks/results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = markdown_report(result)
    Path("benchmarks/results.md").write_text(report, encoding="utf-8")
    if args.update_readme:
        readme = Path("README.md")
        content = readme.read_text(encoding="utf-8")
        start = content.index("<!-- BENCHMARK_START -->") + len("<!-- BENCHMARK_START -->")
        end = content.index("<!-- BENCHMARK_END -->")
        readme.write_text(content[:start] + "\n" + report + content[end:], encoding="utf-8")


if __name__ == "__main__":
    main()
