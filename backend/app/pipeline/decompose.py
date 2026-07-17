"""Claude call #1 — decomposition (CONSTRUCTION_PLAN.md §6.2).

Splits the normalized LaTeX proof into atomic steps. Claude is never asked
for character offsets (LLMs are bad at counting characters and drift is the
common case, not the exception — §10a) — only for an exact quoted
anchor_text, which span_matching.find_span locates in the backend.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from ..claude_client import get_client
from ..config import settings
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
irrationality, etc). This includes algebraic identities/manipulations over FREE VARIABLES \
(e.g. "n^2 = 4k^2 = 2(2k^2)" for general n, k) — a step being simple algebra does not make \
it computational; what makes it computational is having no free variables at all.
  - "computational": a claim about SPECIFIC, CONCRETE NUMBERS with no free variables — \
every quantity in the statement is a literal number, not a symbol standing for an arbitrary \
integer (e.g. "gcd(48,18)=6", "1000003 is prime", "17^2 = 289"). If the statement contains \
any letter that represents an arbitrary/unspecified integer (n, k, p, q, ...), it is NOT \
computational, even if the claim is a one-line algebraic identity — classify it \
"lean_candidate" instead, since there's no single computation that decides a claim about \
all integers.
  - "premise": NOT a claim at all — a stipulation, hypothesis, or proof-strategy setup \
that the proof simply assumes or introduces ("suppose, for contradiction, that ..."; \
"let p, q be integers with ..."; "write p = 2k for some integer k"). There is nothing to \
verify here; it is given. Use this whenever the step's job is to *introduce* an object or \
assumption rather than *claim* something is true. If you use this classification, fill in \
`note` with a one-sentence description of what's being assumed/introduced.
  - "unformalizable": a step that DOES assert something, but cannot be captured as a \
precise formal statement (an informal remark, a step that says "clearly"/"obviously" \
without stating precisely what follows, a claim resting on unstated context). This is for \
claims you can't check, not for premises — if it isn't asserting anything, it's "premise" \
instead. If you use this classification, fill in `note` explaining why it can't be \
formalized.
- anchor_text: a short (roughly 5-15 word) substring copied EXACTLY, character-for-\
character, from the proof source given below, identifying where this step appears. It \
must be a verbatim quote, not a paraphrase — it is used to highlight the step in the \
original text.

Decompose the whole proof. Do not skip steps, and do not merge unrelated claims into one \
step just because they're adjacent.

The input may open with a formal goal statement — a `\\begin{theorem}`/`\\begin{proposition}`/\
`\\begin{lemma}`/`\\begin{corollary}` environment (or an equivalent stated goal immediately \
before a `\\begin{proof}` block) naming the overall claim the rest of the document exists to \
establish. Do NOT decompose that goal statement into a step of its own. It is the conclusion \
the proof steps below build up to piece by piece, not itself an atomic claim to hand to a \
verifier — asking Lean/SymPy to check the *entire* theorem in one shot is exactly the kind of \
oversized claim decomposition exists to avoid, and it would also be circular: the goal restated \
as a "step" adds nothing the actual proof steps don't already establish individually. Skip \
straight to decomposing the proof body itself (everything inside `\\begin{proof}...\\end{proof}`, \
or the argument that follows if the input never restates the goal as a separate step outside the \
proof — many short proofs given to Tark aren't structured with an explicit theorem/proof \
environment at all, and in that case there is no separate goal statement to skip: decompose \
normally starting from the first sentence). This applies per theorem if a document restates the \
goal more than once (e.g. a theorem statement followed later by "we must show X" restating the \
same goal inside the proof) — none of those restatements are themselves a step; only decompose \
the actual reasoning that establishes them. If the theorem is an "if and only if" or otherwise \
has multiple named directions/cases (e.g. "($\\Rightarrow$)" and "($\\Leftarrow$)"), decompose \
each direction's argument in sequence as its own run of steps — still never as a single step for \
the direction's own restated sub-goal.

The input may be a real, messy excerpt from a paper — bibliography commands, section/\
appendix headers, citations, custom formatting macros, multiple independent theorems and \
proofs in sequence. Handle this explicitly:
- Skip non-mathematical apparatus entirely (bibliography/citation commands, section \
headings with no claim in them, standalone `\\label`/`\\ref`). Don't manufacture a step for \
"this is a section header."
- Tark's scope is number theory. If the document contains multiple independent proofs, \
decompose the first substantial number-theory proof in full and STOP — do not continue on \
to unrelated later proofs/sections (e.g. asymptotic complexity analysis, combinatorics) \
just because they're present in the same input. Your output budget is finite; a complete \
decomposition of one proof beats a truncated decomposition of several.
- If truly nothing in the input is a number-theory proof (e.g. it's entirely bibliography/\
complexity analysis/other domains), it is legitimate to return very few steps, but say so: \
give at least one step classified "unformalizable" whose note explains that no in-scope \
proof content was found, rather than returning an empty list."""

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
                            "enum": [
                                "lean_candidate",
                                "computational",
                                "premise",
                                "unformalizable",
                            ],
                        },
                        "anchor_text": {"type": "string"},
                        "note": {
                            "type": "string",
                            "description": (
                                "Required for premise/unformalizable: what's being "
                                "assumed, or why this can't be formalized."
                            ),
                        },
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
    note: str | None = field(default=None)


class DecompositionError(Exception):
    """Claude's decomposition response didn't come back in the expected shape."""


DECOMPOSE_MAX_TOKENS = 8192
# Empty-steps responses have been observed to be sampling-variance, not
# deterministic — the same input succeeds on a retry. Bounded to 2 total
# attempts; NOT applied to a max_tokens truncation, which is a deterministic
# function of input size and will just truncate identically again.
MAX_EMPTY_RETRIES = 1


async def _decompose_once(client, normalized_source: str) -> list[RawStep]:
    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=DECOMPOSE_MAX_TOKENS,
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

    if response.stop_reason == "max_tokens":
        # The tool call's JSON was cut off mid-generation — whatever the SDK
        # salvaged (often an empty dict) is not a real decomposition. Long,
        # multi-proof inputs are the common trigger; say so specifically
        # rather than the misleading "returned no steps" a truncated call
        # would otherwise produce. Not retried — same input, same size, same
        # truncation point.
        raise DecompositionError(
            "This input is too long to decompose in a single pass (Claude's response was "
            "cut off before finishing). Try pasting a single, shorter proof rather than a "
            "full document/appendix."
        )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise DecompositionError("Claude did not return a record_decomposition tool call.")

    raw_steps = tool_use.input.get("steps")
    if isinstance(raw_steps, str):
        # On long inputs, forced tool-use occasionally emits a large `steps`
        # array double-encoded as a JSON string ({"steps": "[...]"} instead
        # of {"steps": [...]}) rather than true structured output — a real,
        # complete decomposition dodging the schema's typing, not a missing
        # one. Recover it before falling through to the empty-steps error.
        try:
            parsed = json.loads(raw_steps)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            raw_steps = parsed.get("steps")
        elif isinstance(parsed, list):
            raw_steps = parsed

    if not isinstance(raw_steps, list) or not raw_steps:
        # Root cause of empty-steps responses was never pinned down (see
        # HANDOFF.md) because no live repro captured what Claude actually
        # said. Log the full tool_use input and any accompanying text block
        # so the next occurrence is diagnosable instead of a bare error.
        text_blocks = [b.text for b in response.content if b.type == "text"]
        _logger.warning(
            "Empty decomposition steps. stop_reason=%r tool_use.input=%r text_blocks=%r",
            response.stop_reason,
            tool_use.input,
            text_blocks,
        )
        raise DecompositionError("Claude's decomposition returned no steps.")

    steps: list[RawStep] = []
    for raw in raw_steps:
        try:
            classification = Classification(raw["classification"])
        except (KeyError, ValueError):
            # A step with a missing/invalid classification is genuinely
            # ambiguous — degrade it to unformalizable rather than either
            # guessing a classification or discarding the step (and losing
            # visibility into a chunk of the user's proof) or aborting the
            # whole batch over one malformed entry (§4a.5: a failure on one
            # step must not take down the others).
            classification = Classification.UNFORMALIZABLE

        try:
            steps.append(
                RawStep(
                    id=str(raw["id"]),
                    statement=str(raw.get("statement", "(statement missing from decomposition response)")),
                    depends_on=[str(d) for d in raw.get("depends_on", [])],
                    classification=classification,
                    # anchor_text is best-effort — find_span already handles
                    # "" by rendering the step without a source highlight
                    # rather than failing, so a missing anchor_text should
                    # degrade the same way, not abort decomposition entirely.
                    anchor_text=str(raw.get("anchor_text", "")),
                    note=raw.get("note"),
                )
            )
        except KeyError:
            # No `id` at all means this entry can't be tracked (dependencies
            # reference ids) — this one genuinely has to be dropped, but
            # only this one, not the rest of the batch.
            continue

    if not steps:
        raise DecompositionError(
            "Claude's decomposition returned steps, but none could be parsed."
        )

    return steps


async def decompose(normalized_source: str) -> list[RawStep]:
    client = get_client()
    last_error: DecompositionError | None = None
    for attempt in range(MAX_EMPTY_RETRIES + 1):
        try:
            return await _decompose_once(client, normalized_source)
        except DecompositionError as exc:
            if "too long to decompose" in str(exc):
                raise  # deterministic given input size — retrying won't help
            last_error = exc
    raise last_error

    return steps
