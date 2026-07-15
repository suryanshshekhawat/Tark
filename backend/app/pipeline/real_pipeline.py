"""Real pipeline: decompose -> per-step formalize + verify -> Report.

CONSTRUCTION_PLAN.md §6, stages 2-5. Stage 6 (the separate advisory pass)
lives in advisory.py and is invoked by the router after this generator is
exhausted, since it needs the final verdicts for every step.

Every stage handles its own failures without killing the stream (§4a.5):
a malformed Claude response or a verifier crash on one step degrades that
step to UNVERIFIED with the error recorded as evidence, and the other
steps still get reported.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from ..models.schema import ClaudeNote, ClaudeNoteType, Classification, Evidence, Formalization, Step, Verdict
from ..verifiers.base import VerdictResult
from ..verifiers.lean_verifier import LeanVerifier
from ..verifiers.sympy_verifier import SympyVerifier
from .decompose import RawStep, decompose
from .formalize import formalize, formalize_lean_repair
from .span_matching import find_span

_lean_verifier = LeanVerifier()
_sympy_verifier = SympyVerifier()

# Each Lean check is a heavy subprocess (elaborating a Mathlib import chain).
# Firing off one per step with no cap causes them to contend for CPU/disk and
# every single one blows its timeout — observed directly on an 11-step proof
# (8 cores, all-timeout with unbounded concurrency). Cap concurrent Lean
# subprocesses; SymPy checks are cheap and don't need this.
#
# Lowered from 3 to 2 after a second live regression: with only ~2GB free
# RAM on this dev machine, even 3 concurrent Mathlib environment loads caused
# every check to time out — including ones independently verified to compile
# in ~14s alone. Same code, same imports, only difference was concurrency
# level plus ambient system memory pressure at the time. If checks are still
# timing out with this lower limit, the fix is freeing memory / reducing this
# further, not touching the formalization prompt — the failure is
# infrastructure contention, not formalization quality. See CLAUDE.md.
#
# Reconfirmed in a later session, worse: a 15-lean_candidate-step proof
# produced 4/20 verified with free RAM at just 0.6GB (Get-CimInstance
# Win32_OperatingSystem), and every failure's evidence was an *empty*
# timeout with no partial stdout/stderr at all — the classic signature of
# contention, not a compile error. `Get-Process | sort WorkingSet64 -desc`
# showed several multi-GB Chrome processes as the dominant consumer. Before
# concluding the cookbook needs more/better patterns after a bad run, check
# free memory first — a pattern independently confirmed to compile in ~15s
# alone can still show UNVERIFIED here for reasons that have nothing to do
# with the pattern.
_LEAN_CONCURRENCY_LIMIT = 2
_lean_semaphore = asyncio.Semaphore(_LEAN_CONCURRENCY_LIMIT)

# §8.3 / §11: cap at 3 attempts total per step.
MAX_LEAN_ATTEMPTS = 3


# Neither of these gets a formalization/verification attempt — a PREMISE
# isn't a claim, and UNFORMALIZABLE means Claude already said it can't be
# formalized. Both skip straight to a terminal verdict.
_SKIP_FORMALIZATION = {Classification.UNFORMALIZABLE, Classification.PREMISE}


def _build_step(raw: RawStep, normalized_source: str) -> Step:
    source_span = find_span(normalized_source, raw.anchor_text)
    claude_notes = []
    if raw.classification in _SKIP_FORMALIZATION and raw.note:
        claude_notes.append(ClaudeNote(type=ClaudeNoteType.SUSPICION, text=raw.note))

    # PREMISE -> ASSUMED (given, not a claim); UNFORMALIZABLE -> UNVERIFIED
    # (a claim we couldn't check). Never conflate the two (see CLAUDE.md).
    verdict = Verdict.ASSUMED if raw.classification == Classification.PREMISE else Verdict.UNVERIFIED

    return Step(
        id=raw.id,
        statement=raw.statement,
        source_span=source_span,
        depends_on=raw.depends_on,
        classification=raw.classification,
        formalization=None,
        verdict=verdict,
        verifier=None,
        evidence=None,
        claude_notes=claude_notes,
    )


def _is_retryable(result: VerdictResult) -> bool:
    """§8.3.4: a genuine mathematical REFUTED is surfaced immediately, never
    retried. A timeout is also excluded — with concurrency already capped,
    retrying one is unlikely to help and just burns another 30s slot that
    other steps are waiting on. Everything else UNVERIFIED (bad import,
    unknown tactic, unsolved goal, a `sorry`) is worth one more attempt.
    """
    if result.verdict != Verdict.UNVERIFIED:
        return False
    return "timed out" not in result.evidence.raw_output.lower()


async def _verify_lean_with_repair(step: Step, first_attempt_code: str) -> Step:
    code = first_attempt_code
    for attempt in range(1, MAX_LEAN_ATTEMPTS + 1):
        step.formalization = Formalization(lean_code=code, attempts=attempt)

        try:
            async with _lean_semaphore:
                # .check() runs a blocking subprocess.run() — calling it
                # directly here would block the *entire* event loop, not
                # just this task, serializing every concurrent step.
                result = await asyncio.to_thread(_lean_verifier.check, code)
        except Exception as exc:  # noqa: BLE001 - never crash the stream
            step.evidence = Evidence(raw_output=f"Verifier crashed: {exc}", exit_code=None)
            step.verdict = Verdict.UNVERIFIED
            return step

        step.verdict = result.verdict
        step.verifier = result.verifier
        step.evidence = result.evidence

        if result.verdict == Verdict.VERIFIED:
            return step
        if not _is_retryable(result) or attempt == MAX_LEAN_ATTEMPTS:
            return step

        try:
            code = await formalize_lean_repair(step.statement, code, result.evidence.raw_output)
        except Exception:  # noqa: BLE001 - repair call failing just ends the loop early
            return step

    return step


async def _formalize_and_verify(step: Step) -> Step:
    try:
        lean_code, python_code = await formalize(step.classification, step.statement)
    except Exception as exc:  # noqa: BLE001 - must degrade to UNVERIFIED, never crash the stream
        step.formalization = Formalization(attempts=1)
        step.evidence = Evidence(raw_output=f"Formalization failed: {exc}", exit_code=None)
        step.verdict = Verdict.UNVERIFIED
        return step

    if step.classification == Classification.LEAN_CANDIDATE:
        return await _verify_lean_with_repair(step, lean_code)

    step.formalization = Formalization(python_code=python_code, attempts=1)
    try:
        result = await asyncio.to_thread(_sympy_verifier.check, python_code)
    except Exception as exc:  # noqa: BLE001
        step.evidence = Evidence(raw_output=f"Verifier crashed: {exc}", exit_code=None)
        step.verdict = Verdict.UNVERIFIED
        return step

    step.verdict = result.verdict
    step.verifier = result.verifier
    step.evidence = result.evidence
    return step


async def decompose_steps(normalized_source: str) -> list[Step]:
    """Stage 2 alone (§6.2) — a single Claude call that already knows the
    true total step count, every statement's text/classification/depends_on,
    and (via find_span) its source_span, well before any formalize/verify
    work starts. Split out from run_real_pipeline so routers/verify.py can
    surface this immediately as a `decomposition` SSE event instead of
    letting the frontend infer "how many statements total" from whichever
    steps have merely *finished verifying* so far — a count that
    misleadingly grows over the whole run instead of being known upfront.
    """
    raw_steps = await decompose(normalized_source)
    return [_build_step(raw, normalized_source) for raw in raw_steps]


async def run_verification(steps: list[Step]) -> AsyncGenerator[Step, None]:
    """Stages 3-5 (§6.3-6.5) over an already-decomposed step list. Mutates
    and yields the same Step objects passed in — a caller that already
    attached data to a step (e.g. pdf_boxes, computed once right after
    decomposition) will see that data preserved on the object it receives
    back here, not overwritten.
    """
    skipped = [s for s in steps if s.classification in _SKIP_FORMALIZATION]
    formalizable = [s for s in steps if s.classification not in _SKIP_FORMALIZATION]

    for step in skipped:
        yield step

    tasks = [asyncio.create_task(_formalize_and_verify(s)) for s in formalizable]
    for coro in asyncio.as_completed(tasks):
        yield await coro


async def run_real_pipeline(normalized_source: str) -> AsyncGenerator[Step, None]:
    steps = await decompose_steps(normalized_source)
    async for step in run_verification(steps):
        yield step
