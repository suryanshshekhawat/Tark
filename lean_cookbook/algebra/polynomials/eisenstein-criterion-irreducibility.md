---
title: Applying Eisenstein's criterion to prove a polynomial is irreducible
tags: [polynomials, irreducibility, eisenstein, primes]
verified: 2026-07-17
when_to_use: >
  The step invokes Eisenstein's criterion directly: a prime p, a polynomial
  f with leading coefficient not divisible by p, every other coefficient
  divisible by p, and constant term not divisible by p^2, therefore f is
  irreducible over Q (or more generally over Frac(R) for R a domain).
  Matches steps that either state the criterion's hypotheses explicitly
  ("every coefficient except the leading one is divisible by p...") or just
  assert "by Eisenstein's criterion, f is irreducible" once those
  hypotheses were established in earlier steps. This worked example proves
  X^2 + 2 irreducible over Z with p = 2 — adapt the coefficient-membership
  proofs (the `interval_cases n` block) to the actual polynomial's degree
  and coefficients; the ideal-primality and constant-term-not-in-P^2 bullets
  carry over almost unchanged for any prime p.
gotchas: >
  irreducible_of_eisenstein_criterion takes hypotheses in this exact order:
  P.IsPrime, leadingCoeff ∉ P, (∀ n, n < degree f -> coeff n ∈ P), 0 <
  degree f, coeff 0 ∉ P^2, f.IsPrimitive — get the `apply` bullet order
  wrong and goals silently mismatch instead of erroring cleanly. `P^2` means
  `P * P` here (Ideal power), not "divisible by p^2" directly — rewrite
  with `pow_two` then `Ideal.span_singleton_mul_span_singleton` to turn it
  into a plain `Ideal.mem_span_singleton` divisibility goal before
  `norm_num`/`decide` can close it. `Nat.Prime 2`-style goals need the
  `Mathlib.Tactic.NormNum.Prime` import or `norm_num` alone won't close
  them; `Prime (2 : Z)` (as opposed to `Nat.Prime`) needs a detour through
  `Int.prime_iff_natAbs_prime`. `interval_cases n` needs `n` bounded as a
  plain Nat (`exact_mod_cast` the WithBot-Nat degree bound down to Nat
  first) and needs `Mathlib.Tactic.IntervalCases` imported. `monicity!` and
  `compute_degree!` (from `Mathlib.Tactic.ComputeDegree`) make the
  degree/leadingCoeff/Monic side-goals for X^n + C a-shaped polynomials
  nearly automatic — reach for them before hand-unfolding `coeff`/`degree`.
---

```lean
import Mathlib.RingTheory.Polynomial.Eisenstein.Criterion
import Mathlib.RingTheory.Int.Basic
import Mathlib.Tactic.ComputeDegree
import Mathlib.Tactic.NormNum.Prime
import Mathlib.Tactic.IntervalCases

open Polynomial

example : Irreducible (X ^ 2 + C (2 : ℤ)) := by
  have hmonic : (X ^ 2 + C (2 : ℤ)).Monic := by monicity!
  have hdeg : (X ^ 2 + C (2 : ℤ)).degree = 2 := by compute_degree!
  apply irreducible_of_eisenstein_criterion (P := Ideal.span {(2 : ℤ)})
  · exact (Ideal.span_singleton_prime (by norm_num)).mpr
      (Int.prime_iff_natAbs_prime.mpr (by norm_num))
  · rw [hmonic.leadingCoeff, Ideal.mem_span_singleton]
    norm_num
  · intro n hn
    rw [hdeg] at hn
    have hn' : n < 2 := by exact_mod_cast hn
    interval_cases n <;> simp
  · rw [hdeg]; decide
  · rw [pow_two, Ideal.span_singleton_mul_span_singleton, Ideal.mem_span_singleton]
    norm_num
  · exact hmonic.isPrimitive
```
