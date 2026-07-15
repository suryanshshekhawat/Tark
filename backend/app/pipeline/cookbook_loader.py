"""Loads the Lean strategy cookbook (../../../lean_cookbook/) and assembles
it into the Lean formalization system prompt.

See lean_cookbook/README.md for the format spec and the contribution
workflow. This module is the ONLY place that turns cookbook files into the
prompt Claude actually sees — adding a pattern file there is the entire
integration step; nothing here should ever hardcode a pattern.

Deliberately hand-rolled rather than depending on a YAML library: the
frontmatter schema is small and constrained by convention (see the README),
so a ~100-line parser covers it without adding a new dependency.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Cookbook lives at the repo root, a sibling of backend/, frontend/, and
# tark_lean/ — resolved relative to this file's own location, not the
# process's cwd (see CLAUDE.md's note on the .env cwd bug this exact
# mistake caused elsewhere in this codebase).
COOKBOOK_DIR = Path(__file__).resolve().parents[3] / "lean_cookbook"
PRELUDE_PATH = COOKBOOK_DIR / "_prelude.md"

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.DOTALL)
_LEAN_BLOCK_RE = re.compile(r"```lean\r?\n(.*?)```", re.DOTALL)
_LIST_VALUE_RE = re.compile(r"^\[(.*)\]$")


@dataclass(frozen=True)
class Pattern:
    path: Path
    category: str  # e.g. "number-theory/factorials", derived from directory structure
    title: str
    when_to_use: str
    lean_code: str
    tags: tuple[str, ...] = ()
    gotchas: str | None = None
    verified: str | None = None


class CookbookError(Exception):
    """A cookbook file doesn't match the format documented in README.md."""


def _parse_frontmatter(text: str, path: Path) -> tuple[dict[str, str | tuple[str, ...]], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise CookbookError(f"{path}: missing or malformed '---' frontmatter block.")
    raw_frontmatter, body = match.group(1), match.group(2)

    fields: dict[str, str | tuple[str, ...]] = {}
    lines = raw_frontmatter.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        key_match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not key_match:
            raise CookbookError(f"{path}: unparseable frontmatter line: {line!r}")
        key, rest = key_match.group(1), key_match.group(2).strip()
        i += 1

        if rest == ">":
            # Folded block scalar: consume subsequent indented lines, join
            # with spaces (YAML '>' folding semantics, simplified — this
            # cookbook's fields are single paragraphs by convention).
            block_lines = []
            while i < len(lines) and (lines[i].startswith(" ") or lines[i].startswith("\t")):
                block_lines.append(lines[i].strip())
                i += 1
            fields[key] = " ".join(block_lines).strip()
        elif (list_match := _LIST_VALUE_RE.match(rest)) is not None:
            fields[key] = tuple(
                item.strip() for item in list_match.group(1).split(",") if item.strip()
            )
        else:
            fields[key] = rest

    return fields, body


def _load_prelude() -> str:
    if not PRELUDE_PATH.exists():
        raise CookbookError(f"Cookbook prelude not found at {PRELUDE_PATH}.")
    text = PRELUDE_PATH.read_text(encoding="utf-8")
    _, body = _parse_frontmatter(text, PRELUDE_PATH)
    return body.strip()


def _category_for(path: Path) -> str:
    """Category is the directory structure between the cookbook root and the
    file itself, e.g. lean_cookbook/number-theory/factorials/foo.md ->
    "number-theory/factorials". The folder IS the category — no separate
    frontmatter field to keep in sync (see the README's note on avoiding
    two sources of truth for the same fact).
    """
    return "/".join(path.relative_to(COOKBOOK_DIR).parts[:-1])


def _load_pattern(path: Path) -> Pattern:
    text = path.read_text(encoding="utf-8")
    fields, body = _parse_frontmatter(text, path)

    if "title" not in fields or not fields["title"]:
        raise CookbookError(f"{path}: missing required 'title' field.")
    if "when_to_use" not in fields or not fields["when_to_use"]:
        raise CookbookError(f"{path}: missing required 'when_to_use' field.")

    lean_match = _LEAN_BLOCK_RE.search(body)
    if lean_match is None:
        raise CookbookError(f"{path}: no ```lean code block found in the body.")

    tags = fields.get("tags", ())
    if isinstance(tags, str):  # a single bare tag without brackets
        tags = (tags,)

    return Pattern(
        path=path,
        category=_category_for(path),
        title=str(fields["title"]),
        when_to_use=str(fields["when_to_use"]),
        lean_code=lean_match.group(1).strip("\n"),
        tags=tags,
        gotchas=fields.get("gotchas"),  # type: ignore[arg-type]
        verified=fields.get("verified"),  # type: ignore[arg-type]
    )


def load_patterns() -> list[Pattern]:
    """Discovers every pattern file under lean_cookbook/, excluding the
    README and prelude. Sorted by path for deterministic, stable prompt
    ordering — matters both for readability and for prompt-cache hit rate
    (a stable prompt text is a cache hit; a reshuffled one isn't).
    """
    if not COOKBOOK_DIR.exists():
        raise CookbookError(f"Cookbook directory not found at {COOKBOOK_DIR}.")

    pattern_paths = sorted(
        p
        for p in COOKBOOK_DIR.rglob("*.md")
        if p.name not in {"README.md", "_prelude.md"}
    )
    return [_load_pattern(p) for p in pattern_paths]


def _render_pattern(pattern: Pattern, number: int) -> str:
    lines = [f"{number}. {pattern.title} (category: {pattern.category}):"]
    lines.append(pattern.when_to_use)
    lines.append(f"```lean\n{pattern.lean_code}\n```")
    if pattern.gotchas:
        lines.append(pattern.gotchas)
    return "\n".join(lines)


def build_lean_system_prompt() -> str:
    """Assembles the full Lean formalization system prompt: the prelude,
    then every cookbook pattern, numbered and grouped in category order.
    """
    prelude = _load_prelude()
    patterns = load_patterns()

    if not patterns:
        return prelude

    transition = (
        "The following patterns are verified to compile against this exact Mathlib pin. "
        "When a step matches one of these shapes, adapt the pattern directly rather than "
        "reconstructing an approach from memory — memory is exactly what tends to cite "
        "renamed/nonexistent lemmas."
    )
    rendered = [_render_pattern(p, i) for i, p in enumerate(patterns, start=1)]
    return "\n\n".join([prelude, transition, *rendered])
