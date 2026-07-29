"""Source-project classification and exclusions."""

from __future__ import annotations

from pathlib import PurePosixPath

DEFAULT_EXCLUDES = (
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
)

CATEGORIES = {
    ".py": "python",
    ".c": "c-cpp",
    ".cc": "c-cpp",
    ".cpp": "c-cpp",
    ".h": "c-cpp",
    ".hpp": "c-cpp",
    ".ino": "arduino",
    ".js": "javascript-typescript",
    ".jsx": "javascript-typescript",
    ".ts": "javascript-typescript",
    ".tsx": "javascript-typescript",
    ".html": "html-css",
    ".css": "html-css",
    ".json": "json-yaml",
    ".yaml": "json-yaml",
    ".yml": "json-yaml",
    ".md": "documentation",
    ".rst": "documentation",
    ".txt": "documentation",
}


def category(path: str) -> str:
    return CATEGORIES.get(PurePosixPath(path).suffix.lower(), "other")
