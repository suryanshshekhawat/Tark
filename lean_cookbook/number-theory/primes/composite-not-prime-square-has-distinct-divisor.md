---
title: A composite number that isn't a prime square has two distinct proper divisors
tags: [primes, divisibility, factorization]
verified: 2026-07-14
when_to_use: >
  The step claims that a composite n, given it is NOT the square of a
  prime, has a divisor d with 1 < d < n and d ≠ n/d (i.e. a genuinely
  distinct divisor/cofactor pair) — the standard first case-split in
  proofs that reason about a composite number's factor structure (e.g.
  showing d*(n/d) contributes distinct factors to a product).
gotchas: >
  Use `n.minFac` (the smallest prime factor) as the witness, not an
  arbitrary divisor obtained from `Nat.exists_dvd_of_not_prime2` — a
  free-form attempt at this went down a dead end trying to prove the
  chosen witness `a` itself is prime via a nested case split on whether
  `a` is prime, got stuck, and gave up with a `sorry` (visible directly in
  a captured live failure). `n.minFac` is prime by construction
  (`Nat.minFac_prime`), which sidesteps that entire dead end. The
  distinctness argument is then just: if `n/d = d` then `n = d^2` with `d`
  prime, contradicting the "not a prime square" hypothesis directly.
---

```lean
import Mathlib.Data.Nat.Prime.Basic
import Mathlib.Tactic.Ring

theorem composite_not_prime_sq_has_distinct_divisor
    (n : ℕ) (hcomp : ¬ n.Prime ∧ n ≠ 1 ∧ n ≠ 0)
    (hnotsq : ∀ p : ℕ, p.Prime → n ≠ p ^ 2) :
    ∃ d : ℕ, 1 < d ∧ d < n ∧ d ≠ n / d ∧ d ∣ n := by
  obtain ⟨hnp, hn1, hn0⟩ := hcomp
  set p := n.minFac with hp_def
  have hp_prime : p.Prime := Nat.minFac_prime hn1
  have hp_dvd : p ∣ n := Nat.minFac_dvd n
  have hp_lt : p < n := by
    have hp_le : p ≤ n := Nat.le_of_dvd (Nat.pos_of_ne_zero hn0) hp_dvd
    rcases lt_or_eq_of_le hp_le with h | h
    · exact h
    · exact absurd (h ▸ hp_prime) hnp
  refine ⟨p, hp_prime.one_lt, hp_lt, ?_, hp_dvd⟩
  intro heq
  obtain ⟨k, hk⟩ := hp_dvd
  have hk_eq : n / p = k := by rw [hk]; exact Nat.mul_div_cancel_left k hp_prime.pos
  rw [hk_eq] at heq
  apply hnotsq p hp_prime
  rw [hk, ← heq]; ring
```
