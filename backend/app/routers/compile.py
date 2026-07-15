"""POST /api/compile — real LaTeX -> PDF compilation for the paper viewer.

Separate from /api/verify's pipeline entirely: compiling a document never
produces a verdict (see rendering/latex_compiler.py's module docstring).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from ..models.schema import CompileError, CompileRequest, CompileResult
from ..rendering.latex_compiler import CompileFailure, compile_document, get_cached

router = APIRouter()


@router.post("/compile")
async def compile_latex(request: CompileRequest):
    result = await asyncio.to_thread(compile_document, request.latex)
    if isinstance(result, CompileFailure):
        return JSONResponse(
            status_code=422,
            content=CompileError(message=result.message, log=result.log).model_dump(),
        )
    return CompileResult(doc_id=result.doc_id, page_count=result.page_count)


@router.get("/compile/{doc_id}/pdf")
async def get_compiled_pdf(doc_id: str):
    doc = await asyncio.to_thread(get_cached, doc_id)
    if doc is None:
        return JSONResponse(status_code=404, content={"message": "No compiled document with that id."})
    return FileResponse(doc.pdf_path, media_type="application/pdf")
