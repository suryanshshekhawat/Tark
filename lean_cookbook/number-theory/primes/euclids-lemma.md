---
title: Euclid's lemma — a prime dividing a product divides one factor
tags: [primes, divisibility]
verified: 2026-07-14
when_to_use: >
  The step invokes "Euclid's lemma" or equivalent reasoning: from p prime
  and p | a * b, concludes p | a or p | b. Extremely common in factoring
  arguments and case-split proofs.
---

```lean
import Mathlib.Data.Nat.Prime.Defs

theorem ex9 (p a b : ℕ) (hp : Nat.Prime p) (h : p ∣ a * b) : p ∣ a ∨ p ∣ b :=
  hp.dvd_mul.mp h
```
