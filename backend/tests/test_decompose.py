"""Regression tests for decompose.py's resilience to real-world-shaped
failures — a truncated response, and individually malformed steps within an
otherwise-good batch. Both were found live against a real multi-theorem
academic LaTeX input, not written speculatively.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

from app.pipeline.decompose import DecompositionError, decompose


@dataclass
class _FakeToolUseBlock:
    input: dict
    type: str = "tool_use"


@dataclass
class _FakeResponse:
    content: list
    stop_reason: str = "tool_use"


@dataclass
class _FakeMessages:
    response: _FakeResponse

    async def create(self, **kwargs):
        return self.response


@dataclass
class _FakeClient:
    messages: _FakeMessages = field(init=False)
    response: _FakeResponse

    def __post_init__(self):
        self.messages = _FakeMessages(self.response)


@dataclass
class _SequencedMessages:
    responses: list

    async def create(self, **kwargs):
        return self.responses.pop(0)


@dataclass
class _SequencedClient:
    responses: list
    messages: _SequencedMessages = field(init=False)

    def __post_init__(self):
        self.messages = _SequencedMessages(list(self.responses))


def _patched_client(response: _FakeResponse):
    return patch("app.pipeline.decompose.get_client", return_value=_FakeClient(response))


async def _run(response: _FakeResponse):
    with _patched_client(response):
        return await decompose("some normalized latex source")


@pytest.mark.asyncio
async def test_truncated_response_raises_specific_error():
    response = _FakeResponse(content=[_FakeToolUseBlock(input={})], stop_reason="max_tokens")
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
    response = _FakeResponse(content=[_FakeToolUseBlock(input=steps_input)])
    result = await _run(response)
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
    response = _FakeResponse(content=[_FakeToolUseBlock(input=steps_input)])
    result = await _run(response)
    assert len(result) == 1
    assert result[0].classification.value == "unformalizable"


@pytest.mark.asyncio
async def test_one_bad_step_does_not_drop_the_rest():
    steps_input = {
        "steps": [
            {
                "id": "S1",
                "statement": "good step",
                "depends_on": [],
                "classification": "premise",
                "anchor_text": "good",
            },
            {
                # no "id" at all -> unparseable, must be dropped, not fatal
                "statement": "orphan step",
                "depends_on": [],
                "classification": "premise",
                "anchor_text": "orphan",
            },
            {
                "id": "S3",
                "statement": "another good step",
                "depends_on": [],
                "classification": "premise",
                "anchor_text": "another",
            },
        ]
    }
    response = _FakeResponse(content=[_FakeToolUseBlock(input=steps_input)])
    result = await _run(response)
    assert [s.id for s in result] == ["S1", "S3"]


@pytest.mark.asyncio
async def test_all_steps_unparseable_raises():
    steps_input = {"steps": [{"statement": "no id here"}]}
    response = _FakeResponse(content=[_FakeToolUseBlock(input=steps_input)])
    with pytest.raises(DecompositionError, match="none could be parsed"):
        await _run(response)


@pytest.mark.asyncio
async def test_empty_steps_list_raises():
    response = _FakeResponse(content=[_FakeToolUseBlock(input={"steps": []})])
    with pytest.raises(DecompositionError, match="returned no steps"):
        await _run(response)


@pytest.mark.asyncio
async def test_empty_steps_retries_and_succeeds_on_second_attempt():
    """Empty-steps has been observed to be sampling variance, not a
    deterministic function of the input — a bare retry on the identical
    input has succeeded. Confirm decompose() actually retries rather than
    failing on the first empty response."""
    empty = _FakeResponse(content=[_FakeToolUseBlock(input={"steps": []})])
    good_steps = {
        "steps": [
            {
                "id": "S1",
                "statement": "n is even",
                "depends_on": [],
                "classification": "premise",
                "anchor_text": "n is even",
            }
        ]
    }
    good = _FakeResponse(content=[_FakeToolUseBlock(input=good_steps)])

    with patch(
        "app.pipeline.decompose.get_client",
        return_value=_SequencedClient([empty, good]),
    ):
        result = await decompose("some normalized latex source")
    assert len(result) == 1
    assert result[0].id == "S1"


@pytest.mark.asyncio
async def test_empty_steps_exhausts_retries_then_raises():
    empty = _FakeResponse(content=[_FakeToolUseBlock(input={"steps": []})])
    with patch(
        "app.pipeline.decompose.get_client",
        return_value=_SequencedClient([empty, empty]),
    ):
        with pytest.raises(DecompositionError, match="returned no steps"):
            await decompose("some normalized latex source")
