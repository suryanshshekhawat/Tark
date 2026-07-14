"""Real pipeline: decompose -> per-step formalize + verify -> Report.

CONSTRUCTION_PLAN.md §6, stages 2-5. Stage 6 (the separate advisory pass)
lives in advisory.py and is invoked by the router after this generator is
exhausted, since it needs the final verdicts for every step.

Every stage handles its own failures without killing the stream (§4a.5):
a malformed Claude response or a verifier crash on one step degrades that
step to UNVERIFIED with the error recorded as evidence, and the other
steps still get reported.

Orchestration is a LangGraph graph (decompose -> Send-fan-out over steps ->
aggregate), not a hand-rolled asyncio.gather loop, so the pipeline reads as
an explicit multi-agent graph — each formalization/repair call is still a
Claude call scoped to one role (decomposer, Lean-formalizer, Lean-repairer,
computational-formalizer; see decompose.py/formalize.py), and the graph is
what fans them out and streams results back as each step finishes. swarms.ai
was evaluated first and rejected: its Agent class unconditionally sends a
`temperature` param that the Claude Sonnet 5 API now rejects outright, with
no public way to suppress it (verified against swarms 13.0.0, the latest
release, both against the live API and swarms' own litellm_wrapper.py
source) — LangGraph has none of that friction with the same model.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import operator
import time
from collections.abc import AsyncGenerator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ..config import settings
from ..models.schema import ClaudeNote, ClaudeNoteType, Classification, Evidence, Formalization, Step, Verdict
from ..verifiers.base import VerdictResult
from ..verifiers.lean_verifier import LeanVerifier
from ..verifiers.sympy_verifier import SympyVerifier
from . import proof_cache
from .counterexample import probe_for_counterexample
from .decompose import RawStep, decompose
from .formalize import ENSEMBLE_STRATEGIES, formalize, formalize_lean, formalize_lean_repair
from .span_matching import find_span

_lean_verifier = LeanVerifier()
_sympy_verifier = SympyVerifier()

# Phase 0 instrumentation (see CONSTRUCTION_PLAN.md discussion on this branch):
# no timing existed anywhere in the pipeline before this, so any claim about
# where wall-clock time goes was reasoning from code paths, not measurement.
# This logger is the only source of truth for that until it's proven out.
_timing_logger = logging.getLogger("tark.timing")


def _lean_imports(code: str) -> list[str]:
    return [line.strip() for line in code.splitlines() if line.strip().startswith("import ")]


# Each Lean check is a heavy subprocess (elaborating a Mathlib import chain).
# Firing off one per step with no cap causes them to contend for CPU/disk —
# see settings.lean_concurrency_limit (config.py) for the machine-dependent
# tuning story. The cap is a single module-level semaphore shared across
# every step *and* every ensemble candidate within a step, so fanning out
# more candidates per step (below) never raises the true concurrent-
# subprocess count above this limit — it just changes what fills the slots.
_lean_semaphore = asyncio.Semaphore(settings.lean_concurrency_limit)

# Measured directly on this branch (Phase 0 baseline): most of a proof's wall
# time was steps burning all of a *sequential* single-attempt-then-repair
# loop without ever converging. Generating a few independent candidates
# concurrently up front (this is the "ensemble" — different attempts at the
# same step, run in parallel) converts several of those sequential
# Claude-then-Lean round trips into one parallel round, and only falls back
# to sequential repair if every candidate in the round fails. Size is derived
# from formalize.ENSEMBLE_STRATEGIES so the two never drift out of sync; total
# Lean subprocess invocations per step are still capped (ENSEMBLE_SIZE +
# MAX_REPAIR_ROUNDS) so cost doesn't grow unbounded — deduplication (below)
# keeps the effective count lower still whenever candidates converge.
ENSEMBLE_SIZE = len(ENSEMBLE_STRATEGIES)
MAX_REPAIR_ROUNDS = 2

_IMPORT_FAILURE_MARKERS = ("unknown module", "unknown identifier", "does not exist")


def _code_hash(code: str) -> str:
    """Whitespace-normalized hash so cosmetic differences (indentation,
    trailing newlines) don't defeat dedup — measured directly: "diverse"
    ensemble candidates were frequently byte-identical or identical up to
    whitespace, burning a Lean subprocess slot to re-verify the same code."""
    normalized = " ".join(code.split())
    return hashlib.sha256(normalized.encode()).hexdigest()


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


def _looks_like_import_failure(result: VerdictResult) -> bool:
    out = result.evidence.raw_output.lower()
    return any(marker in out for marker in _IMPORT_FAILURE_MARKERS)


async def _verify_lean_code(step_id: str, code: str, attempt_tag: str, timeout: float) -> VerdictResult:
    wait_start = time.monotonic()
    async with _lean_semaphore:
        wait_s = time.monotonic() - wait_start
        # .check() runs a blocking subprocess.run() — calling it directly
        # here would block the *entire* event loop, not just this task,
        # serializing every concurrent step.
        check_start = time.monotonic()
        try:
            result = await asyncio.to_thread(_lean_verifier.check, code, timeout)
        except Exception as exc:  # noqa: BLE001 - never crash the stream
            result = VerdictResult(
                verdict=Verdict.UNVERIFIED,
                verifier=None,
                evidence=Evidence(raw_output=f"Verifier crashed: {exc}", exit_code=None),
            )
        check_s = time.monotonic() - check_start

    _timing_logger.info(
        "lean_check step=%s attempt=%s semaphore_wait_s=%.2f check_s=%.2f verdict=%s imports=%s",
        step_id, attempt_tag, wait_s, check_s, result.verdict.value, _lean_imports(code),
    )
    return result


async def _repair_lean(
    step: Step,
    code: str,
    result: VerdictResult,
    tried: dict[str, VerdictResult],
    dependency_statements: list[tuple[str, str]],
) -> Step:
    """Sequential fallback once no ensemble candidate verified (§8.3's
    repair loop — Lean's compiler is the adversary). Only reached for
    syntax/tactic-level failures, never for a genuine mathematical REFUTED.
    `tried` carries forward every (whitespace-normalized) candidate hash
    already checked this step (ensemble round + earlier repair rounds) so a
    repaired attempt that converges back to something already tried reuses
    that result instead of paying for another Lean subprocess.
    """
    for attempt in range(1, MAX_REPAIR_ROUNDS + 1):
        repair_start = time.monotonic()
        try:
            code = await formalize_lean_repair(
                step.statement, code, result.evidence.raw_output, dependency_statements=dependency_statements
            )
        except Exception:  # noqa: BLE001 - repair call failing just ends the loop early
            return step
        finally:
            _timing_logger.info(
                "lean_repair_call step=%s attempt=%d duration_s=%.2f",
                step.id, attempt, time.monotonic() - repair_start,
            )

        step.formalization = Formalization(lean_code=code, attempts=ENSEMBLE_SIZE + attempt)

        code_hash = _code_hash(code)
        if code_hash in tried:
            result = tried[code_hash]
            _timing_logger.info(
                "lean_check step=%s attempt=repair-%d verdict=%s (deduped, reused prior result)",
                step.id, attempt, result.verdict.value,
            )
        else:
            result = await _verify_lean_code(
                step.id, code, f"repair-{attempt}", settings.lean_timeout_repair
            )
            tried[code_hash] = result

        step.verdict = result.verdict
        step.verifier = result.verifier
        step.evidence = result.evidence

        if result.verdict == Verdict.VERIFIED or not _is_retryable(result):
            return step

    return step


async def _generate_and_verify_lean(
    step: Step, dependency_statements: list[tuple[str, str]]
) -> Step:
    """The ensemble round: ENSEMBLE_SIZE independent candidate
    formalizations generated concurrently (each following a distinct
    strategy brief — see formalize.ENSEMBLE_STRATEGIES — rather than a
    generic "try something different" nudge, which measurably produced
    near-duplicate candidates), verified concurrently (still gated by
    `_lean_semaphore`), first VERIFIED wins. Byte-for-byte (modulo
    whitespace) duplicate candidates are only ever sent to Lean once and
    share the result. If none verify, repair proceeds sequentially from
    whichever failure looks most informative — a tactic/proof-shape failure
    is preferred over an import-path guess, since the former means a closer
    miss worth handing to the repair loop.
    """
    if settings.enable_proof_cache:
        cached_code = await proof_cache.get_cached_lean_code(step.statement, dependency_statements)
        if cached_code is not None:
            # A cache hit still pays for one real Lean check before being
            # trusted — "verifiers dispose" applies to our own cache too;
            # Mathlib may have moved a lemma since this was cached.
            cache_start = time.monotonic()
            result = await _verify_lean_code(step.id, cached_code, "cache-hit", settings.lean_timeout_repair)
            _timing_logger.info(
                "proof_cache_check step=%s verdict=%s duration_s=%.2f",
                step.id, result.verdict.value, time.monotonic() - cache_start,
            )
            if result.verdict == Verdict.VERIFIED:
                step.formalization = Formalization(lean_code=cached_code, attempts=1)
                step.verdict = result.verdict
                step.verifier = result.verifier
                step.evidence = result.evidence
                return step
            await proof_cache.evict(step.statement, dependency_statements)

    formalize_start = time.monotonic()
    try:
        candidates = await asyncio.gather(
            *(
                formalize_lean(step.statement, strategy_hint=hint, dependency_statements=dependency_statements)
                for hint in ENSEMBLE_STRATEGIES
            )
        )
    except Exception as exc:  # noqa: BLE001 - must degrade to UNVERIFIED, never crash the stream
        step.formalization = Formalization(attempts=1)
        step.evidence = Evidence(raw_output=f"Formalization failed: {exc}", exit_code=None)
        step.verdict = Verdict.UNVERIFIED
        return step
    finally:
        _timing_logger.info(
            "formalize_ensemble step=%s candidates=%d duration_s=%.2f",
            step.id, ENSEMBLE_SIZE, time.monotonic() - formalize_start,
        )

    hashes = [_code_hash(c) for c in candidates]
    first_index_for_hash: dict[str, int] = {}
    unique_indices: list[int] = []
    for i, h in enumerate(hashes):
        if h not in first_index_for_hash:
            first_index_for_hash[h] = i
            unique_indices.append(i)

    if len(unique_indices) < len(candidates):
        _timing_logger.info(
            "ensemble_dedup step=%s candidates=%d unique=%d",
            step.id, len(candidates), len(unique_indices),
        )

    unique_results = await asyncio.gather(
        *(
            _verify_lean_code(step.id, candidates[i], f"ensemble-{i + 1}", settings.lean_timeout_ensemble)
            for i in unique_indices
        )
    )
    result_by_index = dict(zip(unique_indices, unique_results))
    results = [result_by_index[first_index_for_hash[h]] for h in hashes]
    tried = {h: r for h, r in zip(hashes, results)}

    for code, result in zip(candidates, results):
        if result.verdict == Verdict.VERIFIED:
            step.formalization = Formalization(lean_code=code, attempts=1)
            step.verdict = result.verdict
            step.verifier = result.verifier
            step.evidence = result.evidence
            if settings.enable_proof_cache:
                await proof_cache.store_verified(step.statement, dependency_statements, code)
            return step

    non_import_failures = [
        (code, result) for code, result in zip(candidates, results) if not _looks_like_import_failure(result)
    ]
    code, result = non_import_failures[0] if non_import_failures else (candidates[0], results[0])

    step.formalization = Formalization(lean_code=code, attempts=1)
    step.verdict = result.verdict
    step.verifier = result.verifier
    step.evidence = result.evidence

    if not _is_retryable(result):
        return step

    result_step = await _repair_lean(step, code, result, tried, dependency_statements)
    if (
        settings.enable_proof_cache
        and result_step.verdict == Verdict.VERIFIED
        and result_step.formalization is not None
    ):
        await proof_cache.store_verified(
            step.statement, dependency_statements, result_step.formalization.lean_code
        )
    return result_step


async def _formalize_and_verify(step: Step, dependency_statements: list[tuple[str, str]]) -> Step:
    step_start = time.monotonic()

    if step.classification == Classification.LEAN_CANDIDATE:
        result_step = await _generate_and_verify_lean(step, dependency_statements)

        if settings.enable_counterexample_probe and result_step.verdict == Verdict.UNVERIFIED:
            # Advisory only — see counterexample.py. This can only ever add
            # a note, never touch result_step.verdict.
            probe_start = time.monotonic()
            note = await probe_for_counterexample(result_step.statement)
            _timing_logger.info(
                "counterexample_probe step=%s found=%s duration_s=%.2f",
                step.id, note is not None, time.monotonic() - probe_start,
            )
            if note is not None:
                result_step.claude_notes.append(note)

        _timing_logger.info(
            "step_total step=%s classification=%s total_s=%.2f verdict=%s",
            step.id, step.classification.value, time.monotonic() - step_start, result_step.verdict.value,
        )
        return result_step

    formalize_start = time.monotonic()
    try:
        _, python_code = await formalize(
            step.classification, step.statement, dependency_statements=dependency_statements
        )
    except Exception as exc:  # noqa: BLE001 - must degrade to UNVERIFIED, never crash the stream
        step.formalization = Formalization(attempts=1)
        step.evidence = Evidence(raw_output=f"Formalization failed: {exc}", exit_code=None)
        step.verdict = Verdict.UNVERIFIED
        return step
    finally:
        _timing_logger.info(
            "formalize_call step=%s classification=%s duration_s=%.2f",
            step.id, step.classification.value, time.monotonic() - formalize_start,
        )

    step.formalization = Formalization(python_code=python_code, attempts=1)
    check_start = time.monotonic()
    try:
        result = await asyncio.to_thread(_sympy_verifier.check, python_code)
    except Exception as exc:  # noqa: BLE001
        step.evidence = Evidence(raw_output=f"Verifier crashed: {exc}", exit_code=None)
        step.verdict = Verdict.UNVERIFIED
        return step
    finally:
        _timing_logger.info(
            "sympy_check step=%s duration_s=%.2f", step.id, time.monotonic() - check_start,
        )

    step.verdict = result.verdict
    step.verifier = result.verifier
    step.evidence = result.evidence
    _timing_logger.info(
        "step_total step=%s classification=%s total_s=%.2f verdict=%s",
        step.id, step.classification.value, time.monotonic() - step_start, step.verdict.value,
    )
    return step


class PipelineState(TypedDict):
    normalized_source: str
    steps: Annotated[list[Step], operator.add]
    formalizable: list[Step]
    id_to_statement: dict[str, str]


class StepTask(TypedDict):
    step: Step
    dependency_statements: list[tuple[str, str]]


async def _decompose_node(state: PipelineState) -> dict:
    decompose_start = time.monotonic()
    raw_steps = await decompose(state["normalized_source"])
    _timing_logger.info(
        "decompose_call duration_s=%.2f steps=%d", time.monotonic() - decompose_start, len(raw_steps),
    )
    steps = [_build_step(raw, state["normalized_source"]) for raw in raw_steps]
    # PREMISE steps (ASSUMED, not a claim) and UNFORMALIZABLE steps (Claude
    # already said it can't formalize this) both skip straight to a terminal
    # verdict — see _SKIP_FORMALIZATION / _build_step above.
    skipped = [s for s in steps if s.classification in _SKIP_FORMALIZATION]
    formalizable = [s for s in steps if s.classification not in _SKIP_FORMALIZATION]
    id_to_statement = {s.id: s.statement for s in steps}
    return {"steps": skipped, "formalizable": formalizable, "id_to_statement": id_to_statement}


async def _process_step_node(state: StepTask) -> dict:
    return {"steps": [await _formalize_and_verify(state["step"], state["dependency_statements"])]}


def _fan_out(state: PipelineState) -> list[Send]:
    id_to_statement = state["id_to_statement"]
    sends = []
    for s in state["formalizable"]:
        dependency_statements = [
            (dep_id, id_to_statement[dep_id]) for dep_id in s.depends_on if dep_id in id_to_statement
        ]
        sends.append(Send("process_step", {"step": s, "dependency_statements": dependency_statements}))
    return sends


def _build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("decompose", _decompose_node)
    graph.add_node("process_step", _process_step_node)
    graph.add_edge(START, "decompose")
    graph.add_conditional_edges("decompose", _fan_out, ["process_step"])
    graph.add_edge("process_step", END)
    return graph.compile()


_graph = _build_graph()


async def run_real_pipeline(normalized_source: str) -> AsyncGenerator[Step, None]:
    pipeline_start = time.monotonic()
    steps_total = 0
    initial_state: PipelineState = {
        "normalized_source": normalized_source,
        "steps": [],
        "formalizable": [],
        "id_to_statement": {},
    }
    async for update in _graph.astream(initial_state, stream_mode="updates"):
        for partial in update.values():
            for step in partial.get("steps", []):
                steps_total += 1
                yield step

    _timing_logger.info(
        "pipeline_total duration_s=%.2f steps_total=%d", time.monotonic() - pipeline_start, steps_total,
    )
