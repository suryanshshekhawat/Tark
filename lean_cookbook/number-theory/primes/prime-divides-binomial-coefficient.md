---
title: A prime p divides the binomial coefficient C(p, k) for 0 < k < p
tags: [primes, binomial-coefficients, combinatorics]
verified: 2026-07-17
when_to_use: >
  The step claims p | binom(p, k) for a prime p and 1 <= k <= p-1 — the
  standard fact that every "interior" binomial coefficient of a prime row of
  Pascal's triangle is divisible by that prime (often justified informally by
  "the numerator p! has exactly one factor of p, which no factor in
  k!(p-k)! can cancel"). Recurring in Eisenstein-criterion arguments for
  cyclotomic/binomial-shaped polynomials (e.g. Phi_p(x+1)'s coefficients) and
  in combinatorial mod-p proofs. Do not confuse with the general (non-prime)
  case, which has no such clean divisibility.
gotchas: >
  The lemma is stated for Nat.choose (natural-number coefficients), not a
  Polynomial.coeff — if the step is really about a polynomial's coefficient
  equal to a specific binomial coefficient, first identify the coefficient
  with Nat.choose p k, then apply this. hkp needs strict k < p, not k <= p
  (k = p gives C(p,p) = 1, not divisible by p).
---

```lean
import Mathlib.Data.Nat.Choose.Dvd

theorem ex10 (p k : ℕ) (hp : p.Prime) (hk : k ≠ 0) (hkp : k < p) : p ∣ Nat.choose p k :=
  hp.dvd_choose_self hk hkp
```
