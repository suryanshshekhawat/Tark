"""Pluggable verifier interface — CONSTRUCTION_PLAN.md §5.

`Verifier.check(step) -> VerdictResult` is the one piece of architectural
rigor worth building in from day 1: every backend (Lean, SymPy, and later
e.g. Z3) plugs into the pipeline through this same interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models.schema import Evidence, Verdict, VerifierName


@dataclass
class VerdictResult:
    verdict: Verdict
    verifier: VerifierName | None
    evidence: Evidence


class Verifier(ABC):
    @abstractmethod
    def check(self, code: str, timeout: float) -> VerdictResult:
        """Run a single formalization attempt and return a mechanical verdict.

        Implementations must never assign VERIFIED themselves based on
        heuristics — only a clean compiler/interpreter success does that.
        """
        raise NotImplementedError
