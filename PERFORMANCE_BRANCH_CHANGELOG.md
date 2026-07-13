# `performance-updates` branch — change log

Two work sessions on this branch, both aimed at the same complaint: proof
verification (even for short proofs like the sqrt(2)-is-irrational demo) was
slow, and the working assumption was that the Claude-orchestration
architecture was the cause. Session 1 rebuilt the orchestration layer.
Session 2 took a systems-engineer pass over the resulting hybrid
agentic/Lean system looking for further robustness and performance
improvements, informed by a competitor (Aristotle, harmonic.fun).

Every change below was measured with a benchmark harness
(`backend/scripts/bench.py`), not assumed — several changes that looked good
in isolation measurably didn't help (or hurt) and were reverted or retuned
before landing. See "Things that looked good and weren't" at the bottom.

---

## Session 1 — orchestration rebuild

### Starting point
- `backend/app/pipeline/real_pipeline.py` already fanned out per-step work
  concurrently (`asyncio.create_task` + `asyncio.as_completed`), capped at
  `_LEAN_CONCURRENCY_LIMIT = 3` concurrent Lean subprocesses.
- The actual serial cost was **within** a single Lean-candidate step:
  formalize → verify → (if retryable) repair → verify again, up to 3
  attempts, each round strictly dependent on the previous compiler error.
- `formalize.py`'s own prompt already warned Claude that Mathlib renames
  files often — a strong hint that many repair rounds were being burned on
  import-path guessing, not genuine proof gaps.

### swarms.ai evaluated and rejected
The original ask was to rebuild the proposal side (decompose → formalize →
repair) as a multi-agent system using swarms.ai. Empirically, swarms.ai's
`Agent` class (v13.0.0, latest release) cannot drive Claude Sonnet 5 at all:
it unconditionally sends a `temperature` parameter that the Sonnet 5 API now
rejects outright (`"temperature is deprecated for this model"`), with no
public way to suppress it (confirmed by reading swarms' own
`litellm_wrapper.py`). Worse, `Agent.run()` didn't raise on this — after
exhausting retries it silently returned the *original input task string* as
if it were the model's output, a dangerous silent-failure mode in a system
whose entire safety story is "Claude proposes, verifiers dispose."

**LangGraph** was evaluated as a replacement and validated empirically before
committing:
- `ChatAnthropic` (langchain-anthropic) works cleanly with Claude Sonnet 5,
  no temperature issue.
- Forced tool-use (`bind_tools(..., tool_choice=...)`) works identically to
  the raw Anthropic SDK's `tool_choice` forcing already used in this codebase.
- `Send`-based fan-out streams each branch's result as it individually
  completes (verified with a synthetic test — 5 items with staggered sleep
  times streamed at 0.3s/0.6s/0.9s/... not batched at the end) — this
  preserves the existing SSE "stream results live" behavior exactly.

### What changed
- **`backend/app/claude_client.py`** — `anthropic` SDK replaced with
  `langchain-anthropic`'s `ChatAnthropic`.
- **`backend/app/pipeline/decompose.py`** / **`formalize.py`** — calls
  migrated to `ChatAnthropic.bind_tools(...).ainvoke(...)`.
- **`backend/app/pipeline/mathlib_search.py`** (new) — a `search_mathlib`
  tool backed by the public Loogle API
  (`https://loogle.lean-lang.org`), given to the Lean-formalizer and
  Lean-repairer so Claude can confirm a lemma/import actually exists before
  submitting to the (much slower) Lean compiler, instead of guessing and
  finding out ~11-30s later. Fails open (network issues never block the
  pipeline).
- **`backend/app/pipeline/real_pipeline.py`** — rewritten as a LangGraph
  `StateGraph`: `decompose` node → `Send`-based fan-out over steps →
  `process_step` node per step → aggregated back into the `Step` stream.
  Within each Lean-candidate step, generates multiple independent candidate
  formalizations **concurrently** (the "ensemble") instead of one attempt at
  a time, taking the first `VERIFIED`; only falls through to the sequential,
  tool-equipped repair loop if every candidate fails.
- **`backend/app/config.py`** — `lean_concurrency_limit` made configurable
  (env var `LEAN_CONCURRENCY_LIMIT`) rather than a hardcoded `3`, since the
  right number turned out to be machine-dependent: raising it from 3 to 6-10
  measurably reduced wall time once ensemble candidates tripled the
  concurrent-check load on this (14-core, warm-cache) dev machine, whereas
  the original `3` was tuned on a different, slower machine.

### Measured result (sqrt(2) demo proof)
| Stage | Verified | Wall time |
|---|---|---|
| Original baseline | 2/11 (18%) | 36.4s |
| + Loogle tool | 7/11 (64%) | 41.5s |
| + ensemble (cap=3, contended) | 7/11 (64%) | 64.6s |
| + ensemble (cap=6, tuned) | 8/11 (73%) | 61.9s |

---

## Session 2 — systems-engineering robustness/performance pass

Reviewed the resulting hybrid agentic (Claude/LangGraph) + non-agentic
(Lean/SymPy) system end-to-end for further improvements, benchmarked each
change before keeping it.

### Tier 0 — benchmark harness
- **`backend/scripts/bench.py`** (new) + **`backend/scripts/fixtures/*.tex`**
  (new: `sqrt2`, `gcd_euclid`, `mod4_squares`, `false_gcd` (deliberately
  false, exercises `REFUTED`), `prime_square_minus_one`). Runs the real
  pipeline directly (no HTTP), repeats N times, reports verified-rate and
  timing means/stdev instead of one-off anecdotal numbers.
- **Immediately caught a real bug**: `decompose()` raised a
  `DecompositionError` and killed an *entire* proof's results because Claude
  omitted a `required` tool-schema field (`anchor_text`) on one step — schema
  `required` is a strong hint under forced tool-use, not a hard guarantee.
  This directly violated the project's own principle (§4a.5: "a failure at
  step S4 should not prevent S1-S3's results from being shown"). Fixed in
  **`decompose.py`**: malformed individual steps now degrade gracefully
  (missing classification → `unformalizable` with a note; missing
  `anchor_text` → no highlight; only a missing `id`/`statement` drops the
  step, logged). Regression-tested in **`tests/test_decompose.py`**.

### Tier 1 — eliminate measured waste
- **Candidate dedup** (`real_pipeline.py`) — ensemble candidates were
  frequently byte-identical; now hashed (whitespace-normalized) and only
  unique candidates are sent to Lean, sharing results across duplicates.
- **Loogle TTL cache + circuit breaker** (`mathlib_search.py`) — identical
  queries repeated a dozen+ times within one proof; now cached (15 min TTL)
  with a failure-circuit-breaker so a Loogle outage doesn't add per-call
  timeout latency to every candidate.
- **Real ensemble diversity** (`formalize.py`) — the "try something
  different" prompt suffix produced near-duplicate candidates; replaced with
  3 concrete, differently-shaped strategy briefs (search-Mathlib-first,
  elementary-tactics-only, unsteered default). Deliberately kept at 3, not 4
  — see "Things that looked good and weren't" below.
- **Tiered Lean timeouts** (`config.py`) — `lean_timeout_ensemble` (15s,
  first-attempt candidates) vs `lean_timeout_repair` (30s, targeted fixes),
  instead of one flat 30s regardless of context.

### Tier 2 — API-level resilience
- **`claude_client.py`** — process-wide semaphore (`claude_concurrency_limit`,
  default 8) via a new `invoke_llm()` helper, so a many-step proof with
  several ensemble candidates each can't fire dozens of simultaneous Claude
  calls unchecked; `max_retries` configured explicitly.
- **Anthropic prompt caching** — `cached_system_message()` / `cached_tool()`
  helpers mark the system-prompt+tools prefix (shared, unchanging, across
  every decompose/formalize/repair call) with `cache_control: ephemeral`.
  Verified live against the real API: a repeat call with the same prefix
  reads it from cache (`cache_read_input_tokens`) instead of reprocessing it.

### Tier 3 — dependency-aware formalization
- Steps were formalized as freestanding claims even when they logically
  depend on earlier steps (e.g. "p is even" formalized without being told
  gcd(p,q)=1 and p²=2q² were already established) — both a fidelity problem
  (verifying a different claim than the proof actually makes) and a
  success-rate problem. `real_pipeline.py` now threads each step's
  `depends_on` statements into `formalize_lean` / `formalize_lean_repair` /
  `formalize_computational`, which state the theorem *given* those as
  hypotheses instead of inventing or ignoring them.

### Tier 4 — cross-request proof cache
- **`backend/app/pipeline/proof_cache.py`** (new) — SQLite file
  (`backend/tark_cache.sqlite3`, gitignored), keyed on a hash of the
  (whitespace-normalized) statement + dependency statements. A deliberate,
  narrow, user-approved exception to CONSTRUCTION_PLAN.md §14's "no storage
  for v1" — and the seed of the roadmap's "persistent knowledge archive"
  (§13). **A cache hit is never trusted blindly**: it still pays for one real
  Lean re-check before being used (Mathlib may have moved a lemma since it
  was cached); a failed re-check evicts the entry and falls through to the
  normal ensemble path. Config flag `enable_proof_cache` (default on).

### Tier 5 — advisory-only counterexample probe
- **`backend/app/pipeline/counterexample.py`** (new) — when a Lean-candidate
  step ends `UNVERIFIED` after every attempt, one additional Claude call asks
  for a small SymPy search over concrete values for a counterexample (or
  declines if the claim isn't concretely testable). Runs in its own
  sandboxed subprocess, structurally separate from `SympyVerifier` (which
  *does* produce verdicts) specifically so a probe bug can never be confused
  with, or accidentally produce, a `REFUTED`. **Never changes the verdict** —
  a hit only appends a labeled `claude_notes` entry
  ("Computational probe: ..."). Config flag `enable_counterexample_probe`
  (default on).

### Tier 6 — precompiled Lean prelude (measured, adopted with caveats)
- **`tark_lean/Tark/Prelude.lean`** (new) — bundles the ~18 Mathlib imports
  that recurred most often across proof steps (parity, GCD, Rat, Real.sqrt,
  Irrational, ring/linarith/norm_num). Benchmarked directly against targeted
  imports before adopting:
  - Single narrow import (e.g. just `Mathlib.Algebra.Ring.Parity`) vs
    `Tark.Prelude`: Prelude ~0.48s **slower** (forces loading Real/Analysis
    content even when unneeded).
  - 5 targeted imports vs `Tark.Prelude`: **identical** (1.93s vs 1.93s) —
    Mathlib's own prebuilt `.olean` cache means individual targeted imports
    were never "recompiled from source" per subprocess as originally feared;
    a wrapper file doesn't change what actually gets loaded.
  - Adopted as a **recommended option**, not a replacement: the
    `LEAN_SYSTEM_PROMPT` now tells Claude to prefer `Tark.Prelude` when a step
    needs 2+ of the bundled areas or the exact path is uncertain, and to keep
    using a single targeted import for a step that only needs one narrow,
    well-known lemma.

---

## Things that looked good and weren't (kept here so they aren't retried blindly)

- **4 ensemble strategies instead of 3.** Making ensemble candidates
  genuinely diverse (Tier 1) worked *too well* in one sense: dedup had
  nothing left to collapse, so growing the strategy list from 3 to 4 was a
  flat 33% increase in real per-step Lean-check load. Measured directly: this
  showed up as more semaphore contention with no wall-time improvement.
  Reverted to 3. If a 4th strategy is added later, re-benchmark
  `lean_concurrency_limit` alongside it — don't assume it's free.
- **Piping `bench.py` output through `tail -N`.** Truncates earlier fixture
  results before a later crash/completion — lost an early baseline run this
  way. Redirect to a file and read the whole thing instead.
- **A real API/environment surprise, not a code mistake**: the Claude Sonnet
  5 API rejects the `temperature` parameter entirely (any value), which is
  why swarms.ai is unusable here today. Worth re-checking if swarms.ai ships
  a fix, since the underlying multi-agent-framework idea isn't wrong, just
  currently incompatible with this specific model.

---

## Results (this session's benchmark, 2 repeats per fixture)

| Fixture | Wall time | Verified rate | Lean checks/run | Semaphore wait/run |
|---|---|---|---|---|
| `sqrt2` | 43.8s | 86.4% | 26.5 | 0.0s |
| `gcd_euclid` | 17.4s | 90.0% | 1.5 | 0.0s |
| `mod4_squares` | 33.7s | 72.9% | 15.0 | 0.0s |
| `prime_square_minus_one` | 31.0s | 77.4% | 16.5 | 0.9s |
| `false_gcd` (deliberately false) | 9.1s | 50%* | 0.0 | 0.0s |

\* Low verified% on `false_gcd` is correct — it's a fixture designed to be
wrong, exercising the `REFUTED`/`UNVERIFIED` path rather than `VERIFIED`.

Compared to the very first baseline measured at the start of session 1
(36.4s, 18% verified on `sqrt2`), verified rate roughly quintupled while wall
time stayed flat-to-better and semaphore contention dropped to near zero.

38 backend tests pass (up from 19 at the start of session 2). The
backend↔frontend SSE/JSON contract (`event: step` / `event: done`, `Step` /
`Report` schemas) was verified byte-identical via live HTTP calls before and
after — no frontend changes required.

## Files touched

**New:** `backend/scripts/bench.py`, `backend/scripts/fixtures/*.tex`,
`backend/app/pipeline/mathlib_search.py`,
`backend/app/pipeline/proof_cache.py`,
`backend/app/pipeline/counterexample.py`, `tark_lean/Tark/Prelude.lean`,
`backend/tests/test_decompose.py`, `backend/tests/test_proof_cache.py`,
`backend/tests/test_counterexample.py`.

**Modified:** `backend/app/claude_client.py`, `backend/app/config.py`,
`backend/app/main.py`, `backend/app/pipeline/decompose.py`,
`backend/app/pipeline/formalize.py`, `backend/app/pipeline/real_pipeline.py`,
`backend/requirements.txt`, `backend/.env.example`, `.gitignore`,
`tark_lean/Tark.lean`, `CLAUDE.md`.
