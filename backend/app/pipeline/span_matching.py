"""Locate a Claude-quoted anchor substring in the normalized source.

CONSTRUCTION_PLAN.md §10a: offset drift from an LLM is the *common* case,
not an edge case, so Claude is only ever asked for a quoted anchor_text
(never asked to count characters), and this fuzzy-match fallback is built
from day one rather than bolted on later.
"""
from __future__ import annotations

import difflib

from ..models.schema import SourceSpan

FUZZY_MATCH_THRESHOLD = 0.7


def find_span(source: str, anchor_text: str | None) -> SourceSpan:
    """Never raises. A step with no confidently-locatable span still
    renders — it just has start == end, so the frontend skips the
    highlight instead of showing a wrong one.
    """
    if not anchor_text:
        return SourceSpan(start=0, end=0, anchor_text=None)

    exact_idx = source.find(anchor_text)
    if exact_idx != -1:
        return SourceSpan(
            start=exact_idx, end=exact_idx + len(anchor_text), anchor_text=anchor_text
        )

    window = len(anchor_text)
    if window == 0 or window > len(source):
        return SourceSpan(start=0, end=0, anchor_text=anchor_text)

    best_ratio = 0.0
    best_start = 0
    matcher = difflib.SequenceMatcher(a=anchor_text, autojunk=False)
    stride = max(1, window // 8)  # coarse stride — good enough for proof-sized sources
    for i in range(0, len(source) - window + 1, stride):
        matcher.set_seq2(source[i : i + window])
        # quick_ratio() overcounts shared-letter English text (it ignores
        # order), which false-positives on unrelated prose — use the real
        # ratio() here; windows are proof-sized, so this stays cheap.
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = i

    if best_ratio >= FUZZY_MATCH_THRESHOLD:
        return SourceSpan(start=best_start, end=best_start + window, anchor_text=anchor_text)

    return SourceSpan(start=0, end=0, anchor_text=anchor_text)
