"""Claude call #1 — decomposition (CONSTRUCTION_PLAN.md §6.2).

Splits the normalized LaTeX proof into atomic steps. Claude is never asked
for character offsets (LLMs are bad at counting characters and drift is the
common case, not the exception — §10a) — only for an exact quoted
anchor_text, which span_matching.find_span locates in the backend.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..claude_client import cached_system_message, cached_tool, get_llm, invoke_llm
from ..models.schema import Classification

_logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the decomposition stage of Tark, a proof verification tool.

Core principle: you never assert correctness. Only Lean 4 (via Mathlib) compiling a \
formal statement, or a deterministic Python/SymPy check, can produce a VERIFIED verdict. \
Your only job here is to break the given LaTeX number-theory proof into a sequence of \
atomic, checkable steps — not to prove or verify anything yourself.

For each step, record:
- id: "S1", "S2", ... in the order the steps appear.
- statement: a precise statement of what this step claims (plain language plus math \
notation is fine).
- depends_on: ids of earlier steps this step logically relies on (may be empty).
- classification, exactly one of:
  - "lean_candidate": a precise mathematical claim that could plausibly be stated and \
proved as a Lean 4 theorem using Mathlib (divisibility, gcd, parity, modular arithmetic, \
irrationality, etc).
  - "computational": a concrete, decidable numerical claim best checked by direct \
computation (e.g. "gcd(48,18)=6", "1000003 is prime").
  - "unformalizable": a step that cannot be captured as a precise formal statement (an \
informal remark, a step that says "clearly"/"obviously" without stating precisely what \
follows, or reasoning about definitions rather than a checkable claim). If you use this \
classification you MUST also fill in unformalizable_reason.
- anchor_text: a short (roughly 5-15 word) substring copied EXACTLY, character-for-\
character, from the proof source given below, identifying where this step appears. It \
must be a verbatim quote, not a paraphrase — it is used to highlight the step in the \
original text.

Decompose the whole proof. Do not skip steps, and do not merge unrelated claims into one \
step just because they're adjacent."""

DECOMPOSE_TOOL = {
    "name": "record_decomposition",
    "description": "Record the atomic step decomposition of a number theory proof.",
    "input_schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "statement": {"type": "string"},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                        "classification": {
                            "type": "string",
                            "enum": ["lean_candidate", "computational", "unformalizable"],
                        },
                        "anchor_text": {"type": "string"},
                        "unformalizable_reason": {"type": "string"},
                    },
                    "required": ["id", "statement", "depends_on", "classification", "anchor_text"],
                },
            }
        },
        "required": ["steps"],
    },
}


@dataclass
class RawStep:
    id: str
    statement: str
    depends_on: list[str]
    classification: Classification
    anchor_text: str | None
    unformalizable_reason: str | None = field(default=None)


class DecompositionError(Exception):
    """Claude's decomposition response didn't come back in the expected shape."""


def _parse_raw_step(raw: dict, index: int) -> RawStep | None:
    """One malformed step must not take the whole proof's decomposition down
    with it (CONSTRUCTION_PLAN.md §4a.5: "a failure at step S4 should not
    prevent S1-S3's results from being shown") — caught live via the
    benchmark harness: Claude omitted `anchor_text` on one unformalizable
    step despite it being a `required` field in the tool schema (schema
    `required` is a strong hint under forced tool-use, not a hard guarantee),
    and that single omission previously raised `DecompositionError` and
    killed every other step's results too.

    `id` and `statement` are the two fields with no safe fallback — without
    them there's nothing meaningful to render, so only those cause this
    particular step to be dropped (logged, not silently). Everything else
    degrades to a safe default: missing classification becomes
    `unformalizable` with a note explaining why (never invent a formalizable
    claim), missing anchor_text becomes `None` (span_matching.find_span
    already renders that as "no highlight" rather than failing).
    """
    try:
        step_id = str(raw["id"])
        statement = str(raw["statement"])
    except KeyError:
        _logger.warning("Dropping decomposition step %d: missing id or statement: %r", index, raw)
        return None

    depends_on = [str(d) for d in raw.get("depends_on", []) or []]
    anchor_text = raw.get("anchor_text")
    anchor_text = str(anchor_text) if anchor_text is not None else None

    try:
        classification = Classification(raw["classification"])
        unformalizable_reason = raw.get("unformalizable_reason")
    except (KeyError, ValueError):
        classification = Classification.UNFORMALIZABLE
        unformalizable_reason = (
            "Decomposition response for this step was malformed "
            f"(missing or invalid classification: {raw.get('classification')!r}) — "
            "downgraded to unformalizable rather than guessing."
        )

    return RawStep(
        id=step_id,
        statement=statement,
        depends_on=depends_on,
        classification=classification,
        anchor_text=anchor_text,
        unformalizable_reason=unformalizable_reason,
    )


async def decompose(normalized_source: str) -> list[RawStep]:
    llm = get_llm(max_tokens=4096).bind_tools(
        [cached_tool(DECOMPOSE_TOOL)], tool_choice={"type": "tool", "name": "record_decomposition"}
    )
    response = await invoke_llm(
        llm,
        [
            cached_system_message(SYSTEM_PROMPT),
            {"role": "user", "content": f"Proof source:\n\n{normalized_source}"},
        ],
    )

    tool_call = next((tc for tc in response.tool_calls if tc["name"] == "record_decomposition"), None)
    if tool_call is None:
        raise DecompositionError("Claude did not return a record_decomposition tool call.")

    raw_steps = tool_call["args"].get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise DecompositionError("Claude's decomposition returned no steps.")

    steps = [s for i, raw in enumerate(raw_steps) if (s := _parse_raw_step(raw, i)) is not None]
    if not steps:
        raise DecompositionError("Every step in the decomposition response was malformed.")

    return steps
