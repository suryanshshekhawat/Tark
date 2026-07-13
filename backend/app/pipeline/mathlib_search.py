"""Mathlib lemma/import lookup via the public Loogle API.

Mathlib reorganizes its file layout often (LEAN_SYSTEM_PROMPT already warns
Claude about this in formalize.py) — a plausible import path or lemma name
Claude recalls from training data may no longer exist. Measured directly on
this branch: repair rounds are frequently burned either re-guessing import
paths (e.g. bouncing between `Mathlib.Analysis.Irrational` and
`Mathlib.Data.Real.Irrational` across attempts) or hand-rolling a tactic
proof for something Mathlib already has a lemma for, with a syntax mistake
in the process. Giving the formalization/repair agent a way to check what
actually exists *before* submitting to the (much slower) Lean subprocess
directly cuts down on both failure modes.

This is a read-only, outbound call to a third-party API made during the
Claude/agent formalization step — separate from the sandboxed Lean/SymPy
verifier subprocesses, which stay fully offline per CONSTRUCTION_PLAN.md §8.2/§9.
It must fail open: if Loogle is slow or unreachable, formalization proceeds
exactly as it did before this existed, never blocking the pipeline on a
third-party API being up.
"""
from __future__ import annotations

import time

import httpx

LOOGLE_URL = "https://loogle.lean-lang.org/json"
TIMEOUT = 4.0
MAX_RESULTS = 5

# Measured directly on this branch: identical queries (e.g. "irrational_sqrt_two",
# "Nat.even_pow") repeat a dozen+ times within one proof — every ensemble
# candidate and every repair round re-derives the same search independently.
# A short TTL cache turns those into free repeats without risking staleness
# (Mathlib doesn't move lemmas mid-request).
CACHE_TTL_S = 900.0
CACHE_MAX_ENTRIES = 512

# If Loogle is down, every one of these calls would otherwise pay a full
# TIMEOUT-second wait before failing open — across a dozen concurrent
# candidates that's real wall-clock, not just wasted network. After a few
# consecutive failures, stop trying for a cooldown window and fail open
# immediately; a later successful call resets the breaker.
BREAKER_FAILURE_THRESHOLD = 3
BREAKER_COOLDOWN_S = 60.0

_cache: dict[str, tuple[float, str]] = {}
_consecutive_failures = 0
_breaker_open_until = 0.0


def _cache_get(query: str) -> str | None:
    entry = _cache.get(query)
    if entry is None:
        return None
    expires_at, value = entry
    if time.monotonic() >= expires_at:
        del _cache[query]
        return None
    return value


def _cache_put(query: str, value: str) -> None:
    if len(_cache) >= CACHE_MAX_ENTRIES:
        # Cheap eviction: drop an arbitrary entry rather than tracking LRU —
        # this cache exists to absorb bursts of repeat queries within a
        # single proof, not to be a long-lived store.
        _cache.pop(next(iter(_cache)), None)
    _cache[query] = (time.monotonic() + CACHE_TTL_S, value)


async def search_mathlib(query: str) -> str:
    """Look up Mathlib lemmas/definitions matching `query` (a Loogle query —
    a name fragment like "Nat.gcd", or a type-shape pattern like
    "Even (?a ^ 2) -> Even ?a"). Returns a short text block of `name (module)
    : type` per hit, or a plain-text explanation if nothing was found or the
    lookup failed. Never raises — callers can treat the return value as
    always safe to feed back to Claude as a tool result.
    """
    global _consecutive_failures, _breaker_open_until

    cached = _cache_get(query)
    if cached is not None:
        return cached

    if time.monotonic() < _breaker_open_until:
        return "Mathlib search temporarily unavailable (recent failures) — proceed with your own best knowledge."

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(LOOGLE_URL, params={"q": query})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001 - fail open, never break formalization
        _consecutive_failures += 1
        if _consecutive_failures >= BREAKER_FAILURE_THRESHOLD:
            _breaker_open_until = time.monotonic() + BREAKER_COOLDOWN_S
        return f"Mathlib search unavailable ({type(exc).__name__}) — proceed with your own best knowledge."

    _consecutive_failures = 0

    if payload.get("error"):
        result = f"Mathlib search error: {payload['error']}"
        _cache_put(query, result)
        return result

    hits = payload.get("hits") or []
    if not hits:
        result = f"No Mathlib declarations found for query: {query}"
        _cache_put(query, result)
        return result

    lines = []
    for hit in hits[:MAX_RESULTS]:
        name = hit.get("name", "?")
        module = hit.get("module", "?")
        sig = (hit.get("type") or "").strip()
        lines.append(f"{name} (import {module}) : {sig}")
    result = "\n".join(lines)
    _cache_put(query, result)
    return result


SEARCH_MATHLIB_TOOL = {
    "name": "search_mathlib",
    "description": (
        "Search Mathlib for lemmas/definitions before writing Lean code, so you don't have to "
        "guess an import path or hand-roll a tactic proof for something that already exists. "
        "Accepts either a name fragment (e.g. \"Nat.even_pow\") or a Loogle type-shape pattern "
        "(e.g. \"Even (?a ^ 2) -> Even ?a\", using ?name for holes). Returns matching declaration "
        "names, their defining module (use this as the import path), and their type signature."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A Loogle search query: a name fragment or a type-shape pattern.",
            }
        },
        "required": ["query"],
    },
}
