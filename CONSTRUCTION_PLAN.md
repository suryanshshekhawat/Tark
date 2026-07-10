# Tark — MVP Requirements & Architecture
**15-day build spec for Coding Fest 2026 (P44 Honours)**

---

## 1. Core Principle (do not violate this anywhere in the codebase)

> **Claude proposes. Verifiers dispose.**

Claude (the LLM) is *never* the source of a correctness claim. Its jobs are:
1. Decompose a proof into atomic steps.
2. Propose a formalization of each step — either as a **Lean 4 statement+tactic attempt** or a **computational check** (SymPy/Python) — whichever fits the step.
3. Suggest where it *suspects* a problem (a separate, clearly-labeled advisory layer).

The only things allowed to produce a `VERIFIED` verdict are:
- **Lean 4** compiling/type-checking a formalized statement against Mathlib, or
- **SymPy/Python** executing a deterministic computational check that passes.

If a step cannot be formalized by either backend, it is marked `UNVERIFIED — could not be checked`, full stop. This is not a fallback to be hidden; it is a first-class, visible outcome. No paraphrasing this as "likely correct."

This principle is the entire pitch. Every architecture decision below exists to protect it.

---

## 2. Outcome we're building toward

A web app where a user pastes a number-theory proof (LaTeX or plain text) and gets back, live:
- A decomposition into numbered steps with dependencies.
- Per-step verdict: `VERIFIED (Lean)`, `VERIFIED (Computational)`, `UNVERIFIED`, or `REFUTED`.
- The actual Lean compiler output / SymPy check output as evidence for each `VERIFIED`/`REFUTED` step — not Claude's word for it.
- A separate "Claude's notes" panel per step: suspected issues, style comments — explicitly labeled as unverified opinion, visually distinct from the verdicts above.
- An overall proof status: `FULLY VERIFIED` only if every step is Lean/SymPy-verified; otherwise `PARTIALLY VERIFIED (n/m steps)` with the gaps named.

## 3. Explicit non-goals for this build (v1 — poster's fuller vision is the roadmap, see §13)

- No persistent knowledge archive / theorem store across sessions.
- No adversarial LLM-vs-LLM dialogue (Lean's compiler *is* the adversary — see §8.3).
- No belief-tracker graph UI.
- No multi-model routing — Claude only.
- No domains beyond elementary number theory.
- No auth/multi-user/deployment infra until the tool works locally end-to-end (deployment is a stretch goal near day 13–15).

---

## 4. Scope

- **Domain:** elementary number theory (divisibility, primes, gcd/lcm, modular arithmetic, irrationality proofs, basic Diophantine claims) — the poster's own √2/gcd example is a good north star for what "in scope" looks like.
- **Input:** LaTeX only. Not plaintext, not "natural language proof" — the user pastes a reasonably well-formed LaTeX proof (this is a hard scope cut from the poster, which advertised plaintext/NL input too; v1 does not support that). See §4a for what "valid enough" means and how we handle the rest.
- **Output:** structured step-by-step report rendered live in the browser, **interactively linked back to the source LaTeX** (see §10a), + downloadable report (JSON + human-readable markdown/PDF).

### 4a. Input validation & exception handling

LaTeX input is messy by nature (unbalanced braces, unknown macros, partial documents, stray `\begin{document}` wrappers, users pasting from Overleaf with full preambles). This needs its own explicit stage — don't let malformed input silently corrupt the decomposition step.

**Validation pipeline (before any Claude call):**
1. **Structural check** — parse with a LaTeX parser (e.g. `pylatexenc` or a small custom brace/environment balancer) to catch: unbalanced `{}`/`\begin`...`\end`, unterminated math mode (`$...$`, `\[...\]`), obviously truncated input.
2. **Normalization** — strip preamble/document wrappers if present (`\documentclass`, `\usepackage`, everything outside `\begin{document}...\end{document}`) so the pipeline only ever sees the proof body, not the whole document.
3. **Soft-fail, not hard-fail** — if the parser finds issues that are recoverable (e.g. missing a closing `$`), attempt a best-effort repair and flag it to the user ("we auto-closed an unmatched `$` at position 412 — please check this wasn't intentional") rather than rejecting outright. LaTeX pasted by hand is very often *slightly* malformed; being too strict makes the tool unusable.
4. **Hard-fail cases** — reject with a clear, specific error (not a generic 400) when: input is empty, input contains no math content at all (e.g. it's just prose with no LaTeX), or structural errors are too severe to safely auto-repair (e.g. mismatched environment nesting that changes meaning). The error message should point to the specific location — "unbalanced `\begin{align}` starting at line 6, no matching `\end{align}` found" — not just "invalid LaTeX."
5. **Exception handling downstream** — every subsequent stage (Claude decomposition, Lean generation, verification) must assume the *input* is now clean, but must still handle its own failure modes gracefully (Claude returning malformed JSON, Lean subprocess crashing, timeout) without ever crashing the whole pipeline — a failure at step S4 should not prevent S1–S3's results from being shown.

This validation stage needs its own step in the pipeline (see §6, §12) and its own error schema so the frontend can render a specific, actionable message rather than a generic failure state.

---

## 5. High-Level Architecture

```
┌─────────────┐    paste proof    ┌──────────────────┐
│   Frontend   │ ────────────────▶│   Backend API      │
│  (React)     │◀──── stream ─────│   (FastAPI)         │
└─────────────┘   step results    └─────────┬─────────┘
                                             │
                          ┌──────────────────┼───────────────────┐
                          ▼                                      ▼
                 ┌──────────────────┐                  ┌──────────────────┐
                 │  Claude API      │                  │  Verifier Router  │
                 │  (decompose +    │                  │  (per-step)        │
                 │  formalize +     │                  └────────┬──────────┘
                 │  flag issues)    │                            │
                 └──────────────────┘                 ┌──────────┴──────────┐
                                                        ▼                     ▼
                                              ┌──────────────────┐  ┌──────────────────┐
                                              │  Lean Verifier    │  │  SymPy Verifier   │
                                              │  (subprocess,     │  │  (sandboxed exec) │
                                              │   Mathlib)        │  │                    │
                                              └──────────────────┘  └──────────────────┘
```

The **Verifier Router** is a pluggable interface (`Verifier.check(step) -> VerdictResult`) so a third backend (e.g. Z3 for later) can be added without touching the pipeline. This is the one piece of architectural "rigor" worth building in from day 1, because everything else compounds on top of it.

---

## 6. Pipeline stages (per proof submission)

1. **Ingest + validate** — accept raw LaTeX, run it through §4a's validation pipeline. Reject with a specific, located error if it fails hard-fail checks; auto-repair and flag if soft-fail; otherwise pass the normalized LaTeX (proof body only) downstream.
2. **Decompose** (Claude call #1) — split into atomic steps. Each step gets:
   - `id`, `statement` (plain language + any math), `depends_on: [ids]`
   - a first-pass `classification`: `"lean_candidate"` | `"computational"` | `"unformalizable"`
   - **`source_span`: `{start, end}`** — character offsets into the normalized LaTeX source that this step corresponds to. This is what makes the report interactive (§10a) — Claude must be prompted explicitly to return these offsets (or a quoted anchor substring the backend can locate via string search as a fallback if offsets drift).
3. **Formalize** (Claude call #2, per step, parallelizable):
   - if `lean_candidate`: generate a Lean 4 statement + tactic proof attempt (Mathlib imports allowed)
   - if `computational`: generate a Python/SymPy snippet whose truthiness proves/refutes the step
   - if `unformalizable`: skip formalization, go straight to `UNVERIFIED`, with Claude's reasoning for *why* it can't be formalized attached as a note
4. **Verify** (no LLM involved):
   - Lean steps → run through Lean Verifier (§8)
   - Computational steps → run through SymPy Verifier (§9)
5. **Repair loop** (bounded retries — see §8.3): if Lean rejects due to a *syntax* error (not a genuine proof gap), feed the compiler error back to Claude once/twice to fix the Lean code and retry. Cap at 3 attempts total per step. If still failing after retries, the step's verdict is decided by the *nature* of the last failure (see §11) — never silently marked verified.
6. **Advisory pass** (Claude call #3, separate from verification) — Claude reviews the whole proof and flags anything it's suspicious of, independent of what Lean/SymPy found. Rendered in its own "Claude's Notes" section, never merged into the verdict.
7. **Aggregate + report** — compute overall status, assemble JSON, render to frontend, offer markdown/PDF export.

---

## 7. Data model

```jsonc
// Step object
{
  "id": "S4",
  "statement": "gcd(p, q) = 1",
  "source_span": {"start": 412, "end": 468, "anchor_text": "\\gcd(p, q) = 1"},
  "depends_on": ["S1", "S3"],
  "classification": "lean_candidate", // | "computational" | "unformalizable"
  "formalization": {
    "lean_code": "theorem s4 : Nat.gcd p q = 1 := by ...",
    "attempts": 2,
    "python_code": null
  },
  "verdict": "VERIFIED", // | "REFUTED" | "UNVERIFIED"
  "verifier": "lean",     // | "sympy" | null
  "evidence": {
    "raw_output": "<lean compiler stdout/stderr>",
    "exit_code": 0
  },
  "claude_notes": [
    {"type": "suspicion", "text": "This step silently assumes p, q coprime from S1, which wasn't stated explicitly."}
  ]
}
```

```jsonc
// Top-level report
{
  "overall_status": "PARTIALLY_VERIFIED", // | "FULLY_VERIFIED" | "REFUTED_SOMEWHERE"
  "steps_verified": 6,
  "steps_total": 7,
  "normalized_source": "<the cleaned LaTeX body the whole pipeline actually ran against>",
  "steps": [ /* Step objects */ ],
  "claude_global_notes": [ "..." ]
}
```

```jsonc
// Ingest error (returned instead of a report when validation hard-fails)
{
  "error_type": "unbalanced_environment", // | "empty_input" | "no_math_content" | "unrecoverable_structure"
  "message": "Unbalanced \\begin{align} starting at line 6 — no matching \\end{align} found.",
  "location": {"line": 6, "char_offset": 210},
  "auto_repairs_attempted": [
    {"issue": "unmatched $ at offset 412", "action": "auto-closed", "confidence": "medium"}
  ]
}
```

This schema is the contract between backend and frontend — build it first, then both sides can be developed in parallel.

---

## 8. Lean 4 Integration

### 8.1 Toolchain (local for now, per your answer)
- `elan` for Lean version management, project pinned via `lakefile.lean` / `lake-manifest.json`.
- Mathlib as a dependency. **Build Mathlib's cache once, up front** — a cold Mathlib build can take 30–60+ minutes; do this on day 1–2 and never again. Use `lake exe cache get` if available for your Mathlib version to pull prebuilt `.olean` files instead of compiling from source.
- Keep a single warm Lean project directory (`tark_lean/`) that the backend writes temp files into and invokes `lake env lean <file>.lean` against, rather than spinning up a fresh project per request.

### 8.2 Execution
- Each Lean check runs as a subprocess with a **hard timeout** (e.g. 20–30s) — number theory proofs on Mathlib shouldn't need more; anything that hangs is treated as `UNVERIFIED (timeout)`.
- Capture stdout/stderr verbatim — this is the "evidence" shown to the user. Never summarize Lean's own output through Claude; show it raw (users can toggle a "explain this error in plain English" button that calls Claude separately, clearly labeled as an LLM explanation of the Lean log, not a new verdict).
- Run subprocesses in a restricted working directory, no network access, resource-limited (cgroup/ulimit if on Linux) — Claude-generated code should never be trusted with full system access.

### 8.3 The repair loop *is* your adversarial mechanism
Instead of the poster's LLM-vs-LLM adversarial dialogue, use Lean's compiler as the adversary:
1. Claude proposes Lean code for a step.
2. Lean either accepts, or rejects with a specific error (syntax error vs. `sorry`/incomplete proof vs. genuine type mismatch).
3. If it's a *syntax*/tactic-level failure, feed the error back to Claude with the original step statement and ask for a corrected attempt. Max 3 rounds.
4. If Lean explicitly rejects the mathematical claim (not just syntax), that's a `REFUTED` — surface it immediately, don't retry-loop trying to force a pass.

This gets you a real "adversarial tension surfaces gaps" story for the demo, grounded in an actual compiler rather than a second LLM performance.

---

## 9. SymPy / Computational Verification

- For steps like "1000003 is prime", "gcd(48, 18) = 6", "no integer solutions for x²+y²=... below N" — Claude generates a small Python snippet using `sympy` (or plain arithmetic) that evaluates to `True`/`False` for the claim.
- Run in a **sandboxed subprocess** (separate process, no filesystem/network access, timeout ~5–10s, restricted builtins). Do not `eval()` in-process.
- Verdict is purely mechanical: script raises/returns False → `REFUTED`; returns True → `VERIFIED (Computational)`; times out or errors unexpectedly → `UNVERIFIED`.
- This backend is *much* faster to build than Lean and a good place to get an end-to-end pipeline working on day 2–3 before Lean is fully wired in — build Lean and SymPy as parallel workstreams for the two team members.

---

## 10. Frontend UX

- **Input screen:** textarea for pasting **LaTeX** (make this explicit in the placeholder/copy — "Paste a LaTeX proof" not "Paste your proof," to set expectations), a "Verify" button, maybe 2–3 example proofs pre-loaded as one-click demos (safe fallback if live Lean is slow during the actual demo). On submit, if ingest validation hard-fails, show the located error inline (§4a/§6 error schema) pointing at the offending line/offset — do not just show a generic "invalid input" toast.
- **Live report view:** as steps come back (stream via Server-Sent Events or simple polling — SSE is easy in FastAPI and looks great live), render step cards top-to-bottom:
  - Step statement + dependency chips
  - Verdict badge (color-coded: green `VERIFIED`, red `REFUTED`, amber `UNVERIFIED`)
  - Expandable raw evidence (Lean/SymPy output)
  - Separate, visually distinct "Claude's notes" chip if present
- **Summary header:** overall verdict, X/Y steps verified, one-line explanation of what "verified" actually guarantees (be explicit in the UI copy: *"Verified steps are checked by the Lean 4 theorem prover or by executable computation — not by the AI's judgment."*)
- **Export:** "Download report" → JSON + a rendered markdown/PDF version.

Keep the UI honest and slightly austere rather than "impressive AI demo" styled — the credibility story depends on the UI never blurring the line between "Claude said so" and "Lean/SymPy proved so."

### 10a. Interactive, source-linked report (this is the centerpiece interaction, build it deliberately)

**Layout: split view.**
- **Left pane:** the normalized LaTeX source, rendered (KaTeX/MathJax) with the original text still addressable — wrap each step's `source_span` in a `<span data-step-id="S4">` so it can be targeted by CSS/JS without breaking the math rendering.
- **Right pane:** the scrollable list of step cards from above.

**Interaction:**
- Hovering or clicking a step card **highlights the corresponding span in the source pane** (background color matching the verdict: green/red/amber tint) and scrolls it into view if off-screen.
- Hovering/clicking a highlighted region in the *source* pane does the reverse — scrolls to and briefly emphasizes the matching step card. Two-way linking, not just one direction.
- Dependency chips (`depends_on`) are clickable and jump to the referenced step, so a user can trace *why* a step is (or isn't) grounded.
- If Claude's returned `source_span` offsets don't cleanly match the normalized source (drift from token-counting errors, whitespace differences), **fall back to fuzzy string matching on `anchor_text`** rather than showing a broken highlight or silently failing — this fallback should be built from day one, not treated as an edge case, because span drift from LLM-returned offsets is the common case, not the rare one.
- Steps that are `unformalizable`/`UNVERIFIED` should highlight distinctly (e.g. dashed amber border) so a user scanning the source can immediately see "this part of my proof has no formal backing" without opening anything.

This span-linking is what turns the report from "a list of AI opinions" into "an annotated version of your actual proof" — worth the extra build time relative to a flat step list.

---

## 11. Verdict semantics (be strict about this)

| Verdict | Meaning | Who decides |
|---|---|---|
| `VERIFIED (Lean)` | Lean type-checked a formalization of this exact step against Mathlib | Lean compiler |
| `VERIFIED (Computational)` | A deterministic script confirmed the claim | Python/SymPy execution |
| `REFUTED` | Lean explicitly rejected the mathematical content (not a syntax issue), or the computational check returned False | Lean/SymPy |
| `UNVERIFIED` | Could not be formalized in either backend, or formalization attempts were exhausted without a clean verdict, or timed out | Default/fallback — never assigned by Claude asserting confidence |

Overall proof status:
- `FULLY_VERIFIED` — every step is `VERIFIED (*)`.
- `REFUTED_SOMEWHERE` — at least one step is `REFUTED`.
- `PARTIALLY_VERIFIED` — mix of verified and unverified, none refuted.

---

## 12. 15-Day Plan

**Days 1–2 — Foundations (parallel work)**
- Person A: stand up Lean 4 + Mathlib locally, get cache built, write a minimal script that takes a Lean snippet string and returns compile success/failure + raw output.
- Person B: stand up FastAPI backend skeleton + React frontend skeleton, define the JSON schema (§6) including `source_span`/error schema, build the LaTeX validation stage (§4a) and the SSE streaming plumbing with fake/mocked step data.

**Days 3–5 — Core pipeline v1**
- Wire Claude API for decomposition (stage 2) and per-step formalization (stage 3) with the classification logic.
- Build SymPy verifier (fast, low-risk) and wire it fully end-to-end first — this gives you a working demo skeleton early.
- Start wiring Lean verifier into the same pipeline behind the `Verifier` interface.

**Days 6–8 — Lean integration + repair loop**
- Get the Lean verifier fully working against 3–5 hand-picked number theory proofs (know these cold; they're your demo safety net).
- Implement the bounded repair loop (§8.3).
- Handle timeouts, sandboxing, error classification (syntax vs. genuine rejection).

**Days 9–10 — Advisory layer + UI polish**
- Add the separate Claude "notes/suspicions" pass (stage 6), keep it visually and structurally separate from verdicts.
- Build out the full frontend report view: split-pane interactive highlighting (§10a), summary header, export. Prioritize the `anchor_text` fuzzy-match fallback before polishing visuals — a highlight that silently fails to appear is worse than an ugly one that always works.

**Days 11–12 — Robustness pass**
- Test against a wider set of number theory proofs (including proofs you *expect* to partially fail — you want visible `UNVERIFIED`/`REFUTED` cases in the demo, not just green checkmarks, to prove the tool isn't rubber-stamping).
- Tighten sandboxing on both verifiers.
- Add the pre-loaded example proofs as a demo fallback.

**Days 13–14 — Deployment attempt + buffer**
- Attempt a deployment (containerize Lean+Mathlib is the hard part — expect this to eat most of the time; have a "runs locally, demo via screen share/local host" fallback ready regardless).
- Bug buffer.

**Day 15 — Demo prep**
- Rehearse the demo on your 3–5 known-good proofs plus at least one proof that produces a genuine `UNVERIFIED` or `REFUTED` result — that's the credibility moment.

---

## 13. Stretch goals / roadmap (poster's fuller vision — not v1)

- Persistent knowledge archive (indexed theorem/strategy store, retrieval-augmented formalization).
- Belief tracker / dependency graph across a full paper, not just one proof.
- Additional verifier backends (Z3/SMT for certain claims).
- Additional math domains (real analysis, abstract algebra).
- Multi-model routing, agentic verification network.
- Benchmarking against QED-Bench/APE.
- Hosted deployment, opt-in pilot with a partner journal/arXiv moderation team.

---

## 14. Tech Stack

- **Backend:** Python, FastAPI, SSE for streaming, `anthropic` SDK for Claude calls.
- **Lean:** Lean 4 + Mathlib via `elan`/`lake`, invoked via subprocess.
- **Computational:** `sympy`, sandboxed subprocess execution (restricted builtins, resource limits).
- **Frontend:** React (Vite), plain CSS or Tailwind — keep it simple, avoid framework overhead that eats build time.
- **Storage:** none required for v1 beyond in-memory/session state; add SQLite only if you want submission history.

---

## 15. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Cold Mathlib build eats days 1–2 | Build/cache it on day 1 immediately, before anything else; use prebuilt `.olean` cache if version-compatible |
| Claude generates Lean code that doesn't compile at all (not just wrong proof) | Bounded repair loop (§8.3); after 3 failed attempts, classify as `UNVERIFIED` rather than looping forever |
| Sandboxed Python/Lean execution has security holes | No network access, restricted filesystem, timeouts, resource limits on every subprocess — treat all generated code as untrusted |
| Demo depends on live Lean compilation which can be slow/flaky | Pre-loaded example proofs with cached results as a fallback; keep timeouts tight and visible in UI ("verifying... 4s") |
| Scope creep toward poster's full vision | This document is the scope; anything in §13 is explicitly out until v1 is solid |
| Claude's `source_span` offsets drift from the actual normalized source | Build the `anchor_text` fuzzy-match fallback from day one (§10a) — treat offset drift as the expected case, not an exception |
| Users paste malformed/partial LaTeX (missing preamble handling, unbalanced braces) | Dedicated validation stage (§4a) with soft-repair for recoverable issues and specific, located error messages for hard failures |