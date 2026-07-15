---
title: A prime squared divides a factorial via two distinct multiples
tags: [factorials, divisibility, primes]
verified: 2026-07-14
when_to_use: >
  The step claims p^2 divides (n-1)! (or n!) because two distinct multiples
  of p (typically p and 2p) both occur among the factors — i.e. the
  factorial's multiplicity of p is at least 2.
gotchas: >
  Don't `rw` an equation like `2 * p = (2 * p - 1) + 1` in place —
  `2 * p - 1` still textually contains `2 * p`, so the rewrite doesn't
  normalize cleanly. Introduce a fresh opaque variable q first
  (`obtain ⟨q, hq⟩ : ∃ q, 2 * p = q + 1 := ...`) to avoid the
  self-reference. Needs `Mathlib.Tactic.Ring` for the final `ring` call —
  easy to forget since the rest of the proof is otherwise import-light.
---

```lean
import Mathlib.Data.Nat.Factorial.Basic
import Mathlib.Tactic.Ring

theorem ex8 (n p : ℕ) (hp : 0 < p) (h2p : 2 * p ≤ n - 1) :
    p ^ 2 ∣ Nat.factorial (n - 1) := by
  obtain ⟨q, hq⟩ : ∃ q, 2 * p = q + 1 := ⟨2 * p - 1, by omega⟩
  have hp_le : p ≤ q := by omega
  obtain ⟨k, hk⟩ := Nat.dvd_factorial hp hp_le
  have h2 : Nat.factorial (2 * p) = (2 * p) * (p * k) := by
    rw [hq, Nat.factorial_succ, hk]
  have h4 : p ^ 2 ∣ Nat.factorial (2 * p) := by
    rw [h2]
    exact ⟨2 * k, by ring⟩
  have h5 : Nat.factorial (2 * p) ∣ Nat.factorial (n - 1) := Nat.factorial_dvd_factorial h2p
  exact h4.trans h5
```
