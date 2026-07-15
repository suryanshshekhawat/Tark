# Tark

If HANDOFF.md exists, read it first — it's a short priority list for picking
this project back up. Then read CONSTRUCTION_PLAN.md fully before doing any
work — it is the spec.
Core principle: Claude never asserts correctness. Only Lean 4 (via Mathlib)
or SymPy execution can produce a VERIFIED/REFUTED verdict. Anything else is
UNVERIFIED. Don't violate this anywhere, including in error-handling paths.

Stack: FastAPI backend (backend/), React+Vite frontend (frontend/),
Lean 4 + Mathlib project at tark_lean/, and the Lean strategy cookbook at
lean_cookbook/ (read lean_cookbook/README.md before touching Lean
formalization patterns — see the Conventions entry below).

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
- The Lean cookbook (worked, hand-verified example proofs injected into the
  formalization prompt) is the single highest-leverage fix found so far: on
  the sqrt(2) demo proof, the Lean-candidate verification rate went from
  0/10 (general import/tactic guidance only) to 7/8 (with the cookbook) —
  most steps VERIFIED on the *first* attempt, no repair needed. Root cause
  of the failures wasn't the math being hard, it was recoverable mistakes
  (`ring_nf` needs `Mathlib.Tactic.Ring`, `norm_num` needs
  `Mathlib.Tactic.NormNum`, `omega` needs no import at all, a step mixing
  gcd+parity needs both imports together) — Claude's training data is
  unreliable on exactly this kind of precise, frequently-reorganized
  Mathlib bookkeeping, even for "obvious" facts. If a class of steps keeps
  failing, verify a working snippet directly against `tark_lean/`
  (`lake env lean <file>.lean`) and add it to the cookbook — don't just
  tweak prose guidance and hope.
  **As of a later session, the cookbook is no longer inline in
  `formalize.py`** — it moved to `lean_cookbook/` (one Markdown file per
  pattern, organized by mathematical branch/subtopic) specifically so it
  can grow to hundreds of patterns without becoming an unreadable Python
  string. `formalize.py` now only calls
  `cookbook_loader.build_lean_system_prompt()`, which assembles the prompt
  from those files at import time. **Read `lean_cookbook/README.md` before
  adding, editing, or reasoning about any pattern** — it's the authoritative
  spec for the file format, the required "test against `tark_lean/` first,
  then run `test_cookbook_patterns.py`" workflow, and the directory
  conventions for keeping hundreds of patterns navigable. Don't write Lean
  code inside `formalize.py` again; if you find yourself doing that, stop
  and put it in `lean_cookbook/` instead.
- Real-number steps (`Real.sqrt` etc.) were initially treated as an accepted
  timeout case — turned out to be wrong. Isolated the cost by timing
  `import Mathlib.Analysis.Real.Sqrt` against a *trivial* goal: ~25s, with the
  actual tactics contributing almost nothing on top. It's a fixed import cost,
  not proof difficulty, so the fix was raising `DEFAULT_TIMEOUT` to 45s
  (`lean_verifier.py`) and pointing the prompt at the correct minimal import
  (`Mathlib.Analysis.Real.Sqrt`, not `Mathlib.Analysis.SpecialFunctions.Sqrt`,
  which doesn't reliably resolve at that path) — see
  `lean_cookbook/number-theory/irrationality/squaring-sqrt-equation.md`.
  Lesson: before accepting a timeout as "structurally too
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
- RestrictedPython requires the *embedder* to supply guard functions for
  several ordinary-looking constructs — there's no built-in default. Missing
  one doesn't fail loudly; the snippet just dies with a bare, misleading
  NameError (`name '_unpack_sequence_' is not defined`) that gives no hint
  what's actually missing. Found live, via the UI, not a test: idiomatic
  sympy code constantly does `n, k = sympy.symbols(...)` (needs
  `_unpack_sequence_`), `for p, e in d.items():` (needs
  `_iter_unpack_sequence_`), and `total += x` (needs `_inplacevar_`, which
  has no default implementation at all — see `sympy_verifier.py` for a safe
  one built on `operator`). If SymPy snippets start failing with a
  NameError on an underscore-prefixed name, it's almost certainly a missing
  guard, not a real problem with the snippet — check
  `RestrictedPython/Guards.py` for what exists before assuming the sandbox
  is just broken for that code shape.
- Decomposition classification: "does this look like arithmetic" is the
  wrong test for `computational` vs `lean_candidate` — the actual dividing
  line is "are there free variables." `n^2 = 4k^2 = 2(2k^2)` (general n, k)
  was getting classified `computational` despite having no concrete numbers
  at all, because it superficially resembles a calculation. It isn't one —
  there's no single computation that decides a claim quantified over all
  integers. Any letter standing for an arbitrary integer means
  `lean_candidate`, full stop, regardless of how simple the algebra looks.
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
- `Settings.model_config`'s `env_file=".env"` was a relative path, resolved
  against the process's cwd at import time — fine when uvicorn is launched
  from inside `backend/` by hand, but silently broken (empty
  `anthropic_api_key`, `ClaudeNotConfiguredError` even with a real key in the
  file) when launched from anywhere else, e.g. `uvicorn ... --app-dir
  backend` from the repo root. Fixed by resolving `_ENV_FILE` relative to
  `config.py`'s own location (`Path(__file__).resolve().parent.parent /
  ".env"`) instead — cwd-independent, works regardless of launch directory.
- Long/complex inputs occasionally make Claude's forced tool-use double-encode
  a large array field as a JSON *string* instead of native JSON —
  `{"steps": "[...]"}` instead of `{"steps": [...]}` — inside
  `record_decomposition`'s `tool_use.input`. Live-captured for the first time
  via a debug log on the empty-steps path (see `decompose.py`): Claude's
  decomposition was correct and complete (24-27 well-formed steps every
  time) but got discarded as "returned no steps" because `raw_steps` was a
  `str`, not a `list`. This is what "decomposition keeps failing" turned out
  to actually be, on real multi-page academic LaTeX input — the short demo
  proofs from the previous session never hit it because it's specific to
  large `steps` arrays. Fixed in `_decompose_once`: if `tool_use.input["steps"]`
  is a `str`, `json.loads()` it and unwrap before falling through to the
  empty-steps error. Confirmed NOT caused by `\[...\]`-style display-math
  LaTeX (a hypothesis raised mid-session) — a 22-step Wilson's-theorem proof
  full of `\[...\]` blocks decomposed with zero steps dropped once this fix
  landed.
- `LeanVerifier.check()`'s `subprocess.Popen(..., text=True)` and
  `SympyVerifier.check()`'s `subprocess.run(..., text=True)` both omitted an
  explicit `encoding=`, so on Windows Python decoded subprocess output with
  the OS locale codec (`cp1252`) instead of UTF-8. Lean/Mathlib output is
  full of Unicode math notation (⊢, ¬, ∀, ≠, …) that `cp1252` can't
  represent — this crashed `Popen.communicate()`'s internal reader thread
  mid-read on nearly every Lean check (`UnicodeDecodeError` in
  `_readerthread`, visible in server logs, not raised to the caller), so
  `evidence.raw_output` was truncated right at the corrupting character
  instead of raising or degrading cleanly. A verdict computed from
  `proc.returncode` alone was still correct, but the diagnostic text used for
  cookbook-driven repair (§ "Priority 1" in HANDOFF.md-style sessions) was
  silently incomplete for basically every Mathlib-heavy check on Windows.
  Fixed by passing `encoding="utf-8", errors="replace"` explicitly on both
  `Popen`/`run` calls.
- Lean's `!` postfix factorial notation (`n !`) is declared `scoped` inside
  `namespace Nat` — it does not parse in a standalone single-theorem file
  that never has `open Nat` (which the Lean-formalization prompt's generated
  files never do). Use `Nat.factorial n` instead; confirmed both forms
  directly against `tark_lean/` before adding the factorial-related
  patterns now at `lean_cookbook/number-theory/factorials/` (see that
  directory's move out of `formalize.py` noted above).
- The prime-squared-divides-factorial pattern (two distinct multiples of the
  prime both being ≤ the factorial's argument) needed one non-obvious step:
  don't `rw` an equation like `2 * p = (2 * p - 1) + 1` in place —
  `2 * p - 1` still textually contains `2 * p`, so the rewrite doesn't
  normalize cleanly. `obtain ⟨q, hq⟩ : ∃ q, 2 * p = q + 1 := ...` first, to
  get a fresh opaque variable with no self-reference, then rewrite with
  that.