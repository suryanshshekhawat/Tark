from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5"

    # How many Lean subprocess checks may run concurrently across the whole
    # pipeline (shared by every step and every ensemble candidate within a
    # step — see real_pipeline.py). The right number is machine-dependent,
    # not a universal constant: on the original dev machine (fewer cores,
    # slower disk), 11 concurrent checks measured 10/10 timeouts, hence the
    # conservative default of 3. On a 14-core machine with a warm Mathlib
    # cache (checks completing in 1-5s, this branch's dev/test environment),
    # raising this to 6-10 measurably reduced total wall-clock time once
    # ensemble candidate generation (3x the concurrent check load per step)
    # was introduced — tune this per deployment rather than trusting either
    # number blindly.
    lean_concurrency_limit: int = 3

    # Two timeout tiers instead of one flat 30s: ensemble-round candidates are
    # a first attempt with no evidence yet that they're close, so a hung one
    # shouldn't hold a semaphore slot ~10x longer than the p95 useful check
    # (warm checks measured at 1-5s on this branch's dev machine) — a slower
    # deadline here mostly just delays discovering the other candidates
    # already succeeded. Repair rounds get the original, more generous
    # budget since by then there's a specific, targeted fix being attempted.
    lean_timeout_ensemble: float = 15.0
    lean_timeout_repair: float = 30.0

    # Cap on simultaneous in-flight Claude API calls across the whole
    # process. Without this, a single proof with many steps × ENSEMBLE_SIZE
    # candidates can fire dozens of concurrent requests, risking a 429
    # rate-limit storm from one user's one request. Independent of (not a
    # replacement for) lean_concurrency_limit, which caps Lean subprocesses.
    claude_concurrency_limit: int = 8
    claude_max_retries: int = 3

    # Cross-request cache of VERIFIED Lean formalizations (see
    # pipeline/proof_cache.py) — a deliberate, narrow exception to
    # CONSTRUCTION_PLAN.md §14's "no storage for v1". A cache hit still pays
    # for one real Lean re-check before being trusted; it never bypasses
    # verification, only skips redundant Claude calls for a
    # statement+dependencies combination already proved once.
    enable_proof_cache: bool = True

    # Advisory-only: search for a concrete counterexample when a Lean-
    # candidate step ends UNVERIFIED. Never changes the verdict (see
    # pipeline/counterexample.py) — only ever adds a labeled note.
    enable_counterexample_probe: bool = True


settings = Settings()
