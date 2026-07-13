# Tark

Read CONSTRUCTION_PLAN.md fully before doing any work — it is the spec.
Core principle: Claude never asserts correctness. Only Lean 4 (via Mathlib)
or SymPy execution can produce a VERIFIED/REFUTED verdict. Anything else is
UNVERIFIED. Don't violate this anywhere, including in error-handling paths.

Stack: FastAPI backend (backend/), React+Vite frontend (frontend/),
Lean 4 + Mathlib project at tark_lean/.

Conventions:
- Steps are identified "S1", "S2", ... in proof order (assigned by Claude during
  decomposition). Sort naturally (S2 < S10), not lexicographically — see
  `backend/app/pipeline/report.py::_step_sort_key`.
- Verdict enum: `VERIFIED` | `REFUTED` | `UNVERIFIED` (never a bare "verified" —
  which verifier produced it is a separate `verifier` field: `lean` | `sympy` | null).
- Overall status: `FULLY_VERIFIED` | `PARTIALLY_VERIFIED` | `REFUTED_SOMEWHERE`.
- Claude is never asked for character offsets into the source (LLMs drift badly at
  counting characters). It's only asked for a verbatim quoted `anchor_text`; the
  backend locates it via exact-match-then-fuzzy-match
  (`backend/app/pipeline/span_matching.py`). Build/keep this fallback — offset
  drift is the common case per CONSTRUCTION_PLAN.md §10a.
- Claude calls use forced tool-use (`tool_choice={"type": "tool", "name": ...}`)
  for structured output, not free-text JSON parsing — see `backend/app/pipeline/`.
- Lean formalizations must use targeted Mathlib imports (e.g.
  `import Mathlib.Data.Nat.GCD.Basic`), never bare `import Mathlib` — the whole
  library takes 50s+ per subprocess and blows the 20-30s verifier timeout.
- A Lean proof using `sorry` exits 0 (Lean only warns) — `LeanVerifier` explicitly
  downgrades that to `UNVERIFIED`; never trust exit code 0 alone as "verified".
- `LeanVerifier` never returns `REFUTED` — every Lean failure is `UNVERIFIED`. A
  "type mismatch" compiler error looks identical whether Claude cited the wrong
  lemma (proof-engineering bug) or the statement is genuinely false; observed
  directly in testing: a *true* theorem was misclassified `REFUTED` because a
  cited lemma had a mismatched shape (`Even (2*q)` vs goal `Even (2*q^2)`).
  `REFUTED` is reserved for SymPy (a direct computed `False`, which is
  unambiguous) — don't reintroduce a Lean-side REFUTED heuristic without a much
  more reliable signal than compiler error text.
- Lean checks are expensive subprocesses — verifier `.check()` calls in the
  pipeline MUST go through `asyncio.to_thread`, never called directly inside an
  `async def`. A direct call blocks the whole event loop (all requests, not just
  the current one) for the full timeout window; caught this exact bug live
  (server went unresponsive under a single in-flight Lean check).
- Concurrent Lean subprocesses contend hard for CPU/disk — `real_pipeline.py`
  caps them via a semaphore sized from `settings.lean_concurrency_limit`
  (`config.py`, env var `LEAN_CONCURRENCY_LIMIT`), not a hardcoded constant —
  the right number is machine-dependent (measured directly: 11 concurrent
  checks -> 10/10 timeouts on the original dev machine; but on a 14-core
  machine with a warm cache, raising it from 3 to 6-10 measurably helped once
  ensemble candidates tripled the per-step check load). Tune per deployment,
  don't copy a number from another machine.
- On Windows, a timed-out `lake env lean` subprocess must be killed with
  `taskkill /F /T /PID` (see `_kill_process_tree`), not `proc.kill()` — `lake`
  spawns `lean.exe` as a child rather than exec'ing into it, so a plain kill
  leaves `lean.exe` running indefinitely, still holding CPU/memory.
- Orchestration is LangGraph (`backend/app/pipeline/real_pipeline.py`), not
  swarms.ai — evaluated and rejected: swarms' `Agent` unconditionally sends a
  `temperature` param the Claude Sonnet 5 API now rejects outright, with no
  public override (verified against swarms 13.0.0, the latest release, both
  live and by reading its `litellm_wrapper.py`). Don't re-evaluate swarms.ai
  for this without checking whether that's since been fixed upstream.
- All Claude calls go through `langchain-anthropic` + `claude_client.get_llm`/
  `invoke_llm`, never a raw SDK call — `invoke_llm` enforces the process-wide
  `claude_concurrency_limit` semaphore, and `cached_system_message`/
  `cached_tool` mark the static system-prompt+tools prefix for Anthropic's
  ephemeral prompt cache. Keep system prompts static (dynamic per-call content
  belongs in the user message) or caching silently stops working.
- `decompose()` must never let one malformed step (e.g. Claude omitting a
  `required` tool-schema field — schema `required` is a strong hint under
  forced tool-use, not a hard guarantee) take down the whole decomposition;
  `_parse_raw_step` degrades that one step instead of raising, per §4a.5.
  Caught live via `backend/scripts/bench.py`, not by inspection — rerun the
  bench harness after touching decompose.py, don't just read the diff.
- Ensemble candidate generation (`_generate_and_verify_lean`) fans out
  `formalize.ENSEMBLE_STRATEGIES` concurrently, then dedupes by
  whitespace-normalized hash before spending a Lean subprocess on each.
  Measured directly: growing that list from 3 to 4 strategies increased real
  per-step Lean-check load (real diversity means dedup has nothing to
  collapse) and semaphore contention with no wall-time win — re-validate the
  `lean_concurrency_limit` budget via `bench.py` before changing its length,
  don't just add a strategy and assume it's free.
- The SQLite proof cache (`pipeline/proof_cache.py`) never bypasses
  verification — a cache hit always pays for one real Lean re-check before
  being trusted (Mathlib may have moved a lemma since it was cached); a
  failed re-check evicts the entry and falls through to the normal path.
- The counterexample probe (`pipeline/counterexample.py`) is advisory-only
  and structurally separate from `SympyVerifier` — it can only ever append a
  `claude_notes` entry, never touch `step.verdict`. Don't let it anywhere
  near REFUTED; a false REFUTED is worse than a missed counterexample.
- `backend/scripts/bench.py` (fixtures in `scripts/fixtures/`) exists to
  replace anecdotal one-off timing runs — it costs real Claude API calls and
  Lean subprocess time, and decompose()/ensemble output is non-deterministic
  run to run, so use `--repeat 2+` and compare means, not single runs, before
  claiming a change helped or hurt.