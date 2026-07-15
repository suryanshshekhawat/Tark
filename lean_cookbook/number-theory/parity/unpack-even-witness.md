---
title: Unpack Even n into a witness n = 2 * k
tags: [parity, even]
verified: 2026-07-14
when_to_use: >
  You have (or can derive) `Even n` as a hypothesis and the step needs an
  explicit witness k with n = 2 * k to continue an algebraic argument.
---

```lean
import Mathlib.Algebra.Ring.Parity

theorem ex2 (n : ℕ) (hn : Even n) : ∃ k : ℕ, n = 2 * k := by
  obtain ⟨k, hk⟩ := hn
  exact ⟨k, by omega⟩
```
