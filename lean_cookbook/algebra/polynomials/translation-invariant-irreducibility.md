---
title: A polynomial is irreducible iff its shift f(x+c) is irreducible
tags: [polynomials, irreducibility, substitution]
verified: 2026-07-17
when_to_use: >
  The step argues "f(x) factors over Q iff f(x+c) does" (or "...iff f(x-c)
  does") to transfer irreducibility across a shift of variable — the
  standard trick of substituting x -> x+1 (or any constant shift) before
  applying Eisenstein's criterion, then transferring the conclusion back to
  the original polynomial. The shift is invertible (its own inverse is the
  opposite shift), so this is always an iff, never just one direction.
  Distinct from the general substitution-and-rearrangement pattern — this is
  specifically about the *irreducibility* of a polynomial being preserved by
  a degree-1 substitution, not just an algebraic rewrite.
gotchas: >
  Polynomial.taylor r f is defeq to f.comp (X + C r) (taylor_apply gives the
  equation, but rw needs it in the direction that matches the goal exactly —
  rewrite f.comp (X + C r) to taylor r f with `← taylor_apply`, not the
  other way, before the MulEquiv.irreducible_iff step can see it as an
  `Equiv` application). taylorEquiv bundles this as an AlgEquiv, and its
  coercion to a plain function needs `coe_taylorEquiv` to line up with
  `taylor r` syntactically — `rw [← taylor_apply, ← coe_taylorEquiv] at h`
  is the reliable order, not `simp` (which sometimes normalizes past the
  form `MulEquiv.irreducible_iff` needs to unify against). Needs
  `.toMulEquiv` to hand the AlgEquiv to `MulEquiv.irreducible_iff`, which
  only knows about the multiplicative structure, not the algebra structure.
---

```lean
import Mathlib.Algebra.Polynomial.Taylor
import Mathlib.Algebra.Group.Irreducible.Lemmas

open Polynomial

example (f : ℚ[X]) (h : Irreducible (f.comp (X + C 1))) : Irreducible f := by
  rw [← taylor_apply, ← coe_taylorEquiv] at h
  exact (MulEquiv.irreducible_iff (taylorEquiv (1 : ℚ)).toMulEquiv).mp h
```
