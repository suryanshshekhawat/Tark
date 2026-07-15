---
title: m divides x implies x cast to ZMod m is zero
tags: [modular-arithmetic, zmod, divisibility]
verified: 2026-07-14
when_to_use: >
  The step claims "x ≡ 0 (mod m)" and what's actually in hand is a
  divisibility fact "m ∣ x" (e.g. having just shown p^2 divides a
  factorial and needing that phrased as a ZMod congruence to combine with
  other congruence-style steps).
gotchas: >
  The correct lemma name is `ZMod.natCast_eq_zero_iff` — a live attempt
  used `ZMod.natCast_zmod_eq_zero_iff_dvd`, which does not exist under
  that name (confirmed via the compiler's `unknown constant` error, then
  by grepping `Mathlib/Data/ZMod/Basic.lean` directly for the real name).
  This is exactly the kind of plausible-sounding-but-wrong lemma name
  Claude's training data produces for ZMod/Nat.cast bridging lemmas —
  don't trust a name here without having compiled it.
---

```lean
import Mathlib.Data.Nat.Factorial.Basic
import Mathlib.Data.ZMod.Basic

theorem factorial_dvd_implies_zero_mod (n p : ℕ) (h : p ^ 2 ∣ Nat.factorial (n - 1)) :
    (Nat.factorial (n - 1) : ZMod (p ^ 2)) = 0 :=
  (ZMod.natCast_eq_zero_iff (Nat.factorial (n - 1)) (p ^ 2)).mpr h
```
