---
title: A square is even iff its base is even
tags: [parity, even, squares]
verified: 2026-07-14
when_to_use: >
  The step claims that n is even, and the evidence available is an equation
  of the shape n^2 = 2 * (something) — i.e. n^2 is even, and you need to
  conclude n itself is even.
---

```lean
import Mathlib.Algebra.Ring.Parity

theorem ex1 (n k : ℕ) (h : n ^ 2 = 2 * k ^ 2) : Even n := by
  have h2 : Even (n ^ 2) := ⟨k ^ 2, by omega⟩
  exact (Nat.even_pow.mp h2).1
```
