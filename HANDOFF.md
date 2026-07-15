# Handoff — read this first

Read [CLAUDE.md](CLAUDE.md) fully — it has detailed, hard-won notes on
nearly everything below, written as the bugs were found. This file is the
short version: what's done, what's open, what to do next.

## State: frontend rebuild is done and solid; next session should investigate a verification regression

The frontend (`frontend/`) went through a full visual overwrite this
session to match Figma mockups (`frontend/ui_inspo/`), plus a real
architecture change: LaTeX is now genuinely compiled to PDF (not
approximated via KaTeX) and highlighted via the PDF's own text layer. Both
are stable and tested against three example proofs (√2, gcd/primality,
Wilson's theorem). See "What changed" below before touching the frontend or
`backend/app/rendering/`.

**Known open issue, not yet investigated — pick this up first**: in the
last live test of this session (Wilson's theorem, full run), every
statement came back UNVERIFIED/failed. This was **explicitly not
investigated this session** at the user's request ("do not test that right
now"), so don't assume a cause — CLAUDE.md's memory-pressure note
(concurrent Lean subprocesses timing out under low free RAM) is the
obvious first hypothesis given prior history, but it was **not confirmed
for this specific failure**, and nothing about this session's changes
touched `real_pipeline.py`'s verification logic itself (only
`decompose_steps`/`run_verification` were split apart, not rewritten — see
below). Check `Get-CimInstance Win32_OperatingSystem | Select
FreePhysicalMemory` first per CLAUDE.md's existing playbook, but verify
against `evidence.raw_output` for a few failing steps before concluding
that's actually it this time.

## What changed this session (frontend + rendering)

**Full UI overwrite** (`frontend/src/`): black/white sharp-edged design,
Inter font, matches `frontend/ui_inspo/` mockups. All components were
rewritten — `StatementCard`/`StatementList`/`PdfPaperViewer`/`TopBar`/
`ResultSummary`/`TypingWordmark` are new; the old KaTeX-text-rendering
components (`SourcePane`, `LatexPreview`, `StepCard`, etc.) and
`latex/latexRender.tsx` are gone.

**Real PDF compilation** (`backend/app/rendering/latex_compiler.py`, new
`POST /api/compile` in `backend/app/routers/compile.py`): LaTeX is compiled
with a real `pdflatex` (MiKTeX, already installed on the dev machine) —
not approximated. A bare fragment (no `\begin{document}`) gets wrapped in a
minimal default preamble; a full document compiles verbatim, so
`\title`/`\maketitle`/custom `\newtheorem`/`\begin{proof}` etc. all just
work with zero custom parsing. Compiled docs are cached by content hash in
`backend/.tark_pdf_cache/` (gitignored).

**Highlighting is now 100% client-side** (`frontend/src/textLayerMatch.ts`)
— this replaced a SyncTeX-based backend approach (tried and retired in
this same session; see CLAUDE.md for why it doesn't have the precision
needed). Each step's exact source text is matched against the compiled
PDF's own `pdf.js` text layer (real glyph positions), with an explicit
LaTeX-command classifier so symbol commands (`\equiv`, `\cdot`,
`\Rightarrow`, ...) don't get searched for as literal words. The backend
has **zero** PDF/box-geometry code left — `verify.py` doesn't touch
compilation at all anymore.

**New SSE event**: `decomposition`, emitted immediately after Claude's
decomposition call (Stage 2) finishes, carrying the true total statement
count, classification breakdown, and every step's `source_span` —
`normalized_source` is on this payload too, specifically so the frontend
can start text-layer matching immediately rather than waiting for `done`.
Statement cards render as pending placeholders from this event and resolve
in place as `step` events arrive (matched/upserted by id, not appended).

**Result screen**: short 2-3 line summary + a "Download Verification
Report" button producing a Markdown file (original proof + statement
breakdown — not an exhaustive internal dump). Zoom controls and
sharp/thin custom scrollbars on the PDF viewer.

Four real bugs were found and fixed live this session, worth knowing about
even though they're already fixed:
1. The landing page's LaTeX field was a single-line `<input>`, which
   silently strips newlines from multi-line paste — any real multi-line
   proof would have been silently corrupted before decomposition ever saw
   it. Now a `<textarea>`.
2. No guard against concurrent `/api/verify` submissions — rapid/duplicate
   clicks could fire overlapping SSE streams into the same React state.
   Now guarded (`if (status === "streaming") return;` in `handleVerify`).
3. `StatementList`'s live/timeline mode never wired `focusedStepId`/
   `onFocus` into `StatementCard` — hover-linking silently didn't work
   during streaming even after highlight boxes started arriving live.
4. SyncTeX's box granularity is per-line for running prose, not
   per-character — confirmed directly by querying the same line at
   different columns and getting identical boxes back. No amount of query
   tuning fixes this; it's why highlighting moved to the PDF text layer
   instead (see above).

## Before touching backend or frontend: two easy-to-forget things

- **The backend runs without `--reload`.** Every backend code change needs
  a manual restart (`preview_stop` + `preview_start({name: "backend"})` if
  using the Browser tool). This caused real confusion this session — a
  "the pipeline is broken!" report from the user turned out to just be a
  stopped/stale server, twice.
- **MiKTeX must have `initexmf --set-config-value=[MPM]AutoInstall=1`
  set** (already done on this machine) or `pdflatex` hangs indefinitely
  waiting for an interactive "install missing package?" prompt that never
  comes in a subprocess context. If PDF compilation hangs on a fresh
  machine, check this first.

## Priority 1: investigate the verification regression (see above)

Nothing else should get real attention until this is understood — it's a
correctness/credibility issue, not a UI issue.

## Priority 2: expand the Lean cookbook

Unchanged from before this session. The cookbook lives at `lean_cookbook/`
— one Markdown file per pattern (frontmatter: `title`, `when_to_use`,
`gotchas`, `verified` date; body: a fenced ```lean block), organized by
branch/subtopic. **Read `lean_cookbook/README.md` first.**
`backend/app/pipeline/cookbook_loader.py` assembles these into the
formalization prompt at import time.

Required workflow for adding/changing a pattern:
1. Test the Lean snippet directly against `tark_lean/` first — NOT through
   the full pipeline: `cd tark_lean && lake env lean path/to/scratch.lean`.
2. Add/edit the `.md` file under the right `lean_cookbook/<branch>/<subtopic>/`.
3. Run `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_cookbook_patterns.py -q`
   — recompiles every pattern independently. **Don't skip it.**
4. Restart the backend before re-testing through the live pipeline.

Currently at 17 patterns, driven by a √2 demo proof and a Wilson's-theorem
stress test. See CLAUDE.md for the detailed history/gotchas already found
(Mathlib import naming, `nlinarith`/`interval_cases`/`linear_combination`
import requirements, etc.) — don't rediscover these.

## Priority 3: known open issues (pre-existing, still true)

- **Concurrency/memory**: `_LEAN_CONCURRENCY_LIMIT` in `real_pipeline.py`
  is 2. If verification quality looks bad, check free memory before
  touching the formalization prompt — see CLAUDE.md's detailed notes, and
  the Priority-1 regression above.
- **Fuzzy text-layer matching** (`textLayerMatch.ts`'s `diceCoefficient`)
  is a bigram-overlap heuristic, not a full edit-distance algorithm — cheap
  and has worked on every case tested so far, but hasn't been stress-tested
  against unusual macros/symbols beyond what's in the three example proofs
  and Wilson's theorem.
- **Deployment** (containerizing Lean+Mathlib, now also a LaTeX toolchain)
  — still deliberately deferred, user wants to keep trying locally. This
  session added a second heavy local-machine dependency (MiKTeX) to the
  same deferred pile as Lean+Mathlib; nothing new needed here beyond
  awareness that deployment now has two hard toolchain dependencies to
  containerize, not one.
- **More pre-loaded example proofs** — still just 3 in `frontend/src/App.tsx`'s
  `EXAMPLES` array, unchanged this session.

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
assuming. **Remember the backend needs restarting after every backend code
change** (no `--reload` — see above).

Backend needs `backend/.env` with `ANTHROPIC_API_KEY=...` (gitignored, not
in the repo — check it's actually there and has a valid key **with
credit** before assuming a bug when something fails).

Run tests with:
```
cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q \
  --ignore=tests/test_lean_verifier.py --ignore=tests/test_cookbook_patterns.py
```
(fast, ~43 tests, no real Lean subprocesses, all passing as of this
session's last commit). Both ignored files are slow — run them separately
when touching `lean_verifier.py` or `lean_cookbook/`.

**Be deliberate about API cost.** Each full pipeline run through the live
UI costs one decompose call plus one formalize+verify call per step plus
one advisory call. Test Lean/cookbook changes locally against `tark_lean/`
first (free, seconds) and only run the full live pipeline to confirm a fix
actually lands, not to iterate on it.
