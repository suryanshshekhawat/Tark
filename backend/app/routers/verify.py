"""POST /api/verify — ingest + validate, then stream step results via SSE.

Runs the real LaTeX validator (§4a) and the real Claude decompose/formalize
+ Lean/SymPy verify pipeline. If decomposition itself fails (no API key,
malformed Claude response, network error) that's a `pipeline_error` SSE
event — distinct from the 422 ingest error, since validation already
passed; this is a downstream failure, not a bad-input one.

No PDF/rendering concerns here — /api/compile (routers/compile.py) owns
compilation, and highlight-box geometry is computed entirely client-side by
matching each step's source_span against the compiled PDF's own text layer
(frontend/src/textLayerMatch.ts), not by anything in this pipeline.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from ..claude_client import ClaudeNotConfiguredError
from ..models.schema import (
    Classification,
    DecompositionSummary,
    Evidence,
    Step,
    StepAttempt,
    Verdict,
    VerifyRequest,
)
from ..pipeline.advisory import run_advisory_pass
from ..pipeline.real_pipeline import decompose_steps, retry_step, run_verification
from ..pipeline.report import build_report
from ..validation.latex_validator import LatexValidator

router = APIRouter()
_validator = LatexValidator()
_logger = logging.getLogger(__name__)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _tally(steps: list[Step]) -> tuple[int, int, int]:
    assumptions = sum(1 for s in steps if s.classification == Classification.PREMISE)
    computational = sum(1 for s in steps if s.classification == Classification.COMPUTATIONAL)
    verifiable = len(steps) - assumptions - computational
    return assumptions, verifiable, computational


@router.post("/verify")
async def verify(request: VerifyRequest):
    result = _validator.validate(request.latex)
    if not result.ok:
        return JSONResponse(status_code=422, content=result.error.model_dump())

    async def event_stream() -> AsyncGenerator[str, None]:
        for repair in result.auto_repairs:
            yield _sse("auto_repair", repair.model_dump())

        try:
            steps = await decompose_steps(result.normalized_source)
        except ClaudeNotConfiguredError as exc:
            yield _sse("pipeline_error", {"message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - never let the stream die silently
            _logger.exception("Pipeline failed during decomposition")
            yield _sse("pipeline_error", {"message": f"Pipeline failed: {exc}"})
            return

        assumptions, verifiable, computational = _tally(steps)
        yield _sse(
            "decomposition",
            DecompositionSummary(
                total=len(steps),
                assumptions=assumptions,
                verifiable=verifiable,
                computational=computational,
                normalized_source=result.normalized_source,
                steps=steps,
            ).model_dump(),
        )

        try:
            async for item in run_verification(steps):
                if isinstance(item, StepAttempt):
                    yield _sse("step_attempt", item.model_dump())
                else:
                    yield _sse("step", item.model_dump())
        except Exception as exc:  # noqa: BLE001 - never let the stream die silently
            _logger.exception("Pipeline failed during verification")
            yield _sse("pipeline_error", {"message": f"Pipeline failed: {exc}"})
            return

        # Stage 6 (§6): whole-proof advisory notes, computed only after every
        # step has its final verdict, kept structurally separate from them.
        global_notes = await run_advisory_pass(result.normalized_source, steps)
        report = build_report(result.normalized_source, steps, claude_global_notes=global_notes)
        yield _sse("done", report.model_dump())

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/verify/retry")
async def retry(step: Step):
    """Re-run formalize+verify for a single step (a UI "retry" click on a
    failed statement), not the whole proof. Takes the step as currently held
    by the frontend and streams the same `step_attempt`/`step` events as
    `/verify` (just for this one step) so the UI can show attempt progress
    live instead of only learning the outcome once the whole repair loop
    finishes.
    """

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            async for item in retry_step(step):
                if isinstance(item, StepAttempt):
                    yield _sse("step_attempt", item.model_dump())
                else:
                    yield _sse("step", item.model_dump())
        except Exception as exc:  # noqa: BLE001 - degrade, don't kill the stream
            _logger.exception("Retry failed for step %s", step.id)
            step.evidence = Evidence(raw_output=f"Retry crashed: {exc}", exit_code=None)
            step.verdict = Verdict.UNVERIFIED
            yield _sse("step", step.model_dump())

    return StreamingResponse(event_stream(), media_type="text/event-stream")
