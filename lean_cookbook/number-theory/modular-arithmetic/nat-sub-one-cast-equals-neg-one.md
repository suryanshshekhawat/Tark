---
title: (n-1) cast to ZMod n equals -1
tags: [modular-arithmetic, zmod]
verified: 2026-07-14
when_to_use: >
  The step's conclusion is "X ≡ -1 (mod n)" and what's actually in hand is
  "X ≡ n-1 (mod n)" — e.g. a product that was shown to equal n-1 needs one
  more step to be phrased as ≡ -1. This is a pure cast-arithmetic identity,
  not a new mathematical fact, but Claude's own free-form attempts at it
  reliably reach for `linarith`/`linear_combination` without the needed
  import and fail — cite this shape directly instead.
gotchas: >
  `linarith` does NOT work in `ZMod n` (it's not an ordered ring/field) —
  a live attempt at this exact step used `linarith` inside `ZMod n` and
  failed with an "unknown tactic" error because the required import was
  also missing, which obscured that the tactic choice itself was wrong.
  Use `eq_neg_of_add_eq_zero_left` (from `push_cast`ing the fact that
  ((n-1)+1 : ZMod n) = 0) instead — it's an equation-shuffling lemma, not
  an inequality-solving tactic, and needs no extra import beyond
  `Mathlib.Data.ZMod.Basic`.
---

```lean
import Mathlib.Data.Nat.Factorial.Basic
import Mathlib.Data.ZMod.Basic

theorem factorial_pairing_result (n : ℕ) (hn : 2 ≤ n)
    (h : (Nat.factorial (n - 1) : ZMod n) = ((n - 1 : ℕ) : ZMod n)) :
    (Nat.factorial (n - 1) : ZMod n) = -1 := by
  rw [h]
  have hnat : (n - 1) + 1 = n := by omega
  have h2 : (((n - 1) + 1 : ℕ) : ZMod n) = 0 := by
    rw [hnat, ZMod.natCast_self]
  push_cast at h2
  exact eq_neg_of_add_eq_zero_left h2
```
