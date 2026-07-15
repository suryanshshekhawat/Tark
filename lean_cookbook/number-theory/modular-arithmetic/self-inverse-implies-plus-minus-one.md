---
title: A self-inverse element mod a prime is 1 or -1
tags: [modular-arithmetic, primes, zmod]
verified: 2026-07-14
when_to_use: >
  The step claims that if a^2 = 1 (mod n) for n prime, then a = 1 or a = -1
  (mod n) — e.g. "an element is its own inverse precisely when a^2 = 1,
  which factors as (a-1)(a+1) = 0, so a = 1 or a = -1" in a proof about
  units mod a prime (this is the key step of the standard Wilson's-theorem
  pairing argument, but is a self-contained fact useful anywhere the same
  shape appears).
gotchas: >
  Work in `ZMod n`, not `Nat.ModEq` with raw subtraction — `a - 1` in `ℕ`
  truncates at 0 and makes the factoring identity awkward to state, let
  alone prove. `ZMod n` is a genuine commutative ring (a field when `n` is
  prime via the `Fact n.Prime` instance), so `(a-1)*(a+1) = a^2 - 1` is a
  normal ring identity and `mul_eq_zero` needs a `NoZeroDivisors` instance
  — pull that in via `Mathlib.FieldTheory.Finite.Basic` (the same import
  Mathlib's own Wilson's theorem proof uses), not the lighter
  `Mathlib.Data.ZMod.Basic` (`Mathlib.Data.ZMod.Basic` alone does NOT
  provide a field/`NoZeroDivisors` instance for `ZMod n` — checked
  directly, there is no cheaper import for this fact). This import is
  measured at 58s warm and up to 3m10s under memory pressure — needs a
  longer timeout allowance than most patterns in this cookbook (~45s is not
  enough even on a healthy system).
---

```lean
import Mathlib.FieldTheory.Finite.Basic
import Mathlib.Tactic.Ring

theorem ex11 (n : ℕ) [Fact n.Prime] (a : ZMod n) (h : a ^ 2 = 1) : a = 1 ∨ a = -1 := by
  have hfactor : (a - 1) * (a + 1) = 0 := by
    have expand : (a - 1) * (a + 1) = a ^ 2 - 1 := by ring
    rw [expand, h]; ring
  rcases mul_eq_zero.mp hfactor with h1 | h2
  · left; exact sub_eq_zero.mp h1
  · right; exact eq_neg_of_add_eq_zero_left h2
```
