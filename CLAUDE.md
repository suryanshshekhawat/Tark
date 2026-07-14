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
  library takes 50s+ per subprocess and blows the verifier timeout (45s).
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
- Concurrent Lean subprocesses contend hard for CPU/disk/memory —
  `real_pipeline.py` caps them at `_LEAN_CONCURRENCY_LIMIT` via a semaphore
  (11 concurrent -> 10/10 timeouts; lowered 3 -> 2 after a second live
  regression where even 3 caused a 0/8 run on code independently verified to
  compile in ~14s alone — free RAM on this dev machine was ~2GB/16GB at the
  time). If verification quality looks bad, check `Get-Process | sort
  WorkingSet64 -desc | select -first 10` and free memory / lower this
  constant BEFORE touching the formalization prompt — a resource-starved
  Lean check and a genuinely-hard-to-formalize step produce the identical
  symptom (timeout), and only one of them is fixable by prompt engineering.
  The single highest-leverage fix outside our control: exclude `tark_lean/`
  from Windows Defender real-time scanning (thousands of `.olean` reads per
  check) — Claude can't do this (a system-settings change), the user has to.
- On Windows, a timed-out `lake env lean` subprocess must be killed with
  `taskkill /F /T /PID` (see `_kill_process_tree`), not `proc.kill()` — `lake`
  spawns `lean.exe` as a child rather than exec'ing into it, so a plain kill
  leaves `lean.exe` running indefinitely, still holding CPU/memory.
- `formalize.py`'s `LEAN_SYSTEM_PROMPT` includes a small cookbook of Lean
  snippets hand-verified against this exact Mathlib pin (parity of squares,
  unpacking `Even`, gcd-of-two-evens, algebraic substitution). This is the
  single highest-leverage fix found so far: on the sqrt(2) demo proof, the
  Lean-candidate verification rate went from 0/10 (general import/tactic
  guidance only) to 7/8 (with the cookbook) — most steps VERIFIED on the
  *first* attempt, no repair needed. Root cause of the failures wasn't the
  math being hard, it was recoverable mistakes (`ring_nf` needs
  `Mathlib.Tactic.Ring`, `norm_num` needs `Mathlib.Tactic.NormNum`, `omega`
  needs no import at all, a step mixing gcd+parity needs both imports
  together) — Claude's training data is unreliable on exactly this kind of
  precise, frequently-reorganized Mathlib bookkeeping, even for "obvious"
  facts. If a class of steps keeps failing, verify a working snippet
  directly against `tark_lean/` (`lake env lean <file>.lean`) and add it to
  the cookbook — don't just tweak prose guidance and hope.
- Real-number steps (`Real.sqrt` etc.) were initially treated as an accepted
  timeout case — turned out to be wrong. Isolated the cost by timing
  `import Mathlib.Analysis.Real.Sqrt` against a *trivial* goal: ~25s, with the
  actual tactics contributing almost nothing on top. It's a fixed import cost,
  not proof difficulty, so the fix was raising `DEFAULT_TIMEOUT` to 45s
  (`lean_verifier.py`) and pointing the prompt at the correct minimal import
  (`Mathlib.Analysis.Real.Sqrt`, not `Mathlib.Analysis.SpecialFunctions.Sqrt`,
  which doesn't reliably resolve at that path) — see cookbook pattern 5 in
  `formalize.py`. Lesson: before accepting a timeout as "structurally too
  hard," isolate whether it's actually import cost vs. proof-search cost by
  testing the import alone against a trivial goal — they need very different
  fixes (a longer/no timeout vs. a fundamentally different approach).
- `SympyVerifier` used to sandbox via a restricted `__builtins__` dict passed
  to `exec()` — proven exploitable directly: `().__class__.__base__.__subclasses__()`
  reaches every live Python class (`subprocess.Popen` included) without ever
  calling `import`, completely bypassing the import allowlist. Rewrote to use
  `RestrictedPython` (`compile_restricted` + `safe_globals` + `safer_getattr`),
  which rejects dunder attribute access at *compile* time. No `__import__` is
  exposed at all now — `math`/`sympy`/etc. are pre-bound names, not importable
  modules; `import anything` always fails. If you're tempted to hand-roll
  Python sandboxing again, don't — verify against the class-introspection
  trick specifically before trusting it (see `test_sympy_verifier.py`'s
  `test_snippet_cannot_escape_via_class_introspection`).
- `LeanVerifier`'s sandboxing is narrower in scope than SymPy's needs to be:
  Claude is prompted for a `theorem ... := by <tactics>` file, not arbitrary
  `#eval`/`IO` code, so there's no equivalent to Python's `exec()` executing
  attacker-controlled logic — `lean` is type-checking a proof term, not
  running a program. Isolation is subprocess-level (separate process, hard
  timeout, `taskkill /T` process-tree cleanup, writes confined to
  `.tark_scratch/`). No OS-level network/resource ACLs (Windows Job Objects
  etc.) — not done, given the narrower attack surface and hackathon time
  budget; would be the next step for a production deployment.
- Deployment (§12 Days 13-14) is deliberately deferred — user wants to run
  and try the tool locally first before attempting containerization.
  Docker is confirmed available on this machine if/when it's picked back up;
  the hard part will be baking tark_lean/'s Mathlib `.lake` cache (thousands
  of `.olean` files) into an image without a multi-GB, multi-minute build.