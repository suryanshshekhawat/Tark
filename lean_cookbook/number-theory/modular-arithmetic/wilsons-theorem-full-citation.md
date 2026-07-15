---
title: Wilson's theorem — whole statement is already in Mathlib
tags: [wilson, factorials, primes, famous-theorem]
verified: 2026-07-14
when_to_use: >
  ONLY when the step's entire claim, verbatim, IS the iff statement "(n-1)!
  is congruent to -1 modulo n if and only if n is prime" (or one full
  direction of it stated as a complete claim on its own, e.g. as the
  induction/case conclusion of a proof already structured around proving
  exactly that direction). Do NOT use this for an intermediate step that
  merely mentions factorials, primes, or "-1 mod n" while proving something
  narrower — e.g. a step about pairing elements into inverse pairs, or a
  step concluding a partial product ≡ -1 (mod n) as one piece of a larger
  argument, is NOT this pattern even though it looks Wilson-shaped. A wrong
  match here silently discards the step's actual (narrower, more provable)
  claim in favor of a much stronger one that the step was never asked to
  establish standalone — confirmed live: this pattern was misapplied to two
  sub-steps of a Wilson's-theorem decomposition that were not the full
  theorem, and both timed out as a result (the correct, narrower claims for
  those steps would very likely have succeeded).
gotchas: >
  Pulls in `Mathlib.FieldTheory.Finite.Basic`, a heavier import than most
  patterns in this cookbook (the underlying proof goes via `(ZMod p)ˣ`) —
  measured at 58s warm and up to 3m10s under memory pressure, well past a
  default ~45s budget; needs a longer timeout allowance than most patterns
  here. The statement is phrased with the factorial cast into `ZMod n` and
  equated to `-1` (`((n-1)! : ZMod n) = -1`), which is the standard Mathlib
  idiom for "≡ -1 (mod n)" — match that shape rather than inventing a
  `Nat.ModEq` formulation.
---

```lean
import Mathlib.NumberTheory.Wilson

theorem wilson_theorem_ex (n : ℕ) (hn : n ≠ 1) :
    Nat.Prime n ↔ ((Nat.factorial (n - 1) : ZMod n) = -1) :=
  Nat.prime_iff_fac_equiv_neg_one hn
```
