"""Maps a step's source_span (char offsets into normalized_source) to
highlight boxes on the compiled PDF via SyncTeX — no fuzzy text matching.
SyncTeX is the compiler's own record of where each source line ended up on
the typeset page (`synctex view -i "line:col:file" -o file.pdf`), which is
exact by construction. See latex_compiler.py's `body_offset` for how a
normalized_source offset lines up with a real line in the compiled file.

Coordinate note: SyncTeX reports each box's (h, v) reference point plus
(W, H) width/height, with v as the box's baseline in a top-left-origin,
y-down page coordinate system (TeX "big points", 1bp = 1/72in = 1 PDF
point). The rect used here — left=h, top=v-H, width=W, height=H — was
confirmed against real rendered output during implementation; if boxes ever
look vertically offset against a newly-tested MiKTeX/TeX Live version,
re-check that assumption first.
"""
from __future__ import annotations

import re
import subprocess

from ..models.schema import PdfBox, Step
from .latex_compiler import CompiledDoc

SYNCTEX_TIMEOUT = 10.0

_BOX_BLOCK_RE = re.compile(
    r"Page:(\d+)\s*\n"
    r"x:([\-\d.]+)\s*\n"
    r"y:([\-\d.]+)\s*\n"
    r"h:([\-\d.]+)\s*\n"
    r"v:([\-\d.]+)\s*\n"
    r"W:([\-\d.]+)\s*\n"
    r"H:([\-\d.]+)"
)


def _line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _boxes_for_line(doc: CompiledDoc, line: int) -> list[PdfBox]:
    try:
        proc = subprocess.run(
            ["synctex", "view", "-i", f"{line}:1:{doc.tex_path}", "-o", str(doc.pdf_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SYNCTEX_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    if proc.returncode != 0:
        return []

    boxes: list[PdfBox] = []
    for m in _BOX_BLOCK_RE.finditer(proc.stdout):
        page_s, _x, _y, h, v, w, hh = m.groups()
        boxes.append(
            PdfBox(page=int(page_s), x=float(h), y=float(v) - float(hh), w=float(w), h=float(hh))
        )
    return boxes


def boxes_for_span(doc: CompiledDoc, start: int, end: int) -> list[PdfBox]:
    """start/end are char offsets into normalized_source. Never raises —
    returns [] if the span is empty or synctex can't locate it, same as any
    other "couldn't confidently locate this" case in the pipeline (compare
    span_matching.py's zero-length-span fallback)."""
    if end <= start:
        return []

    raw_start = doc.body_offset + start
    raw_end = doc.body_offset + end
    first_line = _line_for_offset(doc.compiled_text, raw_start)
    last_line = _line_for_offset(doc.compiled_text, max(raw_start, raw_end - 1))

    boxes: list[PdfBox] = []
    seen: set[tuple[int, float, float, float, float]] = set()
    for line in range(first_line, last_line + 1):
        for box in _boxes_for_line(doc, line):
            # synctex returns overlapping char/word/line-granularity blocks
            # per query — dedupe identical rects so the frontend doesn't
            # stack redundant overlay divs.
            key = (box.page, round(box.x, 2), round(box.y, 2), round(box.w, 2), round(box.h, 2))
            if key in seen:
                continue
            seen.add(key)
            boxes.append(box)
    return boxes


def _box_key(b: PdfBox) -> tuple[int, float, float, float, float]:
    return (b.page, round(b.x, 2), round(b.y, 2), round(b.w, 2), round(b.h, 2))


def deoverlap_boxes(steps: list[Step]) -> None:
    """SyncTeX's box granularity is pdfTeX's own — for running prose that's
    one box per typeset line, not per character or word (confirmed directly:
    querying the same line at different columns returns identical boxes).
    So when several steps' claims sit on the same source line (a compact
    proof like "gcd(48,18)=6. Also, 1000003 is prime. However, ..."), they
    all get the *same* box from boxes_for_span, and drawing each highlight
    at full width makes them stack into one solid, unreadable blob instead
    of separate regions.

    There's no way to ask SyncTeX for sub-line geometry, but the pipeline
    already knows each step's exact source_span, which gives their reading
    order and relative length on that line. This slices a shared box
    horizontally among the steps that share it, proportional to each step's
    span length, in source order — an approximation (source character count
    isn't exactly proportional to rendered glyph width, especially across
    math mode), but a real visual separation instead of a full overlap.
    Mutates steps' pdf_boxes in place; call once, after every step's boxes
    are already attached.
    """
    groups: dict[tuple[int, float, float, float, float], list[int]] = {}
    for idx, step in enumerate(steps):
        for box in step.pdf_boxes or []:
            groups.setdefault(_box_key(box), []).append(idx)

    for key, idxs in groups.items():
        unique_idxs = sorted(set(idxs), key=lambda i: steps[i].source_span.start)
        if len(unique_idxs) <= 1:
            continue

        total_len = sum(
            max(1, steps[i].source_span.end - steps[i].source_span.start) for i in unique_idxs
        )
        page, x, y, w, h = key
        cursor = 0.0
        for i in unique_idxs:
            span_len = max(1, steps[i].source_span.end - steps[i].source_span.start)
            frac = span_len / total_len
            sliced = PdfBox(page=page, x=x + cursor * w, y=y, w=frac * w, h=h)
            steps[i].pdf_boxes = [
                sliced if _box_key(b) == key else b for b in (steps[i].pdf_boxes or [])
            ]
            cursor += frac
