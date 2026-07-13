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
- Verdict enum: `VERIFIED` | `REFUTED` | `UNVERIFIED` | `ASSUMED` (never a bare
  "verified" — which verifier produced it is a separate `verifier` field:
  `lean` | `sympy` | null; `ASSUMED` always has `verifier: null`).
- `ASSUMED` is for premises/setup ("let p, q be given", "suppose for
  contradiction") — not a claim, nothing to check, never green. Distinct from
  `UNVERIFIED`, which means "this needed checking and we couldn't."
  Classification gets a matching `premise` value (alongside `lean_candidate` |
  `computational` | `unformalizable`) so decomposition can tell "this isn't a
  claim" apart from "this is a claim we can't formalize." Both are a
  *structural* judgment by Claude (what kind of sentence is this?), not a
  correctness judgment — `ASSUMED` must never be produced by an LLM deciding a
  claim is "probably true." See CONSTRUCTION_PLAN.md's core principle.
- Overall status: `FULLY_VERIFIED` | `PARTIALLY_VERIFIED` | `REFUTED_SOMEWHERE`.
  `ASSUMED` steps don't block `FULLY_VERIFIED` (they're not obligations) — see
  `report.py::build_report`'s `checkable` filter.
- The advisory pass (stage 6, `pipeline/advisory.py`) runs once after every
  step has a final verdict, not during decomposition — it needs the verdicts
  to comment on them ("this UNVERIFIED step might indicate X"). It never
  raises; a failed advisory call just means an empty `claude_global_notes`,
  not a broken report.
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
  caps them at `_LEAN_CONCURRENCY_LIMIT` (3) via a semaphore. Raising this
  without more cores just makes every check individually slower/likelier to
  time out; measured directly (11 concurrent checks -> 10/10 timeouts; 3
  concurrent -> most complete).
- On Windows, a timed-out `lake env lean` subprocess must be killed with
  `taskkill /F /T /PID` (see `_kill_process_tree`), not `proc.kill()` — `lake`
  spawns `lean.exe` as a child rather than exec'ing into it, so a plain kill
  leaves `lean.exe` running indefinitely, still holding CPU/memory.