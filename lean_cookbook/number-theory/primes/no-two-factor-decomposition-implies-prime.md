---
title: No decomposition into two factors >= 2 implies prime
tags: [primes, factorization, contradiction]
verified: 2026-07-14
when_to_use: >
  The step concludes n is prime FROM the absence of any factorization
  n = a*b with a,b >= 2 — the converse direction of "composite means
  factorable," typically the final step of a proof-by-contradiction
  structured as "every composite case leads to a contradiction, so n must
  be prime."
gotchas: >
  A live free-form attempt at this exact claim compiled but had a genuine
  logic bug, not an import/naming issue: after deriving `k = 1` in a
  by-contradiction sub-case, it tried to apply a hypothesis about `m ≠ 1`
  to a fact of type `n = m`, a straightforward Application type mismatch
  (visible directly in the compiler error) — the two facts happened to
  both be "the thing that's contradictory here" but weren't the same
  statement. When a `by_contra` sub-proof involves several `have`s chasing
  the same underlying contradiction from different angles, double-check
  each `exact`/`apply` is discharging the ACTUAL stated type of the
  hypothesis being applied, not just "some contradiction or other" that
  happens to be in scope.
---

```lean
import Mathlib.Data.Nat.Prime.Basic
import Mathlib.Tactic.IntervalCases

theorem composite_contradiction_implies_prime (n : ℕ) (hn2 : 2 ≤ n)
    (h : ¬ (∃ a b, 2 ≤ a ∧ 2 ≤ b ∧ n = a * b)) : Nat.Prime n := by
  rw [Nat.prime_def_lt]
  refine ⟨hn2, ?_⟩
  intro m hm hdvd
  by_contra hm1
  obtain ⟨k, hk⟩ := hdvd
  have hm2 : 2 ≤ m := by
    rcases Nat.eq_zero_or_pos m with rfl | hpos
    · simp at hk; omega
    · omega
  have hk2 : 2 ≤ k := by
    by_contra hklt
    push_neg at hklt
    interval_cases k <;> simp_all <;> omega
  exact h ⟨m, k, hm2, hk2, hk⟩
```
