"""POST /api/verify — ingest + validate, then stream step results via SSE.

Runs the real LaTeX validator (§4a) and the real Claude decompose/formalize
+ Lean/SymPy verify pipeline. If decomposition itself fails (no API key,
malformed Claude response, network error) that's a `pipeline_error` SSE
event — distinct from the 422 ingest error, since validation already
passed; this is a downstream failure, not a bad-input one.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from ..claude_client import ClaudeNotConfiguredError
from ..models.schema import Classification, DecompositionSummary, Step, VerifyRequest
from ..pipeline.advisory import run_advisory_pass
from ..pipeline.real_pipeline import decompose_steps, run_verification
from ..pipeline.report import build_report
from ..rendering.latex_compiler import CompiledDoc, CompileFailure, compile_document
from ..rendering.synctex_lookup import boxes_for_span, deoverlap_boxes
from ..validation.latex_validator import LatexValidator

router = APIRouter()
_validator = LatexValidator()
_logger = logging.getLogger(__name__)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _attach_pdf_boxes(step: Step, compiled_doc: CompiledDoc | None) -> None:
    if compiled_doc is None:
        return
    try:
        boxes = await asyncio.to_thread(
            boxes_for_span, compiled_doc, step.source_span.start, step.source_span.end
        )
        if boxes:
            step.pdf_boxes = boxes
    except Exception:  # noqa: BLE001 - a rendering lookup must never break verification
        _logger.exception("SyncTeX box lookup failed for step %s", step.id)


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

        # PDF compilation is a rendering nicety, not a pipeline requirement —
        # a compile failure (e.g. an exotic package) must never block
        # verification itself. Same request.latex, same content-hash cache
        # /api/compile would have already populated if the frontend called
        # it during the preview step, so this is normally a cache hit.
        compiled_doc = None
        try:
            compile_result = await asyncio.to_thread(compile_document, request.latex)
            if not isinstance(compile_result, CompileFailure):
                compiled_doc = compile_result
        except Exception:  # noqa: BLE001 - rendering must never break verification
            _logger.exception("PDF compilation failed unexpectedly during verify")

        try:
            steps = await decompose_steps(result.normalized_source)
        except ClaudeNotConfiguredError as exc:
            yield _sse("pipeline_error", {"message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - never let the stream die silently
            _logger.exception("Pipeline failed during decomposition")
            yield _sse("pipeline_error", {"message": f"Pipeline failed: {exc}"})
            return

        # Computed once, immediately, on the true full step list — not
        # per-step later — so both the decomposition event below and every
        # subsequent `step` event (same Step objects, mutated in place by
        # run_verification) already carry pdf_boxes from the start.
        for step in steps:
            await _attach_pdf_boxes(step, compiled_doc)
        deoverlap_boxes(steps)

        assumptions, verifiable, computational = _tally(steps)
        yield _sse(
            "decomposition",
            DecompositionSummary(
                total=len(steps),
                assumptions=assumptions,
                verifiable=verifiable,
                computational=computational,
                steps=steps,
            ).model_dump(),
        )

        try:
            async for step in run_verification(steps):
                yield _sse("step", step.model_dump())
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
