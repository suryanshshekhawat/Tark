# Lean strategy cookbook

This directory is Tark's growing library of hand-verified Lean 4 / Mathlib
proof patterns. It exists because Claude's training data is unreliable on
precise, frequently-reorganized Mathlib bookkeeping (import paths, lemma
names, notation scoping) even for "obvious" facts — see `CLAUDE.md` at the
repo root for the concrete incidents that proved this. Giving the
formalization stage worked, pre-verified examples to adapt from — instead of
reconstructing an approach from memory every time — is the single
highest-leverage lever in the whole pipeline. On the original demo proof it
took the Lean verification rate from 0/10 to 8/8.

This file is written for two audiences at once, deliberately: an AI agent
extending this cookbook autonomously, and a human mathematician or
programmer browsing it by hand. Both need the same thing — a structure that
stays legible as it grows from 9 patterns to 900.

## How this directory is used

`backend/app/pipeline/cookbook_loader.py` walks this directory at runtime,
parses every pattern file, and assembles them into the system prompt used
for Lean formalization (see `formalize.py`). Nothing in this directory is
hand-copied into Python — **adding a `.md` file here is the entire
integration step.** There is no second place to register a new pattern.

`_prelude.md` is special: it's the general rules (import discipline, timeout
budget, notation gotchas) that apply regardless of which pattern is used,
and is always included first. Everything else under the category
directories is a pattern.

## Directory structure

```
lean_cookbook/
  README.md              <- you are here
  _prelude.md             <- general rules, always included
  <branch>/               <- top-level mathematical branch (e.g. number-theory, algebra)
    <subtopic>/            <- narrower grouping within the branch (e.g. parity, factorials)
      <pattern-name>.md    <- one proof pattern per file
```

Two levels of nesting (branch / subtopic) is the target depth. Don't nest
deeper than that — if a subtopic is big enough to need its own
sub-subtopics, it's a sign the subtopic should split into two subtopics at
the same level instead. Don't leave patterns loose at the branch root
either — every pattern belongs in some subtopic, even if that subtopic
currently has only one file in it.

Current branches:
- `number-theory/` — parity, gcd-and-coprimality, factorials, primes,
  irrationality, modular-arithmetic, ...
- `algebra/` — pure algebraic manipulation not specific to a number-theoretic
  concept (substitution, rearrangement, ring/field identities).

When a paper introduces a genuinely new branch (combinatorics, graph theory,
whatever comes next), add a new top-level directory for it rather than
forcing it under `number-theory/`. When you're unsure whether something is
a new subtopic or belongs in an existing one, prefer reusing an existing
subtopic — a subtopic with 8 loosely-related patterns is easier to navigate
than 8 subtopics with 1 pattern each. Split later if it actually gets
crowded.

## Pattern file format

Every pattern is one Markdown file with YAML-ish frontmatter followed by a
single fenced ```lean code block:

```markdown
---
title: Short, specific, human-readable name
tags: [optional, freeform, keywords]
verified: 2026-07-14
when_to_use: >
  The one paragraph that matters most. Describe the SHAPE of the proof step
  this pattern matches, concretely enough that both a human skimming this
  file and an LLM reading it as part of a system prompt can recognize "this
  is my situation" without already knowing the answer.
gotchas: >
  Optional. Anything non-obvious you had to discover by trial and error —
  a renamed import, a tactic that needs an easy-to-forget dependency, a
  rewrite that loops, whatever cost you time. This field is where the
  actual hard-won knowledge lives; don't skip it just because the proof
  compiles fine.
---

​```lean
import Mathlib.Whatever.Path

theorem example_name (...) : ... := by
  ...
​```
```

Required fields: `title`, `when_to_use`. Everything else is optional but
`gotchas` is strongly encouraged whenever there was one — a pattern that
"just worked" first try is rarer than it looks, and future sessions
shouldn't have to rediscover the same trap.

The `verified` date is a freshness signal, not a guarantee — Mathlib moves.
If you re-verify an existing pattern (e.g. because a Mathlib upgrade broke
it and you fixed it), bump the date.

## Adding a new pattern — the required workflow

This is not optional process for its own sake — skipping steps here is
exactly how a plausible-looking but non-compiling pattern gets into the
cookbook and silently poisons every future step that matches it.

1. **Test the Lean snippet directly against `tark_lean/` first**, not
   through the full pipeline:
   ```
   cd tark_lean && lake env lean path/to/scratch_test.lean
   ```
   This is seconds, versus minutes through decompose → formalize → verify.
   Do this in `tark_lean/.tark_scratch/` (gitignored scratch space) or
   anywhere temporary — never commit the scratch file itself.
2. Once it compiles cleanly (no errors, no `sorry`), write the permanent
   `.md` file in the right branch/subtopic, following the format above.
3. **Run the cookbook regression test**:
   ```
   cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_cookbook_patterns.py -q
   ```
   This test discovers every pattern file (including your new one),
   extracts its Lean code, and recompiles it against `tark_lean/`
   independently. It exists specifically so that a new pattern, or a
   Mathlib version bump, can't silently break an existing one without
   being caught — **never skip running it after adding or editing a
   pattern.** This is the concrete mechanism behind "improvements are in
   no way regressive" — it's not a promise, it's an enforced test.
4. Only after both of those pass, optionally confirm the improvement lands
   through the full pipeline (costs an API call per affected step — budget
   for it, don't do this reflexively for every single pattern addition).

## What NOT to do

- **Don't edit `formalize.py` to add a pattern.** If you find yourself
  writing Lean code inside a Python string, stop — it belongs in a `.md`
  file here instead. `formalize.py` should only ever import the loader.
- **Don't duplicate a pattern that already exists with minor variable
  renaming.** If an existing pattern's `when_to_use` already covers your
  shape, that's a sign to adapt the existing file (bump `verified`, expand
  `when_to_use` if the new case reveals it was too narrow) rather than add
  a near-duplicate. A cookbook where ten files all say almost the same
  thing is harder to search than one that says it once, precisely.
- **Don't remove or narrow an existing pattern's `when_to_use` to make room
  for a new one that overlaps it.** If two patterns genuinely serve
  different shapes that happen to look similar, make the distinction
  explicit in both files' `when_to_use` instead of hoping context resolves
  it.
- **Don't add a pattern you haven't personally compiled.** A pattern that
  "should probably work" based on Mathlib documentation or training-data
  familiarity is exactly the failure mode this whole cookbook exists to
  prevent (see `CLAUDE.md`'s notes on renamed/nonexistent lemmas). If you
  can't run `lake env lean` in your current environment, don't add the
  pattern — flag it for someone who can, instead.

## Why Markdown-with-frontmatter, specifically

This format was chosen deliberately over alternatives:
- **Not a giant Python string** (the original v1 approach, in
  `formalize.py`) — unreadable in a diff once past a handful of patterns,
  and mixes prose/Lean/Python escaping in one file.
- **Not one-file-per-pattern in pure Lean** — metadata (`when_to_use`
  especially) has nowhere principled to live in a `.lean` file, and it's
  the metadata that lets both the AI and a human actually find the right
  pattern among hundreds.
- **Not a database or YAML-only catalog with Lean code as a separate
  file** — keeping the explanation and the code in the same file, visible
  in the same diff, is what makes `gotchas` actually get written instead of
  skipped.

Markdown-with-frontmatter is readable with zero tooling (any editor, GitHub,
a plain `cat`), diffable, greppable, and the loader that parses it is ~100
lines with no new dependency (see `cookbook_loader.py` — deliberately
hand-rolled rather than pulling in a YAML library, since the schema here is
intentionally small and constrained).
