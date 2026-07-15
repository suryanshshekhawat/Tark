"""Claude call #2 — per-step formalization (CONSTRUCTION_PLAN.md §6.3).

One call per step, meant to run in parallel across steps (the caller is
responsible for the concurrency — this module is just per-step logic).
"""
from __future__ import annotations

from ..claude_client import get_client
from ..config import settings
from ..models.schema import Classification
from .cookbook_loader import build_lean_system_prompt

# The cookbook (imports discipline + every worked pattern) now lives at
# lean_cookbook/ as individual, independently-verified files — see
# lean_cookbook/README.md. Adding a new pattern is a matter of adding a file
# there, not editing this module; build_lean_system_prompt() assembles them
# at import time.
LEAN_SYSTEM_PROMPT = build_lean_system_prompt()

LEAN_TOOL = {
    "name": "record_lean_formalization",
    "description": "Record a Lean 4 formalization attempt for one proof step.",
    "input_schema": {
        "type": "object",
        "properties": {
            "lean_code": {
                "type": "string",
                "description": "Complete Lean 4 file content: imports + theorem + proof attempt.",
            }
        },
        "required": ["lean_code"],
    },
}

SYMPY_SYSTEM_PROMPT = """You are the computational formalization stage of Tark. Given one \
step of a number theory proof, produce a Python snippet that sets a boolean variable \
`result` to True or False, mechanically evaluating whether the claim holds.

Rules:
- Do NOT write `import` statements — the sandbox exposes no import machinery at all. These \
names are already bound and ready to use directly: `math`, `sympy`, `fractions`, \
`itertools`, `functools`, `decimal`, `cmath`, `statistics`, `numbers`.
- Do not access dunder attributes (anything starting with `_`, e.g. `__class__`) — the \
sandbox rejects them at compile time regardless of what you're trying to do with them.
- The snippet must set a variable literally named `result` — nothing else is read back.
- No I/O, no randomness, no network access — deterministic computation only."""

SYMPY_TOOL = {
    "name": "record_computational_formalization",
    "description": "Record a computational (Python/SymPy) check for one proof step.",
    "input_schema": {
        "type": "object",
        "properties": {
            "python_code": {
                "type": "string",
                "description": "Python snippet that sets `result` to True or False.",
            }
        },
        "required": ["python_code"],
    },
}


class FormalizationError(Exception):
    pass


async def formalize_lean(statement: str) -> str:
    client = get_client()
    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=2048,
        system=LEAN_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Step to formalize:\n\n{statement}"}],
        tools=[LEAN_TOOL],
        tool_choice={"type": "tool", "name": "record_lean_formalization"},
    )
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None or "lean_code" not in tool_use.input:
        raise FormalizationError("Claude did not return a record_lean_formalization tool call.")
    return str(tool_use.input["lean_code"])


async def formalize_lean_repair(statement: str, previous_code: str, lean_error: str) -> str:
    """The repair loop (CONSTRUCTION_PLAN.md §8.3) — Lean's compiler is the
    adversary. Only called for syntax/tactic-level failures, never for a
    genuine mathematical REFUTED (the caller decides that, not this).
    """
    client = get_client()
    user_message = (
        f"Step to formalize:\n\n{statement}\n\n"
        "Your previous attempt did not compile. Here is exactly what you submitted:\n\n"
        f"```lean\n{previous_code}\n```\n\n"
        f"Here is Lean's exact compiler output:\n\n{lean_error}\n\n"
        "Fix it and submit a corrected, complete Lean 4 file. If the error is "
        "\"object file ... does not exist\" for one of your imports, that module has been "
        "renamed or moved in this Mathlib version — try a different, more standard path for "
        "the same concept. If the error is an unsolved goal or unknown tactic, fix the proof "
        "itself, not just the imports."
    )
    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=2048,
        system=LEAN_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
        tools=[LEAN_TOOL],
        tool_choice={"type": "tool", "name": "record_lean_formalization"},
    )
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None or "lean_code" not in tool_use.input:
        raise FormalizationError(
            "Claude did not return a record_lean_formalization tool call (repair)."
        )
    return str(tool_use.input["lean_code"])


async def formalize_computational(statement: str) -> str:
    client = get_client()
    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=SYMPY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Step to check:\n\n{statement}"}],
        tools=[SYMPY_TOOL],
        tool_choice={"type": "tool", "name": "record_computational_formalization"},
    )
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None or "python_code" not in tool_use.input:
        raise FormalizationError(
            "Claude did not return a record_computational_formalization tool call."
        )
    return str(tool_use.input["python_code"])


async def formalize(classification: Classification, statement: str) -> tuple[str | None, str | None]:
    """Returns (lean_code, python_code) — exactly one populated."""
    if classification == Classification.LEAN_CANDIDATE:
        return await formalize_lean(statement), None
    if classification == Classification.COMPUTATIONAL:
        return None, await formalize_computational(statement)
    raise FormalizationError(f"formalize() called for non-formalizable classification: {classification}")
