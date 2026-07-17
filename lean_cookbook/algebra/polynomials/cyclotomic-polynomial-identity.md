---
title: The p-th cyclotomic polynomial equals (X^p - 1)/(X - 1), for p prime
tags: [polynomials, cyclotomic, prime]
verified: 2026-07-17
when_to_use: >
  The step claims Phi_p(x) = 1 + x + x^2 + ... + x^(p-1), or equivalently
  Phi_p(x) * (x - 1) = x^p - 1, for a prime p — the standard closed form of
  the p-th cyclotomic polynomial as a geometric-series sum. Mathlib already
  defines Polynomial.cyclotomic and has both forms proved; don't reprove the
  geometric-sum identity by hand from scratch, cite these directly. Only
  applies for p *prime* — composite-index cyclotomic polynomials have a more
  involved closed form (see cyclotomic_prime_pow_eq_geom_sum's sibling
  lemmas in the same file if that case comes up).
gotchas: >
  cyclotomic_prime needs the primality instance as `[Fact p.Prime]`, not a
  bare `(hp : p.Prime)` argument — wrap it with `haveI : Fact p.Prime := ⟨hp⟩`
  first if the surrounding proof only carries the bare Prop. The
  X-1-multiplied form (cyclotomic_prime_mul_X_sub_one) takes the ordinary
  `[Fact (Nat.Prime p)]` instance argument the same way but is often more
  convenient than the sum form when the step is stated as a product/quotient
  identity rather than an explicit sum.
---

```lean
import Mathlib.RingTheory.Polynomial.Cyclotomic.Basic

open Polynomial

-- Phi_p(x) * (x - 1) = x^p - 1
example (p : ℕ) [hp : Fact p.Prime] : (cyclotomic p ℤ) * (X - 1) = X ^ p - 1 :=
  cyclotomic_prime_mul_X_sub_one ℤ p

-- Phi_p(x) = 1 + x + ... + x^(p-1), as an explicit sum
example (p : ℕ) [hp : Fact p.Prime] :
    cyclotomic p ℤ = ∑ i ∈ Finset.range p, X ^ i :=
  cyclotomic_prime ℤ p
```
