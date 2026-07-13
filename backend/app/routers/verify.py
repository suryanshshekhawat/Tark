"""POST /api/verify — ingest + validate, then stream step results via SSE.

Runs the real LaTeX validator (§4a) and the real Claude decompose/formalize
+ Lean/SymPy verify pipeline. If decomposition itself fails (no API key,
malformed Claude response, network error) that's a `pipeline_error` SSE
event — distinct from the 422 ingest error, since validation already
passed; this is a downstream failure, not a bad-input one.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from ..claude_client import ClaudeNotConfiguredError
from ..models.schema import VerifyRequest
from ..pipeline.advisory import run_advisory_pass
from ..pipeline.real_pipeline import run_real_pipeline
from ..pipeline.report import build_report
from ..validation.latex_validator import LatexValidator

router = APIRouter()
_validator = LatexValidator()
_logger = logging.getLogger(__name__)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/verify")
async def verify(request: VerifyRequest):
    result = _validator.validate(request.latex)
    if not result.ok:
        return JSONResponse(status_code=422, content=result.error.model_dump())

    async def event_stream() -> AsyncGenerator[str, None]:
        for repair in result.auto_repairs:
            yield _sse("auto_repair", repair.model_dump())

        steps = []
        try:
            async for step in run_real_pipeline(result.normalized_source):
                steps.append(step)
                yield _sse("step", step.model_dump())
        except ClaudeNotConfiguredError as exc:
            yield _sse("pipeline_error", {"message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - never let the stream die silently
            _logger.exception("Pipeline failed during decomposition")
            yield _sse("pipeline_error", {"message": f"Pipeline failed: {exc}"})
            return

        # Stage 6 (§6): whole-proof advisory notes, computed only after every
        # step has its final verdict, kept structurally separate from them.
        global_notes = await run_advisory_pass(result.normalized_source, steps)
        report = build_report(result.normalized_source, steps, claude_global_notes=global_notes)
        yield _sse("done", report.model_dump())

    return StreamingResponse(event_stream(), media_type="text/event-stream")
