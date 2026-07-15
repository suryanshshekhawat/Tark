# Handoff — read this first

Read [CLAUDE.md](CLAUDE.md) fully — it has detailed, hard-won notes on nearly
everything below, written as the bugs were found. This file is the short
version: what's done, what's open, what to do next.

## State: backend/pipeline is solid; next session is UI-focused

The pipeline works end-to-end with real Claude + Lean + SymPy, and has been
stress-tested hard, not just smoke-tested. A Wilson's-theorem proof (24 steps,
genuinely deep number theory — modular inverses, case-split factorization,
ZMod field structure) now reaches **17/24 verified** through the real
pipeline, up from 4/24 at the start of that investigation. The Lean cookbook
(`lean_cookbook/`, see below) has 17 independently-compiled, regression-tested
patterns. Every fix in this file was confirmed by actually compiling Lean
code against `tark_lean/` or running the affected test suite — nothing here
is speculative.

**The user is starting a new chat next to work on the frontend UI
("UI overwrite").** That means:
- Treat the backend (`backend/`) and the Lean cookbook (`lean_cookbook/`,
  `tark_lean/`) as stable and well-tested — don't need to re-verify them
  from scratch unless the UI work requires an API contract change.
- The frontend (`frontend/`) is the explicit target for rework. See
  "Frontend orientation" below for current structure before changing it.
- Browser preview servers (backend on :8000, frontend on :5173) do **not**
  persist across chat sessions — the new session needs to call
  `preview_start` for both again (see "How to run locally"). Don't assume
  they're already running.

## Frontend orientation (read before the UI overwrite)

Current structure, all under `frontend/src/`:
- `App.tsx` — top-level state machine: `idle → preview → streaming → done/error`.
  Holds the `EXAMPLES` array (3 pre-loaded demo proofs: √2 irrational, gcd &
  primality, even squares) and orchestrates `api.ts`'s `streamVerify()`.
- `api.ts` — hand-rolled SSE client over `fetch()` (not `EventSource`, since
  that can't send a POST body). Events: `auto_repair`, `step`, `done`,
  `pipeline_error`. This is the API contract with the backend
  (`backend/app/routers/verify.py`) — if the UI overwrite changes how
  results are consumed, keep this contract or update both sides together.
- `components/`: `SourcePane` (LaTeX textarea + preview), `LatexPreview` +
  `latex/latexRender.tsx` (renders LaTeX to readable math), `StepSidebar` +
  `StepRow` + `StepCard` (the verification results list — id, verdict badge,
  statement, classification, expandable evidence), `SummaryHeader`
  (overall status + verified/assumed counts).
- Styling is plain CSS, no framework (no Tailwind/MUI/etc. currently) — worth
  deciding explicitly whether the overwrite keeps that or adopts something.

Known rough edges in the current UI (not fixed, fair game to address):
- Evidence panels are collapsed by default and there's no "expand all" —
  became a real friction point this session when debugging multiple failing
  steps at once (had to click each one, or fall back to reading the network
  response / DOM directly).
- No persistence — navigating away or reloading loses all results; a run's
  output only exists in React state. Caught out this exact session
  (accidentally navigated mid-review and lost a completed run's view).
- No way to re-run just one step / a Lean repair attempt from the UI.

## Priority 1: expand the Lean cookbook

The cookbook lives at `lean_cookbook/` — one Markdown file per pattern
(frontmatter: `title`, `when_to_use`, `gotchas`, `verified` date; body: a
fenced ```lean block), organized by branch/subtopic
(`number-theory/factorials/`, `number-theory/primes/`,
`number-theory/modular-arithmetic/`, `algebra/`, ...). **Read
`lean_cookbook/README.md` first** — it's the authoritative spec and
contribution workflow, not a summary of it. `backend/app/pipeline/
cookbook_loader.py` assembles these into the formalization prompt at import
time; `formalize.py` no longer contains any Lean code directly.

Required workflow for adding/changing a pattern:
1. Test the Lean snippet directly against `tark_lean/` first — NOT through
   the full pipeline: `cd tark_lean && lake env lean path/to/scratch.lean`.
2. Add/edit the `.md` file under the right `lean_cookbook/<branch>/<subtopic>/`.
3. Run `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_cookbook_patterns.py -q`
   — recompiles every pattern independently; this is what makes cookbook
   growth non-regressive, not just a hope. **Don't skip it.**
4. Restart the backend (prompt is built once at import time) before
   re-testing through the live pipeline.

This is the single highest-leverage lever in the whole project. Condensed
history (full blow-by-blow, including every exact Mathlib gotcha found, is
in CLAUDE.md — don't duplicate it here):
- Started at 6 patterns (parity, gcd, algebra, irrationality) driven by the
  √2 demo proof: 0/10 → 8/8 Lean verification.
- Grew to 9 via a Wilson's-theorem stress test (factorial divisibility,
  Euclid's lemma).
- Grew to 17 via a deep debugging pass on that same proof: fixed several
  wrong-but-plausible-sounding tactic imports (`nlinarith`, `interval_cases`,
  `linear_combination` each need their own specific import, not the one
  Claude's training data suggests), a renamed lemma
  (`ZMod.natCast_eq_zero_iff`, not `..._zmod_eq_zero_iff_dvd`), a proof
  Claude's own code had given up on with `sorry` (rewritten cleanly via
  `Nat.minFac`), and a genuine logic bug (wrong hypothesis applied to the
  wrong contradiction). Also found that **Mathlib already has the entire
  Wilson's theorem** (`Nat.prime_iff_fac_equiv_neg_one` in
  `Mathlib.NumberTheory.Wilson`) — worth checking whether a step's whole
  claim is already a named theorem before decomposing further.

Known gap: the cancelling-sequence proof from an earlier session (`⌈⌉`/`⌊⌋`
arithmetic, divisibility case-splits) has zero cookbook coverage — a good
next target for a meaningfully different shape than more Wilson/√2-flavored
number theory, if cookbook work continues.

**Important nuance for interpreting future pipeline runs**: because Claude
writes fresh Lean code every single run (not replaying cached proofs), a
single run hitting a `100%`/`0%` verified rate is not by itself proof the
cookbook is complete/broken — check `evidence.raw_output` for each failure
first. A `timed out after Ns` with empty stdout/stderr means infrastructure
contention (see Priority 3), not a bad pattern; retry alone before
concluding anything is broken. A real compiler error (`exit code: 1`) is
worth fixing and adding to the cookbook.

## Priority 2: known open issues

**Decomposition — SOLVED.** Three root causes, all fixed (see CLAUDE.md for
detail): (1) inputs too large hitting `max_tokens` mid-generation — now
detected explicitly with a clear error; (2) Claude occasionally
double-encoding a large `steps` array as a JSON *string* instead of native
JSON, discarding a correct decomposition as "empty" — now detected and
recovered in `_decompose_once`; (3) Windows decoding Lean/SymPy subprocess
output with `cp1252` instead of UTF-8, silently truncating evidence on any
Unicode math notation — fixed with explicit `encoding="utf-8"` on both
verifiers' subprocess calls.

**RestrictedPython sandbox guards**: all 7 guards the transformer can emit
are wired (see `sympy_verifier.py`). If a NameError on a new
underscore-prefixed name shows up, check `RestrictedPython/Guards.py` before
assuming the sandbox is broken.

**Concurrency/memory**: `_LEAN_CONCURRENCY_LIMIT` in `real_pipeline.py` is 2.
`DEFAULT_TIMEOUT` in `lean_verifier.py` is 90s (raised from 45s — some
cookbook imports, e.g. `Mathlib.FieldTheory.Finite.Basic`, measured at 58s
warm / 3m10s under memory pressure, solo with zero contention). If
verification looks inexplicably bad, **check free memory first**
(`Get-CimInstance Win32_OperatingSystem | Select FreePhysicalMemory`) —
repeatedly confirmed live this session that under ~2GB free RAM, checks
independently proven to compile in ~15s alone start timing out, and the
failure evidence (empty timeout, no partial output) looks identical to a
genuinely-too-hard proof. This is not hypothetical — it happened multiple
times in the same session that fixed the cookbook bugs, and cost real
wall-clock time to correctly diagnose each time. Excluding `tark_lean/` from
Windows Defender real-time scanning is still identified as a likely win,
still not done — it's a system-settings change outside what Claude Code
should do unilaterally.

## Priority 3: things not started

- **Deployment** (containerizing Lean+Mathlib) — deliberately deferred, user
  wanted to try the tool locally first. Docker is confirmed installed. The
  hard part will be `tark_lean/.lake`'s multi-GB Mathlib `.olean` cache.
- **More pre-loaded example proofs** — currently 3 in `frontend/src/App.tsx`'s
  `EXAMPLES` array. Could use a 4th that reliably produces `REFUTED` via Lean
  specifically (currently only the SymPy path has a demonstrated `REFUTED`
  case). The Wilson's-theorem proof used throughout this session could
  become a good "hard/deep" 4th example, now that it mostly verifies.
- **Lean-side sandboxing** is narrower than SymPy's (subprocess isolation +
  timeout + process-tree-kill only, no OS-level resource/network ACLs) —
  accepted as proportionate given Claude is only ever asked for
  `theorem := by tactics`, not arbitrary `#eval`/`IO` code.

## How to run locally

```
# Backend
cd backend
./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 --host 127.0.0.1

# Frontend
cd frontend
npm run dev
```

Or via the Browser preview tool: `preview_start({name: "backend"})` and
`preview_start({name: "frontend"})` — both are already defined in the
top-level `.claude/launch.json`. **These do not persist across chat
sessions** — a new chat must call `preview_start` again even if a previous
session left them running; check `preview_list()` first rather than
assuming.

Backend needs `backend/.env` with `ANTHROPIC_API_KEY=...` (gitignored, not in
the repo — check it's actually there and has a valid key **with credit**
before assuming a bug when something fails; this bit a live session — a
low/zero balance produces a clear `invalid_request_error` from the Anthropic
API, not a Tark bug). `Settings` resolves `.env` relative to `config.py`'s
own file location, not the process's cwd, so this works regardless of which
directory uvicorn is launched from.

Run tests with:
```
cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q \
  --ignore=tests/test_lean_verifier.py --ignore=tests/test_cookbook_patterns.py
```
(fast, ~43 tests, no real Lean subprocesses). Both ignored files are slow —
run them separately when touching `lean_verifier.py` or `lean_cookbook/`:
`./.venv/Scripts/python.exe -m pytest tests/test_cookbook_patterns.py -q`
(2-6 minutes for the full cookbook depending on system load; a single
pattern can be run alone with `-k <pattern-name>`).

**Be deliberate about API cost.** Each full pipeline run through the live UI
costs one decompose call plus one formalize+verify call per step plus one
advisory call — a 20+ step proof is a non-trivial number of Claude API
calls. Test Lean/cookbook changes locally against `tark_lean/` first (free,
seconds) and only run the full live pipeline to confirm a fix actually
lands, not to iterate on it.
