"""Real LaTeX -> PDF compilation via a local pdflatex install (MiKTeX/TeX
Live). Deliberately not under verifiers/ — compiling a document never
produces a VERIFIED/REFUTED verdict, it's a rendering concern only. See
CONSTRUCTION_PLAN.md's core principle.

If the user's pasted LaTeX already has \\begin{document}, it's compiled
verbatim — their real preamble (\\title, \\newtheorem, custom macros, ...)
is honored exactly, with zero custom parsing on our side. A bare fragment
(no preamble at all — the common case for the pre-loaded examples) gets
wrapped in a minimal default preamble before compiling.

Highlight-box geometry is not this module's concern: the frontend matches
each step's source_span against the compiled PDF's own text layer directly
(frontend/src/textLayerMatch.ts) rather than this module tracking a
source-offset-to-compiled-file mapping (an earlier SyncTeX-based approach
here, retired — SyncTeX's box granularity turned out to be per-line for
running prose, not per-character, which isn't enough to separate multiple
statements sharing one source line).
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parents[2] / ".tark_pdf_cache"
DEFAULT_TIMEOUT = 45.0  # first use of an as-yet-uncached package triggers a
# MiKTeX network fetch — slower than a warm compile. Same "first call is
# slower" characteristic already documented for Lean in lean_verifier.py.

_DEFAULT_PREAMBLE = (
    "\\documentclass[11pt]{article}\n"
    "\\usepackage{amsmath,amssymb,amsthm}\n"
    "\\begin{document}\n"
)
_DEFAULT_POSTAMBLE = "\n\\end{document}\n"

_PAGE_COUNT_RE = re.compile(r"Output written on .*\((\d+) pages?,")


@dataclass
class CompiledDoc:
    doc_id: str
    dir: Path
    tex_path: Path
    pdf_path: Path
    page_count: int


@dataclass
class CompileFailure:
    message: str
    log: str = ""


def _doc_id(raw_latex: str) -> str:
    return hashlib.sha256(raw_latex.encode("utf-8")).hexdigest()[:24]


def _build_document(raw_latex: str) -> str:
    if "\\begin{document}" in raw_latex:
        return raw_latex
    return _DEFAULT_PREAMBLE + raw_latex + _DEFAULT_POSTAMBLE


def _extract_page_count(stdout: str) -> int | None:
    m = _PAGE_COUNT_RE.search(stdout)
    return int(m.group(1)) if m else None


def _load_cached(doc_id: str) -> CompiledDoc | None:
    doc_dir = CACHE_DIR / doc_id
    pdf_path = doc_dir / "doc.pdf"
    tex_path = doc_dir / "doc.tex"
    meta_path = doc_dir / "meta.txt"
    if not (pdf_path.exists() and meta_path.exists()):
        return None
    page_count_str = meta_path.read_text(encoding="utf-8").strip()
    return CompiledDoc(
        doc_id=doc_id,
        dir=doc_dir,
        tex_path=tex_path,
        pdf_path=pdf_path,
        page_count=int(page_count_str),
    )


def get_cached(doc_id: str) -> CompiledDoc | None:
    """Look up an already-compiled doc by id, without compiling anything."""
    return _load_cached(doc_id)


def compile_document(raw_latex: str, timeout: float = DEFAULT_TIMEOUT) -> CompiledDoc | CompileFailure:
    doc_id = _doc_id(raw_latex)
    cached = _load_cached(doc_id)
    if cached is not None:
        return cached

    doc_dir = CACHE_DIR / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    tex_path = doc_dir / "doc.tex"
    pdf_path = doc_dir / "doc.pdf"
    meta_path = doc_dir / "meta.txt"

    tex_path.write_text(_build_document(raw_latex), encoding="utf-8")

    try:
        proc = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "doc.tex"],
            cwd=str(doc_dir),
            capture_output=True,
            # Without an explicit encoding, Windows decodes subprocess
            # output with the OS locale codec (cp1252), which can't
            # represent LaTeX's own log-file box-drawing/accented output —
            # same class of bug already fixed for lean_verifier.py and
            # sympy_verifier.py; see CLAUDE.md.
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(doc_dir, ignore_errors=True)
        return CompileFailure(
            message=f"LaTeX compilation timed out after {timeout}s.",
            log=(exc.stdout or "") + (exc.stderr or ""),
        )
    except FileNotFoundError:
        shutil.rmtree(doc_dir, ignore_errors=True)
        return CompileFailure(
            message="pdflatex was not found on PATH — no LaTeX toolchain is installed on this machine.",
        )

    if proc.returncode != 0 or not pdf_path.exists():
        log = (proc.stdout or "") + (proc.stderr or "")
        shutil.rmtree(doc_dir, ignore_errors=True)
        return CompileFailure(message="LaTeX failed to compile.", log=log)

    page_count = _extract_page_count(proc.stdout) or 1
    meta_path.write_text(f"{page_count}\n", encoding="utf-8")

    return CompiledDoc(doc_id=doc_id, dir=doc_dir, tex_path=tex_path, pdf_path=pdf_path, page_count=page_count)
