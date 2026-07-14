from app.models.schema import Classification, OverallStatus, SourceSpan, Step, Verdict
from app.pipeline.report import build_report


def _step(id_: str, verdict: Verdict, classification: Classification = Classification.LEAN_CANDIDATE) -> Step:
    return Step(
        id=id_,
        statement="stmt",
        source_span=SourceSpan(start=0, end=0),
        classification=classification,
        verdict=verdict,
    )


def test_assumed_steps_dont_block_fully_verified():
    steps = [
        _step("S1", Verdict.ASSUMED, Classification.PREMISE),
        _step("S2", Verdict.VERIFIED),
        _step("S3", Verdict.VERIFIED),
    ]
    report = build_report("source", steps)
    assert report.overall_status == OverallStatus.FULLY_VERIFIED
    assert report.steps_verified == 2
    assert report.steps_assumed == 1
    assert report.steps_total == 3


def test_all_assumed_is_not_fully_verified():
    steps = [_step("S1", Verdict.ASSUMED, Classification.PREMISE)]
    report = build_report("source", steps)
    assert report.overall_status != OverallStatus.FULLY_VERIFIED


def test_refuted_wins_over_assumed_and_verified():
    steps = [
        _step("S1", Verdict.ASSUMED, Classification.PREMISE),
        _step("S2", Verdict.VERIFIED),
        _step("S3", Verdict.REFUTED),
    ]
    report = build_report("source", steps)
    assert report.overall_status == OverallStatus.REFUTED_SOMEWHERE


def test_unverified_step_gives_partially_verified():
    steps = [
        _step("S1", Verdict.ASSUMED, Classification.PREMISE),
        _step("S2", Verdict.VERIFIED),
        _step("S3", Verdict.UNVERIFIED),
    ]
    report = build_report("source", steps)
    assert report.overall_status == OverallStatus.PARTIALLY_VERIFIED
