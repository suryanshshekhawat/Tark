from app.pipeline.counterexample import _run_probe_code

# This probe must never be able to produce a Verdict — only (found, description)
# for an advisory note. These tests cover the sandboxed runner in isolation
# (no API calls); the "never touches step.verdict" property is enforced at
# the call site in real_pipeline.py (only appended to claude_notes).


def test_counterexample_found():
    found, desc = _run_probe_code(
        "found = True\ncounterexample = 'n=4 fails since 4 is not prime'"
    )
    assert found is True
    assert "n=4" in desc


def test_no_counterexample_found():
    found, desc = _run_probe_code("found = False")
    assert found is False
    assert desc is None


def test_missing_found_variable_fails_closed():
    found, desc = _run_probe_code("x = 1 + 1")
    assert found is False
    assert desc is None


def test_snippet_that_raises_fails_closed():
    found, desc = _run_probe_code("result = 1 / 0")
    assert found is False


def test_non_bool_found_fails_closed():
    found, desc = _run_probe_code("found = 'yes'")
    assert found is False


def test_disallowed_import_fails_closed():
    found, desc = _run_probe_code("import os\nfound = True")
    assert found is False


def test_filesystem_access_fails_closed():
    found, desc = _run_probe_code("found = bool(open('/etc/hosts'))")
    assert found is False
