from app.models.schema import ErrorType
from app.validation.latex_validator import LatexValidator


def test_empty_input_hard_fails():
    result = LatexValidator().validate("")
    assert not result.ok
    assert result.error.error_type == ErrorType.EMPTY_INPUT


def test_no_math_content_hard_fails():
    result = LatexValidator().validate("This is just prose with no math in it at all.")
    assert not result.ok
    assert result.error.error_type == ErrorType.NO_MATH_CONTENT


def test_unbalanced_braces_hard_fails_with_location():
    result = LatexValidator().validate("Let $x = 1$ and $y = 2}$.")
    assert not result.ok
    assert result.error.error_type == ErrorType.UNBALANCED_ENVIRONMENT
    assert result.error.location is not None


def test_unbalanced_environment_hard_fails():
    latex = r"\begin{align} x = 1 \end{equation}"
    result = LatexValidator().validate(latex)
    assert not result.ok
    assert result.error.error_type == ErrorType.UNBALANCED_ENVIRONMENT


def test_unmatched_dollar_soft_repairs():
    result = LatexValidator().validate("Let $x = 1 and $y = 2$.")
    assert result.ok
    assert len(result.auto_repairs) == 1
    assert result.normalized_source.endswith("$")


def test_strips_preamble_and_document_wrapper():
    latex = (
        r"\documentclass{article}" "\n"
        r"\usepackage{amsmath}" "\n"
        r"\begin{document}" "\n"
        r"Claim: $\gcd(48, 18) = 6$." "\n"
        r"\end{document}"
    )
    result = LatexValidator().validate(latex)
    assert result.ok
    assert "documentclass" not in result.normalized_source
    assert r"\gcd(48, 18) = 6" in result.normalized_source


def test_well_formed_proof_passes_clean():
    latex = r"Since $\gcd(p, q) = 1$ and $p^2 = 2q^2$, it follows that $p$ is even."
    result = LatexValidator().validate(latex)
    assert result.ok
    assert result.auto_repairs == []
    assert result.normalized_source == latex
