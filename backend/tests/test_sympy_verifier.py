from app.models.schema import Verdict, VerifierName
from app.verifiers.sympy_verifier import SympyVerifier


def test_true_claim_verifies():
    res = SympyVerifier().check("result = __import__('sympy').isprime(1000003)")
    assert res.verdict == Verdict.VERIFIED
    assert res.verifier == VerifierName.SYMPY


def test_false_claim_refutes():
    res = SympyVerifier().check("result = __import__('math').gcd(48, 18) == 5")
    assert res.verdict == Verdict.REFUTED


def test_snippet_without_result_is_unverified():
    res = SympyVerifier().check("x = 1 + 1")
    assert res.verdict == Verdict.UNVERIFIED


def test_snippet_that_raises_is_unverified():
    res = SympyVerifier().check("result = 1 / 0")
    assert res.verdict == Verdict.UNVERIFIED


def test_snippet_cannot_read_filesystem():
    res = SympyVerifier().check("result = bool(open('C:/Windows/win.ini'))")
    assert res.verdict == Verdict.UNVERIFIED
    assert "NameError" in res.evidence.raw_output or "not defined" in res.evidence.raw_output
