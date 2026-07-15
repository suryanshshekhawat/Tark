"""Compiles every lean_cookbook/ pattern's Lean snippet against tark_lean/
independently of the full pipeline. This is the enforcement mechanism
behind lean_cookbook/README.md's "improvements are in no way regressive"
requirement — a new pattern, or a Mathlib version bump that breaks an
existing one, fails here instead of silently degrading formalization
quality. Slow (a real `lake env lean` subprocess per pattern) — excluded
from the fast test run, same as test_lean_verifier.py; run explicitly when
touching the cookbook or upgrading the Mathlib pin:

    ./.venv/Scripts/python.exe -m pytest tests/test_cookbook_patterns.py -q
"""
import pytest

from app.models.schema import Verdict
from app.pipeline.cookbook_loader import load_patterns
from app.verifiers.lean_verifier import LeanVerifier

_PATTERNS = load_patterns()


@pytest.mark.parametrize(
    "pattern",
    _PATTERNS,
    ids=[f"{p.category}/{p.path.stem}" for p in _PATTERNS],
)
def test_pattern_compiles(pattern):
    # No explicit timeout -> LeanVerifier's own DEFAULT_TIMEOUT, so this
    # test enforces the same budget the real pipeline gives each step.
    # Hardcoding a shorter timeout here previously caused two known-fast
    # patterns (confirmed to compile in ~15s alone) to spuriously fail
    # under concurrency/system contention during the full suite run.
    result = LeanVerifier().check(pattern.lean_code)
    assert result.verdict == Verdict.VERIFIED, (
        f"{pattern.path} no longer compiles against the current Mathlib pin.\n"
        f"{result.evidence.raw_output}"
    )
