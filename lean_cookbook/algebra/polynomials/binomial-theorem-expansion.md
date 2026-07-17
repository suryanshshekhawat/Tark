---
title: Binomial theorem expansion (x+1)^n = sum of C(n,k) x^k
tags: [binomial-coefficients, polynomials, commutative-ring]
verified: 2026-07-17
when_to_use: >
  The step invokes "the binomial theorem" to expand (x+y)^n (most often
  (x+1)^n specifically, e.g. as a substitution step before applying
  Eisenstein's criterion to a shifted polynomial) into a finite sum of
  binomial-coefficient-weighted terms. Works over any CommSemiring — Z, Q,
  and R[X] (polynomials) all qualify, so this covers both a plain numeric/
  variable expansion and expanding a *polynomial* raised to a power (e.g.
  Phi_p(x+1)'s numerator, where x itself is `Polynomial.X`).
gotchas: >
  The general theorem is named `add_pow` at the *root* namespace, in
  `Mathlib.Data.Nat.Choose.Sum` — not the `Mathlib.Algebra.BigOperators.*`
  files an LLM's first instinct usually reaches for (those don't transitively
  pull it in, causing a bare "unknown identifier `add_pow`" even though the
  theorem exists and compiles fine once the right file is imported).
  There's also a same-named `Commute.add_pow` (noncommutative version, needs
  an explicit `Commute x y` proof) in the *same* file — don't reach for that
  one for a plain commutative ring/polynomial ring goal, it just adds an
  unneeded hypothesis. The coefficient lands at the *end* of each summand
  (`x ^ m * y ^ (n - m) * n.choose m`, coefficient last, not first) and as a
  bare `n.choose m : ℕ` needing an implicit cast — `mul_comm` (and a cast, if
  the target states the coefficient first as `(Nat.choose n m : R) * x ^ m`)
  after `rw [add_pow]` reconciles the shapes.
---

```lean
import Mathlib.Data.Nat.Choose.Sum

theorem ex_binom (x : ℤ) (p : ℕ) :
    (x + 1) ^ p = ∑ k ∈ Finset.range (p + 1), (Nat.choose p k : ℤ) * x ^ k := by
  rw [add_pow]
  apply Finset.sum_congr rfl
  intro k hk
  rw [one_pow, mul_one, mul_comm]
```
