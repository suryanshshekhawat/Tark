from app.models.schema import Verdict, VerifierName
from app.verifiers.lean_verifier import LeanVerifier

# `import Mathlib` pulls in the *entire* library (50s+ to elaborate even
# with the prebuilt cache, since every subprocess is a cold interpreter) —
# far beyond the 20-30s hard timeout budget in CONSTRUCTION_PLAN.md §8.2.
# Real formalization prompts must ask Claude for targeted imports.
VALID_THEOREM = """
import Mathlib.Data.Nat.GCD.Basic

theorem gcd_48_18 : Nat.gcd 48 18 = 6 := by decide
"""

FALSE_THEOREM = """
import Mathlib.Data.Nat.GCD.Basic

theorem gcd_48_18_wrong : Nat.gcd 48 18 = 5 := by decide
"""

SORRY_THEOREM = """
import Mathlib.Data.Nat.GCD.Basic

theorem incomplete : Nat.gcd 48 18 = 6 := by sorry
"""


def test_valid_mathlib_theorem_verifies():
    res = LeanVerifier().check(VALID_THEOREM, timeout=25)
    assert res.verdict == Verdict.VERIFIED
    assert res.verifier == VerifierName.LEAN
    assert res.evidence.exit_code == 0


def test_false_theorem_is_rejected():
    res = LeanVerifier().check(FALSE_THEOREM, timeout=25)
    assert res.verdict != Verdict.VERIFIED
    assert res.evidence.exit_code != 0


def test_sorry_is_unverified_not_verified():
    res = LeanVerifier().check(SORRY_THEOREM, timeout=25)
    assert res.verdict == Verdict.UNVERIFIED
