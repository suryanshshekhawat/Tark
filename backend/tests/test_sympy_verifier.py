from app.models.schema import Verdict, VerifierName
from app.verifiers.sympy_verifier import SympyVerifier


def test_true_claim_verifies():
    res = SympyVerifier().check("result = sympy.isprime(1000003)")
    assert res.verdict == Verdict.VERIFIED
    assert res.verifier == VerifierName.SYMPY


def test_false_claim_refutes():
    res = SympyVerifier().check("result = math.gcd(48, 18) == 5")
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


def test_snippet_cannot_import_arbitrary_modules():
    res = SympyVerifier().check("import os\nresult = True")
    assert res.verdict == Verdict.UNVERIFIED
    assert "ImportError" in res.evidence.raw_output or "__import__" in res.evidence.raw_output


def test_snippet_cannot_escape_via_class_introspection():
    """The classic RestrictedPython-defeating trick for a naive restricted-
    builtins sandbox: walk the live object graph via dunder attributes to
    reach subprocess.Popen without ever calling `import`. Must be rejected
    at compile time, not merely fail to find something dangerous."""
    res = SympyVerifier().check(
        "result = 'Popen' in [c.__name__ for c in ().__class__.__base__.__subclasses__()]"
    )
    assert res.verdict == Verdict.UNVERIFIED
    assert "invalid attribute name" in res.evidence.raw_output or "SyntaxError" in res.evidence.raw_output


def test_snippet_cannot_getattr_dunder():
    res = SympyVerifier().check("result = getattr(1, '__class__') is not None")
    assert res.verdict == Verdict.UNVERIFIED


def test_tuple_unpack_assignment_works():
    """Idiomatic sympy usage (`n, k = sympy.symbols(...)`) — RestrictedPython
    compiles unpacking assignment to a call to a `_unpack_sequence_` guard;
    without it every such snippet fails with a misleading bare NameError."""
    res = SympyVerifier().check(
        "n, k = sympy.symbols('n k', integer=True)\n"
        "lhs = (2 * k) ** 2\n"
        "rhs = 2 * (2 * k ** 2)\n"
        "result = sympy.simplify(lhs - rhs) == 0"
    )
    assert res.verdict == Verdict.VERIFIED


def test_for_loop_unpack_works():
    res = SympyVerifier().check(
        "total = 0\n"
        "for base, exp in {2: 1, 3: 1}.items():\n"
        "    total += base * exp\n"
        "result = total == 5"
    )
    assert res.verdict == Verdict.VERIFIED
