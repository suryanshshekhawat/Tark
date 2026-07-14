# Tark

If HANDOFF.md exists, read it first — it's a short priority list for picking
this project back up. Then read CONSTRUCTION_PLAN.md fully before doing any
work — it is the spec.
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
  `real_pipeline.py` caps them via a semaphore sized from
  `settings.lean_concurrency_limit` (`config.py`, env var
  `LEAN_CONCURRENCY_LIMIT`), not a hardcoded constant — the right number is
  machine-dependent, not a universal constant. Three independent
  measurements, not assumptions: 11 concurrent -> 10/10 timeouts on the
  original dev machine; on a *memory*-constrained machine (~2GB/16GB free),
  even 3 concurrent Mathlib environment loads caused a 0/8 run on code
  independently verified to compile in ~14s alone (default lowered to 2 for
  this reason); on a 14-core machine with a warm cache and ample RAM,
  raising it to 6-10 measurably helped once ensemble candidates tripled the
  per-step check load. Default is the most conservative (2) — tune up
  deliberately per deployment, don't copy a number from another machine. If
  verification quality looks inexplicably bad (steps timing out that should
  be fast), check free memory (`Get-Process | sort WorkingSet64 -desc |
  select -first 10` on Windows) and free memory / lower this setting BEFORE
  touching the formalization prompt — a resource-starved Lean check and a
  genuinely-hard-to-formalize step produce the identical symptom (timeout),
  and only one of them is fixable by prompt engineering. The single
  highest-leverage fix outside our control: exclude `tark_lean/` from
  Windows Defender real-time scanning (thousands of `.olean` reads per
  check) — Claude can't do this (a system-settings change), the user has to.
- Two Lean timeout tiers, not one flat value (`lean_timeout_ensemble` /
  `lean_timeout_repair`, `config.py`): a first-round ensemble candidate gets
  less time than a targeted repair attempt, since a hung first attempt
  shouldn't hold a semaphore slot as long as a specific fix being retried.
  The ensemble floor (30s) is set by a real measurement, not the original
  15s guess — `import Mathlib.Analysis.Real.Sqrt` alone costs ~25s to import
  (isolated by timing it against a trivial goal), so a shorter ensemble
  timeout would make every Real.sqrt/Irrational candidate (Lean cookbook
  patterns 5-6 below) time out on the import alone regardless of whether the
  proof was correct — indistinguishable from "hard to prove" but actually
  "budget shorter than baseline import cost."
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
- All Claude calls (decompose, formalize, repair, advisory) go through
  `langchain-anthropic` + `claude_client.get_llm`/`invoke_llm`, never a raw
  SDK call — `invoke_llm` enforces the process-wide `claude_concurrency_limit`
  semaphore, and `cached_system_message`/`cached_tool` mark the static
  system-prompt+tools prefix for Anthropic's ephemeral prompt cache. Keep
  system prompts static (dynamic per-call content belongs in the user
  message) or caching silently stops working. LangChain's response shape
  differs from the raw SDK's: `response.tool_calls` (parsed `name`/`args`/
  `id` dicts) instead of `.content` blocks with `.type`/`.input`, and
  `response.response_metadata.get("stop_reason")` instead of
  `.stop_reason` — a raw-SDK-shaped mock in a test will pass type-checking
  but silently return nothing.
- `decompose()` must never let one malformed step (e.g. Claude omitting a
  `required` tool-schema field — schema `required` is a strong hint under
  forced tool-use, not a hard guarantee) take down the whole decomposition —
  degrade that one step instead of raising, per §4a.5. `_decompose_once`
  also handles two other real, live-observed failure shapes: a `max_tokens`
  truncation (raises a specific "too long to decompose" error, not retried —
  deterministic given input size) and `steps` occasionally arriving as a
  double-JSON-encoded string instead of a true array (recovered via
  `json.loads`, not treated as empty). `decompose()` additionally retries
  once on any other malformed/empty response (observed to be sampling
  variance, not deterministic). Caught/verified live via
  `backend/scripts/bench.py`, not by inspection — rerun the bench harness
  after touching decompose.py, don't just read the diff.
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
  near REFUTED; a false REFUTED is worse than a missed counterexample. It
  shares `SympyVerifier`'s RestrictedPython sandbox design (see below) rather
  than its own restricted-builtins dict — a second sandboxed subprocess is a
  second chance to reintroduce the same escape.
- `backend/scripts/bench.py` (fixtures in `scripts/fixtures/`) exists to
  replace anecdotal one-off timing runs — it costs real Claude API calls and
  Lean subprocess time, and decompose()/ensemble output is non-deterministic
  run to run, so use `--repeat 2+` and compare means, not single runs, before
  claiming a change helped or hurt.
- `formalize.py`'s `LEAN_SYSTEM_PROMPT` includes a small cookbook of Lean
  snippets hand-verified against this exact Mathlib pin (parity of squares,
  unpacking `Even`, gcd-of-two-evens, algebraic substitution, squaring a
  `Real.sqrt` equation, irrationality of `sqrt(p)`). This is the single
  highest-leverage fix found so far: on the sqrt(2) demo proof, the
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
  not proof difficulty — see the two-tier Lean timeout entry above for how
  that's now reflected in `config.py`, and point the prompt at the correct
  minimal import (`Mathlib.Analysis.Real.Sqrt`, not
  `Mathlib.Analysis.SpecialFunctions.Sqrt`, which doesn't reliably resolve at
  that path) — see cookbook pattern 5 in `formalize.py`. Lesson: before
  accepting a timeout as "structurally too hard," isolate whether it's
  actually import cost vs. proof-search cost by testing the import alone
  against a trivial goal — they need very different fixes (a longer timeout
  vs. a fundamentally different approach).
- `SympyVerifier` (and `counterexample.py`'s probe, which shares the same
  runner design) used to sandbox via a restricted `__builtins__` dict passed
  to `exec()` — proven exploitable directly:
  `().__class__.__base__.__subclasses__()` reaches every live Python class
  (`subprocess.Popen` included) without ever calling `import`, completely
  bypassing the import allowlist. Rewrote both to use `RestrictedPython`
  (`compile_restricted` + `safe_globals` + `safer_getattr`), which rejects
  dunder attribute access at *compile* time. No `__import__` is exposed at
  all now — `math`/`sympy`/etc. are pre-bound names, not importable modules;
  `import anything` always fails. If you're tempted to hand-roll Python
  sandboxing again, don't — verify against the class-introspection trick
  specifically before trusting it (see `test_sympy_verifier.py`'s and
  `test_counterexample.py`'s `test_snippet_cannot_escape_via_class_introspection`).
- RestrictedPython requires the *embedder* to supply guard functions for
  several ordinary-looking constructs — there's no built-in default. Missing
  one doesn't fail loudly; the snippet just dies with a bare, misleading
  NameError (`name '_unpack_sequence_' is not defined`) that gives no hint
  what's actually missing. Found live, via the UI, not a test: idiomatic
  sympy code constantly does `n, k = sympy.symbols(...)` (needs
  `_unpack_sequence_`), `for p, e in d.items():` (needs
  `_iter_unpack_sequence_`), and `total += x` (needs `_inplacevar_`, which
  has no default implementation at all — see `sympy_verifier.py` for a safe
  one built on `operator`). If SymPy or counterexample-probe snippets start
  failing with a NameError on an underscore-prefixed name, it's almost
  certainly a missing guard, not a real problem with the snippet — check
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
