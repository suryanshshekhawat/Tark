---
title: A specific number divides a factorial because it's one of the factors
tags: [factorials, divisibility]
verified: 2026-07-14
when_to_use: >
  The step claims p divides (n-1)! (or n!) because p is one of the numbers
  being multiplied together, i.e. 0 < p <= n-1.
gotchas: >
  Use `Nat.factorial n`, not the `!` postfix notation — `!` is `scoped` to
  the `Nat` namespace and fails to parse without `open Nat`, which these
  single-theorem files never have.
---

```lean
import Mathlib.Data.Nat.Factorial.Basic

theorem ex7 (n p : ℕ) (hp : 0 < p) (h : p ≤ n - 1) : p ∣ Nat.factorial (n - 1) :=
  Nat.dvd_factorial hp h
```
