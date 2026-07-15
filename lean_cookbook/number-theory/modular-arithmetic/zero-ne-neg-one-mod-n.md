---
title: 0 is never congruent to -1 modulo n (for n > 1)
tags: [modular-arithmetic, zmod, contradiction]
verified: 2026-07-14
when_to_use: >
  The step derives a contradiction from two congruences of the form
  "X ≡ 0 (mod n)" and "X ≡ -1 (mod n)" both holding — the standard final
  move in a Wilson's-theorem-style proof by contradiction, once one branch
  has shown the factorial is divisible by n (hence ≡ 0) while the working
  hypothesis says it's ≡ -1.
gotchas: >
  Don't reach for `linarith`/`linear_combination` here — a live attempt
  used `linear_combination` and got a `ring failed` error because the
  goal after substitution wasn't actually a ring identity in the way it
  assumed. The clean route is `eq_neg_iff_add_eq_zero.mp h` (turning
  `0 = -1` into `0 + 1 = 0`), then `zero_add` and `one_ne_zero` — no
  `ring`-family tactic needed at all, just equation rewriting plus the
  `Fact (1 < n)` instance that makes `ZMod n` nontrivial.
---

```lean
import Mathlib.Data.ZMod.Basic

theorem zero_ne_neg_one_mod_n (n : ℕ) (hn : 1 < n) (h : (0 : ZMod n) = -1) : False := by
  haveI : Fact (1 < n) := ⟨hn⟩
  have h1 : (0 : ZMod n) + 1 = 0 := eq_neg_iff_add_eq_zero.mp h
  rw [zero_add] at h1
  exact one_ne_zero h1
```
