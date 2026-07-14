# Handoff — read this first

Previous session ran low on context. Read [CLAUDE.md](CLAUDE.md) fully — it has
detailed, hard-won notes on nearly everything below, written as the bugs were
found. This file is the short version: what's done, what's open, what to do next.

## State: working, but not bulletproof

The pipeline works end-to-end with real Claude + Lean + SymPy. The √2-irrationality
demo proof gets `FULLY_VERIFIED` (8/8 Lean steps, 3 correctly `ASSUMED` as premises).
A messy real-world 16KB multi-theorem academic LaTeX excerpt (citations, custom
macros, non-proof content) decomposes and runs without crashing. But it's still
finding new bugs on every new input thrown at it — see "Open issues" below.

## Priority 1: expand the Lean cookbook

`backend/app/pipeline/formalize.py`'s `LEAN_SYSTEM_PROMPT` has 6 hand-verified Lean
snippets covering parity-of-squares, unpacking `Even`, gcd-of-two-evens, algebraic
substitution, squaring a `Real.sqrt` equation, and irrationality of `sqrt(p)`. This
is the single highest-leverage lever in the whole project — it took the demo proof's
Lean verification rate from 0/10 to 8/8. **The method, not just the current 6
entries, is what matters:**

1. Run a proof through the pipeline (curl or the browser UI — see "How to run
   locally" below).
2. For any `UNVERIFIED` `lean_candidate` step, look at its `evidence.raw_output`.
3. If it's an import/lemma-name error, don't guess a fix — grep the actual Mathlib
   source directly: `tark_lean/.lake/packages/mathlib/Mathlib/**/*.lean`. Find where
   the real lemma/definition lives now (Mathlib reorganizes constantly; multiple
   stale paths were found and fixed this way — see CLAUDE.md for the exact list).
4. Write a candidate fix, test it directly against `tark_lean/` — NOT through the
   full pipeline (much faster): `cd tark_lean && lake env lean path/to/test.lean`.
5. Once it compiles, add it to the cookbook as a new numbered pattern with a
   one-line note on when to use it and any import gotchas.
6. Re-run the same proof through the pipeline to confirm the fix actually lands.

The real-world test proof used in this session (a ceiling-function induction proof
about "cancelling sequences") mostly came back `UNVERIFIED` — that's genuinely hard
math (`⌈⌉`/`⌊⌋` arithmetic, divisibility case-splits) with zero cookbook coverage
right now. That's a good next target if you want a meaningfully harder proof to
cut your teeth on, distinct from more √2-shaped number theory.

## Priority 2: known open issues to chase

**"Claude's decomposition returned no steps" can still happen.** Two distinct root
causes were found and fixed this session:
- Input too large -> hits `max_tokens` mid-generation -> truncated/empty tool call.
  Fixed: raised budget to 8192, detect `stop_reason == "max_tokens"` explicitly,
  clear error message, prompt tells Claude to scope itself on multi-proof input.
- A *non-truncated* completion still occasionally returns an empty `steps` array
  (sampling variance, not reproduced with a live repro this session). Mitigated
  with one bounded retry in `decompose()`, but the actual root cause is still
  unknown. **If you can get a live repro:** add a debug print of the full raw
  Claude response before the empty-check in `_decompose_once` and see what it
  actually said — is it refusing because it thinks the input's out of scope? Is it
  a specific input shape that trips it? That's the real fix; the retry is a patch.

**RestrictedPython sandbox guards were found one at a time, live, three separate
times** (`_unpack_sequence_`/`_iter_unpack_sequence_`/`_inplacevar_`, then
`_getitem_`/`_write_`). All 7 guards the transformer can emit are now wired (see
`sympy_verifier.py` and CLAUDE.md), confirmed via grepping RestrictedPython's
source directly rather than guessing — that search should be the definitive list,
but if a fourth NameError on an underscore-prefixed name shows up, it means either
a new RestrictedPython version added something, or the grep missed it.

**Concurrency/memory**: `_LEAN_CONCURRENCY_LIMIT` in `real_pipeline.py` is set to 2,
tuned for a dev machine with ~2GB free RAM at the time. If verification quality
looks inexplicably bad (steps timing out that should be fast), check free memory
before touching any prompt — infrastructure contention and "genuinely hard to
formalize" produce the identical symptom (timeout) and need completely different
fixes. Excluding `tark_lean/` from Windows Defender real-time scanning was
identified as a likely win but never done (it's a system-settings change, outside
what Claude Code should do unilaterally — ask the user to do it if things still
feel slow).

## Priority 3: things not started

- **Deployment** (containerizing Lean+Mathlib) — deliberately deferred, user wanted
  to try the tool locally first. Docker is confirmed installed. The hard part will
  be `tark_lean/.lake`'s multi-GB Mathlib `.olean` cache.
- **More pre-loaded example proofs** — currently 3 (`√2 irrational`, `gcd &
  primality`, `even squares`) in `frontend/src/App.tsx`'s `EXAMPLES` array. Could
  use a 4th that reliably produces `REFUTED` via Lean specifically (currently only
  the SymPy path has a demonstrated `REFUTED` case).
- **Lean-side sandboxing** is narrower than SymPy's (subprocess isolation + timeout
  + process-tree-kill only, no OS-level resource/network ACLs) — accepted as
  proportionate given Claude is only ever asked for `theorem := by tactics`, not
  arbitrary `#eval`/`IO` code. Would need Windows Job Objects for anything stronger.

## How to run locally

```
# Backend
cd backend
./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 --host 127.0.0.1

# Frontend
cd frontend
npm run dev
```

Backend needs `backend/.env` with `ANTHROPIC_API_KEY=...` (gitignored, not in the
repo — check it's actually there and has a valid key with credit before assuming
a bug when something fails). Run tests with
`cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q
--ignore=tests/test_lean_verifier.py` (fast, ~35 tests). The Lean verifier tests are
excluded from that command because they're slow (real `lake env lean` calls,
~30-60s) — run them separately when touching `lean_verifier.py` specifically.

When testing changes to the Lean cookbook or verifier, test the Lean snippet
directly against `tark_lean/` first (see step 4 above) before running the full
pipeline — it's the difference between a few seconds and a multi-minute round trip
through decomposition + formalization + verification.
