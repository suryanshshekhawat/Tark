from app.models.schema import Classification
from app.pipeline.decompose import _parse_raw_step

# Regression coverage for a real failure caught via the benchmark harness:
# Claude omitted `anchor_text` on one unformalizable step despite it being
# `required` in the tool schema, and the old code raised DecompositionError
# for the *entire* decomposition over one step's missing field — killing
# every other step's results too (CONSTRUCTION_PLAN.md §4a.5 explicitly
# forbids this: "a failure at step S4 should not prevent S1-S3's results
# from being shown").


def test_missing_anchor_text_degrades_gracefully():
    raw = {
        "id": "S2",
        "statement": "Case split: consider two cases based on whether n is even or odd.",
        "depends_on": [],
        "classification": "unformalizable",
        "unformalizable_reason": "Proof-structuring statement, not a checkable claim.",
    }
    step = _parse_raw_step(raw, 0)
    assert step is not None
    assert step.id == "S2"
    assert step.anchor_text is None
    assert step.classification == Classification.UNFORMALIZABLE


def test_missing_classification_downgrades_to_unformalizable():
    raw = {"id": "S3", "statement": "p^2 = 2q^2", "depends_on": [], "anchor_text": "p^2 = 2q^2"}
    step = _parse_raw_step(raw, 0)
    assert step is not None
    assert step.classification == Classification.UNFORMALIZABLE
    assert step.unformalizable_reason is not None


def test_invalid_classification_value_downgrades_to_unformalizable():
    raw = {
        "id": "S4",
        "statement": "some claim",
        "depends_on": [],
        "classification": "not_a_real_classification",
        "anchor_text": "some claim",
    }
    step = _parse_raw_step(raw, 0)
    assert step is not None
    assert step.classification == Classification.UNFORMALIZABLE


def test_missing_id_drops_step():
    raw = {"statement": "orphaned claim", "depends_on": [], "classification": "lean_candidate"}
    assert _parse_raw_step(raw, 0) is None


def test_missing_statement_drops_step():
    raw = {"id": "S5", "depends_on": [], "classification": "lean_candidate"}
    assert _parse_raw_step(raw, 0) is None


def test_well_formed_step_parses_normally():
    raw = {
        "id": "S1",
        "statement": "gcd(p, q) = 1",
        "depends_on": ["S0"],
        "classification": "lean_candidate",
        "anchor_text": "\\gcd(p, q) = 1",
    }
    step = _parse_raw_step(raw, 0)
    assert step is not None
    assert step.id == "S1"
    assert step.depends_on == ["S0"]
    assert step.classification == Classification.LEAN_CANDIDATE
    assert step.anchor_text == "\\gcd(p, q) = 1"
    assert step.unformalizable_reason is None
