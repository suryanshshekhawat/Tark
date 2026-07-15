---
title: Two even numbers can't be coprime
tags: [gcd, coprimality, parity]
verified: 2026-07-14
when_to_use: >
  The step derives a contradiction from two numbers both being even while
  also being assumed/claimed coprime (gcd = 1) — a common move in
  infinite-descent style irrationality proofs.
gotchas: >
  Needs GCD.Basic AND Parity AND NormNum together — a step mixing concepts
  needs an import per concept, not just one.
---

```lean
import Mathlib.Data.Nat.GCD.Basic
import Mathlib.Algebra.Ring.Parity
import Mathlib.Tactic.NormNum

theorem ex3 (p q : ℕ) (hgcd : Nat.gcd p q = 1) (hp : Even p) (hq : Even q) : False := by
  have h2p : (2 : ℕ) ∣ p := hp.two_dvd
  have h2q : (2 : ℕ) ∣ q := hq.two_dvd
  have h2gcd : (2 : ℕ) ∣ Nat.gcd p q := Nat.dvd_gcd h2p h2q
  rw [hgcd] at h2gcd
  exact (by norm_num : ¬ (2 : ℕ) ∣ 1) h2gcd
```
