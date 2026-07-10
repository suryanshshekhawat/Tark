"""Fake step stream so the SSE plumbing and frontend can be built and
exercised before Claude + Lean are wired in (CONSTRUCTION_PLAN.md §12,
Days 1-2: "SSE streaming plumbing with fake/mocked step data").

Steps are canned, but their source_span is computed against the real
normalized_source so interactive highlighting (§10a) has something to
point at during frontend dev.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from ..models.schema import (
    ClaudeNote,
    ClaudeNoteType,
    Classification,
    Evidence,
    Formalization,
    OverallStatus,
    Report,
    SourceSpan,
    Step,
    Verdict,
    VerifierName,
)


def _canned_steps(normalized_source: str) -> list[Step]:
    length = len(normalized_source)
    anchor = normalized_source.strip()[:40] or "proof"

    return [
        Step(
            id="S1",
            statement="Let p, q be integers with q != 0 such that sqrt(2) = p/q in lowest terms.",
            source_span=SourceSpan(start=0, end=min(60, length), anchor_text=anchor),
            depends_on=[],
            classification=Classification.LEAN_CANDIDATE,
            formalization=Formalization(lean_code="-- pending Claude formalization", attempts=0),
            verdict=Verdict.VERIFIED,
            verifier=VerifierName.LEAN,
            evidence=Evidence(
                raw_output="(mock) lake env lean check_xyz.lean\nexit code: 0", exit_code=0
            ),
            claude_notes=[],
        ),
        Step(
            id="S2",
            statement="gcd(48, 18) = 6",
            source_span=SourceSpan(start=min(60, length), end=min(90, length)),
            depends_on=["S1"],
            classification=Classification.COMPUTATIONAL,
            formalization=Formalization(
                python_code="result = __import__('math').gcd(48, 18) == 6", attempts=0
            ),
            verdict=Verdict.VERIFIED,
            verifier=VerifierName.SYMPY,
            evidence=Evidence(raw_output="(mock) sympy check -> True", exit_code=0),
            claude_notes=[
                ClaudeNote(
                    type=ClaudeNoteType.STYLE,
                    text="This step could be merged with S1 for brevity.",
                ),
            ],
        ),
        Step(
            id="S3",
            statement="Therefore p is even, by a parity argument left implicit.",
            source_span=SourceSpan(start=min(90, length), end=length),
            depends_on=["S2"],
            classification=Classification.UNFORMALIZABLE,
            formalization=None,
            verdict=Verdict.UNVERIFIED,
            verifier=None,
            evidence=None,
            claude_notes=[
                ClaudeNote(
                    type=ClaudeNoteType.SUSPICION,
                    text="The parity step skips justification — cannot be formalized as stated.",
                ),
            ],
        ),
    ]


async def run_mock_pipeline(normalized_source: str) -> AsyncGenerator[Step, None]:
    for step in _canned_steps(normalized_source):
        await asyncio.sleep(0.6)  # simulate per-step Claude + verifier latency
        yield step


def build_report(normalized_source: str, steps: list[Step]) -> Report:
    verified = sum(1 for s in steps if s.verdict == Verdict.VERIFIED)
    refuted = any(s.verdict == Verdict.REFUTED for s in steps)
    if refuted:
        status = OverallStatus.REFUTED_SOMEWHERE
    elif verified == len(steps):
        status = OverallStatus.FULLY_VERIFIED
    else:
        status = OverallStatus.PARTIALLY_VERIFIED

    return Report(
        overall_status=status,
        steps_verified=verified,
        steps_total=len(steps),
        normalized_source=normalized_source,
        steps=steps,
        claude_global_notes=[
            "(mock) This report came from the Day 1-2 SSE scaffold, not real Claude/Lean output."
        ],
    )
