"""Shared report aggregation (CONSTRUCTION_PLAN.md §6 stage 7, §11) — used
by both the mock and real pipelines so verdict semantics live in one place.
"""
from __future__ import annotations

import re

from ..models.schema import OverallStatus, Report, Step, Verdict


def _step_sort_key(step_id: str) -> tuple[str, int]:
    """Natural sort so S2 < S10 (plain string sort would put S10 first)."""
    match = re.match(r"^(\D*)(\d+)$", step_id)
    if match:
        return match.group(1), int(match.group(2))
    return step_id, 0


def build_report(
    normalized_source: str, steps: list[Step], claude_global_notes: list[str] | None = None
) -> Report:
    ordered = sorted(steps, key=lambda s: _step_sort_key(s.id))
    verified = sum(1 for s in ordered if s.verdict == Verdict.VERIFIED)
    assumed = sum(1 for s in ordered if s.verdict == Verdict.ASSUMED)
    refuted = any(s.verdict == Verdict.REFUTED for s in ordered)

    # ASSUMED steps are premises, not obligations — a proof isn't "partially
    # verified" because it has premises. FULLY_VERIFIED means every step that
    # could be checked was, ignoring the ones that were never claims.
    checkable = [s for s in ordered if s.verdict != Verdict.ASSUMED]

    if refuted:
        status = OverallStatus.REFUTED_SOMEWHERE
    elif checkable and verified == len(checkable):
        status = OverallStatus.FULLY_VERIFIED
    else:
        status = OverallStatus.PARTIALLY_VERIFIED

    return Report(
        overall_status=status,
        steps_verified=verified,
        steps_total=len(ordered),
        steps_assumed=assumed,
        normalized_source=normalized_source,
        steps=ordered,
        claude_global_notes=claude_global_notes or [],
    )
