---
title: Squaring a Real.sqrt equation
tags: [irrationality, real-analysis, sqrt]
verified: 2026-07-14
when_to_use: >
  The step squares both sides of an equation involving Real.sqrt to clear
  the square root — the classic middle step of an infinite-descent
  irrationality proof (e.g. p = q * sqrt 2 implies p^2 = 2 * q^2).
gotchas: >
  `import Mathlib.Analysis.Real.Sqrt` alone costs ~25s to import (measured
  by timing it against a trivial goal, isolating import cost from proof
  cost) — that is a fixed cost of the import, not a sign the proof itself
  is hard. Budget for it (see the checker's timeout), don't avoid the
  statement because of it. Prefer the multiplicative form
  (`p = q * sqrt 2`) over a division form (`p / q = sqrt 2`) where the
  source allows it — it avoids needing `field_simp` on top of the already
  -heavy import.
---

```lean
import Mathlib.Analysis.Real.Sqrt

theorem ex5 (p q : ℤ) (h : (p:ℝ) = (q:ℝ) * Real.sqrt 2) :
    (p:ℝ) ^ 2 = 2 * (q:ℝ) ^ 2 := by
  have hsq : Real.sqrt 2 ^ 2 = 2 := Real.sq_sqrt (by norm_num)
  rw [h, mul_pow, hsq]
  ring
```
