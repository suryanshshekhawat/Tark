import asyncio

import pytest

from app.pipeline import proof_cache


@pytest.fixture(autouse=True)
def _isolated_cache_db(tmp_path, monkeypatch):
    """Never touch the real backend/tark_cache.sqlite3 from tests."""
    monkeypatch.setattr(proof_cache, "DB_PATH", tmp_path / "test_cache.sqlite3")


def test_miss_returns_none():
    result = asyncio.run(proof_cache.get_cached_lean_code("gcd(p, q) = 1", []))
    assert result is None


def test_store_then_hit_returns_same_code():
    async def _run():
        await proof_cache.store_verified("gcd(p, q) = 1", [], "theorem t : True := trivial")
        return await proof_cache.get_cached_lean_code("gcd(p, q) = 1", [])

    assert asyncio.run(_run()) == "theorem t : True := trivial"


def test_different_dependency_context_is_a_different_cache_key():
    """The same statement proved under different hypotheses is a different
    claim — must not collide in the cache."""

    async def _run():
        await proof_cache.store_verified("p is even", [("S1", "p^2 = 2*q^2")], "code-a")
        return await proof_cache.get_cached_lean_code("p is even", [("S1", "p^2 = 3*q^2")])

    assert asyncio.run(_run()) is None


def test_dependency_order_does_not_affect_cache_key():
    async def _run():
        await proof_cache.store_verified(
            "combined claim", [("S1", "a"), ("S2", "b")], "code-x"
        )
        return await proof_cache.get_cached_lean_code("combined claim", [("S2", "b"), ("S1", "a")])

    assert asyncio.run(_run()) == "code-x"


def test_eviction_removes_entry():
    async def _run():
        await proof_cache.store_verified("claim", [], "code")
        await proof_cache.evict("claim", [])
        return await proof_cache.get_cached_lean_code("claim", [])

    assert asyncio.run(_run()) is None


def test_store_overwrites_existing_entry():
    async def _run():
        await proof_cache.store_verified("claim", [], "old-code")
        await proof_cache.store_verified("claim", [], "new-code")
        return await proof_cache.get_cached_lean_code("claim", [])

    assert asyncio.run(_run()) == "new-code"
