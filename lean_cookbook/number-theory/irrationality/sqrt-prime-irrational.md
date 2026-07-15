---
title: sqrt(2) (or any prime) is irrational
tags: [irrationality, real-analysis, sqrt, primes]
verified: 2026-07-14
when_to_use: >
  The step's entire claim IS "sqrt(p) is irrational" for a specific prime p
  — don't overcomplicate this with a manual contradiction argument, it's a
  one-line citation.
gotchas: >
  `Irrational` lives at `Mathlib.NumberTheory.Real.Irrational`, not
  `Mathlib.Data.Real.Irrational` (renamed). `Nat.Prime.irrational_sqrt`
  takes the primality proof directly (`Nat.prime_two`, or `by norm_num` for
  other primes) — no need to unfold `Nat.Prime` into its components first.
---

```lean
import Mathlib.Analysis.Real.Sqrt
import Mathlib.NumberTheory.Real.Irrational

theorem ex6 : Irrational (Real.sqrt 2) :=
  Nat.prime_two.irrational_sqrt
```
