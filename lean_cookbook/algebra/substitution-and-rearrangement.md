---
title: Pure algebraic substitution/rearrangement
tags: [algebra, ring, substitution]
verified: 2026-07-14
when_to_use: >
  The step is a purely mechanical algebraic rewrite of an equation with free
  variables — substituting one hypothesis into another and simplifying.
  Prefer `ring_nf` + `omega` over manual term-by-term rewriting.
---

```lean
import Mathlib.Tactic.Ring

theorem ex4 (p q k : ℕ) (hp : p = 2 * k) (h : p ^ 2 = 2 * q ^ 2) : 4 * k ^ 2 = 2 * q ^ 2 := by
  subst hp
  ring_nf
  ring_nf at h
  omega
```
