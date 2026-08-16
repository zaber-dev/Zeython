"""Search over Zeython's own bundled documentation.

No embeddings, no vector store -- a small, deterministic keyword scorer over
markdown files bundled with the installed package. That's a deliberate
scope boundary matching the rest of the framework: correct and simple beats
a dependency-heavy search stack for a docs set this size.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import zeython

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class SearchResult:
    file: str
    title: str
    score: int
    snippet: str


def _docs_dir() -> Path | None:
    """Locate the bundled docs.

    A real install (`pip install zeython`) ships them under
    ``zeython/_docs/`` via a build-time file mapping (see pyproject.toml's
    ``force-include``). An editable/source install doesn't materialize
    that mapping, so fall back to the repo-root ``docs/`` directory
    relative to this file -- this is what makes `search_docs` work when
    developing Zeython itself, not just when using an installed copy.
    """
    bundled = Path(zeython.__file__).parent / "_docs"
    if bundled.is_dir():
        return bundled

    repo_root_docs = Path(zeython.__file__).parent.parent.parent / "docs"
    if repo_root_docs.is_dir():
        return repo_root_docs

    return None


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def _snippet(text: str, words: list[str], *, context: int = 80) -> str:
    lowered = text.lower()
    for word in words:
        index = lowered.find(word)
        if index != -1:
            start = max(index - context // 2, 0)
            end = min(index + len(word) + context // 2, len(text))
            snippet = text[start:end].replace("\n", " ").strip()
            return f"...{snippet}..." if start > 0 else snippet
    return text[:context].replace("\n", " ").strip()


def search(query: str, *, limit: int = 5) -> list[SearchResult]:
    """Score every bundled doc file against ``query`` and return the top matches."""
    docs_dir = _docs_dir()
    if docs_dir is None:
        return []

    words = [w.lower() for w in _WORD_RE.findall(query) if w]
    if not words:
        return []

    results: list[SearchResult] = []
    for path in sorted(docs_dir.glob("*.md")):
        text = path.read_text()
        lowered = text.lower()
        title = _title(text, path.stem)

        score = 0
        for word in words:
            score += lowered.count(word)
            if word in title.lower():
                score += 5  # a title match matters more than a body match

        if score > 0:
            results.append(SearchResult(file=path.name, title=title, score=score, snippet=_snippet(text, words)))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:limit]


__all__ = ["SearchResult", "search"]
