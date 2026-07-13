"""Cross-request cache of VERIFIED Lean formalizations.

CONSTRUCTION_PLAN.md §14 says "no storage for v1" — this is a deliberate,
user-approved exception, scoped narrowly: it caches only Lean *code* that
has already been mechanically VERIFIED once, keyed on the exact statement +
dependency context it was proved under. It is the seed of the roadmap's
"persistent knowledge archive" (§13) and, pragmatically, makes repeat runs
of the same/similar proofs (a demo re-run, a user re-submitting after a
typo elsewhere in the proof) far cheaper and immune to live-Lean flakiness.

Critically, a cache hit is never trusted blindly — "Claude proposes,
verifiers dispose" applies to this cache's own contents too, since Mathlib
can move a lemma between when an entry was cached and when it's read back.
Every hit still pays for exactly one real Lean subprocess check before
being used; a hit that fails to re-verify is evicted and the caller falls
through to the normal formalization path, never silently trusted.
"""
from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[3] / "backend" / "tark_cache.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS verified_proofs (
    cache_key TEXT PRIMARY KEY,
    statement TEXT NOT NULL,
    lean_code TEXT NOT NULL,
    created_at REAL NOT NULL
)
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_SCHEMA)
    return conn


def _cache_key(statement: str, dependency_statements: list[tuple[str, str]]) -> str:
    """Keyed on statement + dependency *content* (not step ids, which are
    only stable within one decomposition) — sorted so dependency order
    doesn't produce spurious cache misses for an otherwise-identical claim.
    """
    normalized_statement = " ".join(statement.split())
    normalized_deps = sorted(" ".join(dep_statement.split()) for _, dep_statement in dependency_statements)
    payload = normalized_statement + "\n" + "\n".join(normalized_deps)
    return hashlib.sha256(payload.encode()).hexdigest()


def _get_sync(statement: str, dependency_statements: list[tuple[str, str]]) -> str | None:
    key = _cache_key(statement, dependency_statements)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT lean_code FROM verified_proofs WHERE cache_key = ?", (key,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _store_sync(statement: str, dependency_statements: list[tuple[str, str]], lean_code: str) -> None:
    key = _cache_key(statement, dependency_statements)
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO verified_proofs (cache_key, statement, lean_code, created_at) "
            "VALUES (?, ?, ?, ?)",
            (key, statement, lean_code, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def _evict_sync(statement: str, dependency_statements: list[tuple[str, str]]) -> None:
    key = _cache_key(statement, dependency_statements)
    conn = _connect()
    try:
        conn.execute("DELETE FROM verified_proofs WHERE cache_key = ?", (key,))
        conn.commit()
    finally:
        conn.close()


async def get_cached_lean_code(statement: str, dependency_statements: list[tuple[str, str]]) -> str | None:
    """sqlite3 is blocking — routed through asyncio.to_thread like every
    other blocking I/O call in this pipeline, never called directly inside
    an async def."""
    return await asyncio.to_thread(_get_sync, statement, dependency_statements)


async def store_verified(statement: str, dependency_statements: list[tuple[str, str]], lean_code: str) -> None:
    await asyncio.to_thread(_store_sync, statement, dependency_statements, lean_code)


async def evict(statement: str, dependency_statements: list[tuple[str, str]]) -> None:
    await asyncio.to_thread(_evict_sync, statement, dependency_statements)
