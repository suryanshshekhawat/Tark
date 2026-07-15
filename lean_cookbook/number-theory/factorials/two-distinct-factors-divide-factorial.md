---
title: The product of any two distinct factors divides the factorial
tags: [factorials, divisibility]
verified: 2026-07-14
when_to_use: >
  The step claims a*b divides (n-1)! (or n!) because a and b are two
  DISTINCT positive integers both <= n-1 — the general case behind "since d
  and n/d are distinct integers strictly between 1 and n, both occur among
  the factors of (n-1)!, so d*(n/d) divides (n-1)!" (or similar phrasing
  about two named divisors both appearing as factors). This generalizes the
  narrower prime-squared pattern (which is specifically a and 2a) to any
  pair of distinct factors.
gotchas: >
  Split into two symmetric cases by which of a, b is smaller (`rcases
  lt_or_gt_of_ne hab with h | h`) rather than reaching for the `wlog`
  tactic — `wlog ... generalizing a b` generates a `this` hypothesis whose
  argument order/shape is easy to get wrong and not worth the fragility
  here; a small helper lemma for the `a < b` case plus `mul_comm` for the
  other order is more robust and easier to debug when it fails. When
  adapting this to a `d`, `n/d` framing (a divisor and its cofactor,
  instead of two already-named free variables) rather than applying it
  directly, two mistakes were caught live: (1) it's easy to state the new
  theorem WITHOUT an explicit `d ≠ n/d` hypothesis and then try to derive
  distinctness from nothing via a bare `omega`/`decide` call — if
  distinctness was established in an earlier proof step, it must be
  threaded through as an explicit hypothesis here, not re-derived; (2)
  deriving `d < n` from `n/d < n`-style hypotheses needs `nlinarith` (see
  the prelude's import note), and if `omega` alone fails on a goal
  involving `n / d` appearing in multiple hypotheses, `generalize` the
  division into a fresh variable first rather than fighting it directly.
  A related bound that keeps tripping up fresh attempts: proving `d < n`
  directly from `n = d * k` with `k > 1` (rather than from a `n / d < n`
  hypothesis) — `Nat.mul_lt_mul_left` in this Mathlib version is an `iff`,
  not a function (`(Nat.mul_lt_mul_left hd).mpr hk`, not
  `Nat.mul_lt_mul_left hd hk`), and a plausible-looking alternative like
  `Nat.mul_lt_mul_of_lt_of_le` has a different argument shape than it looks
  like it should. The reliable route: `calc d = d * 1 := (Nat.mul_one
  d).symm; _ < d * k := (Nat.mul_lt_mul_left hd).mpr hk`.
---

```lean
import Mathlib.Data.Nat.Factorial.Basic
import Mathlib.Tactic.Ring

theorem lt_case (n a b : ℕ) (ha : 0 < a) (hb2 : b ≤ n - 1) (hlt : a < b) :
    a * b ∣ Nat.factorial (n - 1) := by
  obtain ⟨q, hq⟩ : ∃ q, b = q + 1 := ⟨b - 1, by omega⟩
  have ha_le : a ≤ q := by omega
  obtain ⟨k, hk⟩ := Nat.dvd_factorial ha ha_le
  have hstep : Nat.factorial b = b * (a * k) := by rw [hq, Nat.factorial_succ, hk]
  have h1 : a * b ∣ Nat.factorial b := by
    rw [hstep]; exact ⟨k, by ring⟩
  exact h1.trans (Nat.factorial_dvd_factorial hb2)

theorem ex10 (n a b : ℕ) (ha : 0 < a) (ha2 : a ≤ n - 1) (hb : 0 < b) (hb2 : b ≤ n - 1)
    (hab : a ≠ b) : a * b ∣ Nat.factorial (n - 1) := by
  rcases lt_or_gt_of_ne hab with h | h
  · exact lt_case n a b ha hb2 h
  · rw [mul_comm]; exact lt_case n b a hb ha2 h
```
