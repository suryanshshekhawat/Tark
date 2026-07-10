"""POST /api/verify — ingest + validate, then stream step results via SSE.

Days 1-2 scope: runs the real LaTeX validator (§4a) but streams *mocked*
step data (mock_pipeline) since Claude/Lean aren't wired in yet. Swapping
run_mock_pipeline for the real pipeline is the only change needed later —
that's the point of keeping this endpoint thin.
"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from ..models.schema import VerifyRequest
from ..pipeline.mock_pipeline import build_report, run_mock_pipeline
from ..validation.latex_validator import LatexValidator

router = APIRouter()
_validator = LatexValidator()


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
        async for step in run_mock_pipeline(result.normalized_source):
            steps.append(step)
            yield _sse("step", step.model_dump())

        report = build_report(result.normalized_source, steps)
        yield _sse("done", report.model_dump())

    return StreamingResponse(event_stream(), media_type="text/event-stream")
