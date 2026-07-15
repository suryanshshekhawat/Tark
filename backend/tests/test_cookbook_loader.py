"""Fast, no-subprocess tests for the cookbook frontmatter parser and
assembly logic. See test_cookbook_patterns.py for the slow test that
actually compiles every pattern's Lean code against tark_lean/.
"""
import pytest

from app.pipeline import cookbook_loader
from app.pipeline.cookbook_loader import (
    CookbookError,
    _load_pattern,
    _parse_frontmatter,
    build_lean_system_prompt,
    load_patterns,
)


def test_parses_simple_and_block_and_list_fields(tmp_path, monkeypatch):
    # _category_for() derives the category from the path relative to
    # COOKBOOK_DIR, so a pattern being tested needs to appear to live under
    # it — point COOKBOOK_DIR at tmp_path rather than testing against a
    # throwaway file scattered outside the real cookbook tree.
    monkeypatch.setattr(cookbook_loader, "COOKBOOK_DIR", tmp_path)
    path = tmp_path / "example.md"
    path.write_text(
        "---\n"
        "title: Example pattern\n"
        "tags: [foo, bar]\n"
        "verified: 2026-07-14\n"
        "when_to_use: >\n"
        "  Line one.\n"
        "  Line two.\n"
        "---\n"
        "\n"
        "```lean\n"
        "theorem t : True := trivial\n"
        "```\n",
        encoding="utf-8",
    )
    pattern = _load_pattern(path)
    assert pattern.title == "Example pattern"
    assert pattern.tags == ("foo", "bar")
    assert pattern.verified == "2026-07-14"
    assert pattern.when_to_use == "Line one. Line two."
    assert pattern.lean_code == "theorem t : True := trivial"
    assert pattern.gotchas is None


def test_missing_frontmatter_delimiter_raises(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text("no frontmatter here", encoding="utf-8")
    with pytest.raises(CookbookError):
        _parse_frontmatter(path.read_text(encoding="utf-8"), path)


def test_missing_required_title_raises(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text(
        "---\nwhen_to_use: >\n  Something.\n---\n\n```lean\ntheorem t : True := trivial\n```\n",
        encoding="utf-8",
    )
    with pytest.raises(CookbookError):
        _load_pattern(path)


def test_missing_lean_block_raises(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text(
        "---\ntitle: X\nwhen_to_use: >\n  Something.\n---\n\nno code block here\n",
        encoding="utf-8",
    )
    with pytest.raises(CookbookError):
        _load_pattern(path)


def test_real_cookbook_loads_without_error():
    """Every pattern currently checked into lean_cookbook/ must at least
    parse cleanly — this is the fast, format-only counterpart to
    test_cookbook_patterns.py's slow compile check.
    """
    patterns = load_patterns()
    assert len(patterns) >= 9  # the 9 patterns migrated in this session
    for pattern in patterns:
        assert pattern.title
        assert pattern.when_to_use
        assert pattern.lean_code
        assert pattern.category  # every pattern must live in some category dir


def test_build_lean_system_prompt_includes_prelude_and_patterns():
    prompt = build_lean_system_prompt()
    assert "Lean formalization stage of Tark" in prompt  # from _prelude.md
    assert "```lean" in prompt
    assert prompt.count("```lean") == len(load_patterns())
