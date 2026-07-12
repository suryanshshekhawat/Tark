from app.pipeline.span_matching import find_span


def test_exact_match():
    source = "Let $p$ be prime. Then $p^2 > 1$ follows."
    span = find_span(source, "Then $p^2 > 1$ follows")
    assert source[span.start:span.end] == "Then $p^2 > 1$ follows"


def test_no_anchor_returns_empty_span():
    span = find_span("anything", None)
    assert span.start == span.end == 0


def test_fuzzy_fallback_on_whitespace_drift():
    source = "Since gcd(p, q) = 1\nand p^2 = 2q^2, p is even."
    # Claude quoted it with a space instead of the source's newline.
    span = find_span(source, "Since gcd(p, q) = 1 and p^2 = 2q^2, p is even.")
    assert span.start < span.end


def test_unlocatable_anchor_falls_back_to_zero_span():
    source = "Completely unrelated text with no overlap whatsoever."
    span = find_span(source, "xyz123 not present anywhere qwerty")
    assert span.start == span.end == 0
