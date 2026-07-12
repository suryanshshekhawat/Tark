"""Claude call #1 — decomposition (CONSTRUCTION_PLAN.md §6.2).

Splits the normalized LaTeX proof into atomic steps. Claude is never asked
for character offsets (LLMs are bad at counting characters and drift is the
common case, not the exception — §10a) — only for an exact quoted
anchor_text, which span_matching.find_span locates in the backend.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..claude_client import get_client
from ..config import settings
from ..models.schema import Classification

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
    anchor_text: str
    unformalizable_reason: str | None = field(default=None)


class DecompositionError(Exception):
    """Claude's decomposition response didn't come back in the expected shape."""


async def decompose(normalized_source: str) -> list[RawStep]:
    client = get_client()
    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Proof source:\n\n{normalized_source}",
            }
        ],
        tools=[DECOMPOSE_TOOL],
        tool_choice={"type": "tool", "name": "record_decomposition"},
    )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise DecompositionError("Claude did not return a record_decomposition tool call.")

    raw_steps = tool_use.input.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise DecompositionError("Claude's decomposition returned no steps.")

    steps: list[RawStep] = []
    for raw in raw_steps:
        try:
            steps.append(
                RawStep(
                    id=str(raw["id"]),
                    statement=str(raw["statement"]),
                    depends_on=[str(d) for d in raw.get("depends_on", [])],
                    classification=Classification(raw["classification"]),
                    anchor_text=str(raw["anchor_text"]),
                    unformalizable_reason=raw.get("unformalizable_reason"),
                )
            )
        except (KeyError, ValueError) as exc:
            raise DecompositionError(f"Malformed step in decomposition response: {raw}") from exc

    return steps
