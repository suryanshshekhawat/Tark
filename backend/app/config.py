from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolved relative to this file, not the process's cwd, so it's found
# regardless of the directory `uvicorn`/pytest/etc. was launched from.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5"

    # How many Lean subprocess checks may run concurrently across the whole
    # pipeline (shared by every step and every ensemble candidate within a
    # step — see real_pipeline.py). The right number is machine-dependent,
    # not a universal constant — three independent data points, all
    # measured directly rather than assumed:
    #   - 11 concurrent checks -> 10/10 timeouts on the original dev machine.
    #   - On a *memory*-constrained machine (~2GB free RAM), even 3
    #     concurrent Mathlib environment loads caused every check to time
    #     out, including ones independently verified to compile in ~14s
    #     alone — same code, same imports, only difference was concurrency
    #     level plus ambient memory pressure. That's an infrastructure-
    #     contention failure, not a formalization-quality one; if checks are
    #     timing out, check free memory before touching any prompt.
    #   - On a 14-core machine with a warm Mathlib cache and ample RAM
    #     (checks completing in 1-5s), raising this to 6-10 measurably
    #     reduced total wall-clock time once ensemble candidate generation
    #     (3x the concurrent check load per step) was introduced.
    # Defaults to the most conservative of the three (safe out of the box on
    # constrained hardware); raise it deliberately once you've confirmed
    # your deployment has the cores/memory to spare, don't copy a number
    # from another machine.
    lean_concurrency_limit: int = 2

    # Two timeout tiers instead of one flat value: ensemble-round candidates
    # are a first attempt with no evidence yet that they're close, so a hung
    # one shouldn't hold a semaphore slot as long as a targeted repair
    # attempt would — a slower deadline here mostly just delays discovering
    # that other candidates already succeeded. Repair rounds get a more
    # generous budget since by then there's a specific, targeted fix being
    # attempted.
    #
    # 30s (not the originally-measured 15s) is the floor for the ensemble
    # tier specifically because a separate measurement (on a different,
    # Windows dev machine — see lean_verifier.py's DEFAULT_TIMEOUT) found
    # `import Mathlib.Analysis.Real.Sqrt` alone costs ~25s to import,
    # isolated from proof cost. At 15s, every ensemble candidate touching
    # Real.sqrt/Irrational (the Lean cookbook's patterns 5-6 in
    # formalize.py) would time out on the import alone regardless of
    # whether the proof itself was correct — indistinguishable from "hard
    # to prove" but actually just "budget shorter than baseline import
    # cost", the exact failure mode CLAUDE.md warns about for the
    # concurrency-vs-memory tradeoff. Warm/fast environments won't need the
    # full 30s, but a too-short ensemble timeout silently and systematically
    # fails a whole class of steps, which is worse than a few wasted seconds
    # on fast hardware.
    lean_timeout_ensemble: float = 30.0
    lean_timeout_repair: float = 45.0

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
