-- Precompiled prelude of the Mathlib imports that recur most often across
-- proof steps (measured directly from tark.timing logs on this branch — see
-- CLAUDE.md/CONSTRUCTION_PLAN.md for the "measure, don't assume" convention).
-- This file itself compiles to .olean once via `lake build`; the point of
-- benchmark-testing `import Tark.Prelude` against the current targeted-import
-- approach is to see whether one broader-but-precompiled import is faster
-- than several small ones recompiled fresh per subprocess. Only adopt in
-- formalize.py's prompts if the measured check time is not meaningfully
-- slower than today's targeted imports.
import Mathlib.Algebra.Ring.Parity
import Mathlib.Algebra.Group.Even
import Mathlib.Algebra.Group.Nat.Even
import Mathlib.Algebra.Ring.Basic
import Mathlib.Algebra.Ring.Rat
import Mathlib.Data.Nat.GCD.Basic
import Mathlib.Data.Nat.Prime.Basic
import Mathlib.Data.Int.GCD
import Mathlib.Data.Int.Basic
import Mathlib.Algebra.Ring.Int.Parity
import Mathlib.Data.Rat.Defs
import Mathlib.Data.Real.Basic
import Mathlib.Analysis.Real.Sqrt
import Mathlib.NumberTheory.Real.Irrational
import Mathlib.Tactic.Ring
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.NormNum
-- `omega` itself is a core Lean tactic (no Mathlib import needed at all);
-- `Mathlib.Tactic.Omega` does not exist in this Mathlib version.
