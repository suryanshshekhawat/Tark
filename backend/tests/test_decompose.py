"""Regression tests for decompose.py's resilience to real-world-shaped
failures — a truncated response, individually malformed steps within an
otherwise-good batch, a double-encoded `steps` payload, and empty-steps
sampling variance. All but the double-encoding case were found live against
a real multi-theorem academic LaTeX input, not written speculatively.

Mocks `invoke_llm` (not the underlying ChatAnthropic client) since that's
the single seam `decompose()` calls through — fake responses mimic
langchain-anthropic's AIMessage shape (`.tool_calls`, `.response_metadata`,
`.content`) rather than the raw Anthropic SDK's block objects.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

from app.pipeline.decompose import DecompositionError, decompose


@dataclass
class _FakeResponse:
    tool_calls: list = field(default_factory=list)
    content: list = field(default_factory=list)
    response_metadata: dict = field(default_factory=lambda: {"stop_reason": "tool_use"})


def _tool_call(args: dict, name: str = "record_decomposition") -> dict:
    return {"name": name, "args": args, "id": "toolu_fake", "type": "tool_call"}


async def _run(responses):
    responses = responses if isinstance(responses, list) else [responses]
    with patch("app.pipeline.decompose.invoke_llm", AsyncMock(side_effect=responses)):
        return await decompose("some normalized latex source")


@pytest.mark.asyncio
async def test_truncated_response_raises_specific_error():
    response = _FakeResponse(response_metadata={"stop_reason": "max_tokens"})
    with pytest.raises(DecompositionError, match="too long to decompose"):
        await _run(response)


@pytest.mark.asyncio
async def test_missing_anchor_text_degrades_gracefully():
    steps_input = {
        "steps": [
            {
                "id": "S1",
                "statement": "n is even",
                "depends_on": [],
                "classification": "premise",
                "note": "given",
                # anchor_text deliberately omitted
            }
        ]
    }
    result = await _run(_FakeResponse(tool_calls=[_tool_call(steps_input)]))
    assert len(result) == 1
    assert result[0].anchor_text == ""


@pytest.mark.asyncio
async def test_invalid_classification_degrades_to_unformalizable():
    steps_input = {
        "steps": [
            {
                "id": "S1",
                "statement": "something",
                "depends_on": [],
                "classification": "not_a_real_classification",
                "anchor_text": "something",
            }
        ]
    }
    result = await _run(_FakeResponse(tool_calls=[_tool_call(steps_input)]))
    assert len(result) == 1
    assert result[0].classification.value == "unformalizable"


@pytest.mark.asyncio
async def test_one_bad_step_does_not_drop_the_rest():
    steps_input = {
        "steps": [
            {"id": "S1", "statement": "good step", "depends_on": [], "classification": "premise", "anchor_text": "good"},
            {
                # no "id" at all -> unparseable, must be dropped, not fatal
                "statement": "orphan step",
                "depends_on": [],
                "classification": "premise",
                "anchor_text": "orphan",
            },
            {"id": "S3", "statement": "another good step", "depends_on": [], "classification": "premise", "anchor_text": "another"},
        ]
    }
    result = await _run(_FakeResponse(tool_calls=[_tool_call(steps_input)]))
    assert [s.id for s in result] == ["S1", "S3"]


@pytest.mark.asyncio
async def test_all_steps_unparseable_raises():
    # decompose() retries once on any non-"too long"-shaped DecompositionError
    # (sampling variance, not a deterministic function of input size) — two
    # identical bad responses needed to exhaust that retry.
    steps_input = {"steps": [{"statement": "no id here"}]}
    response = _FakeResponse(tool_calls=[_tool_call(steps_input)])
    with pytest.raises(DecompositionError, match="none could be parsed"):
        await _run([response, response])


@pytest.mark.asyncio
async def test_empty_steps_list_raises():
    response = _FakeResponse(tool_calls=[_tool_call({"steps": []})])
    with pytest.raises(DecompositionError, match="returned no steps"):
        await _run([response, response])


@pytest.mark.asyncio
async def test_double_encoded_json_steps_recovered():
    """On long inputs, forced tool-use occasionally emits `steps` as a JSON
    string instead of a true array — a real, complete decomposition dodging
    the schema's typing, not a missing one. Must be recovered, not treated
    as empty."""
    inner_steps = [
        {"id": "S1", "statement": "n is even", "depends_on": [], "classification": "premise", "anchor_text": "n is even"}
    ]
    steps_input = {"steps": json.dumps(inner_steps)}
    result = await _run(_FakeResponse(tool_calls=[_tool_call(steps_input)]))
    assert len(result) == 1
    assert result[0].id == "S1"


@pytest.mark.asyncio
async def test_empty_steps_retries_and_succeeds_on_second_attempt():
    """Empty-steps has been observed to be sampling variance, not a
    deterministic function of the input — a bare retry on the identical
    input has succeeded. Confirm decompose() actually retries rather than
    failing on the first empty response."""
    empty = _FakeResponse(tool_calls=[_tool_call({"steps": []})])
    good_steps = {
        "steps": [
            {"id": "S1", "statement": "n is even", "depends_on": [], "classification": "premise", "anchor_text": "n is even"}
        ]
    }
    good = _FakeResponse(tool_calls=[_tool_call(good_steps)])

    result = await _run([empty, good])
    assert len(result) == 1
    assert result[0].id == "S1"


@pytest.mark.asyncio
async def test_empty_steps_exhausts_retries_then_raises():
    empty = _FakeResponse(tool_calls=[_tool_call({"steps": []})])
    with pytest.raises(DecompositionError, match="returned no steps"):
        await _run([empty, empty])
