"""Claude call #3 — the advisory pass (CONSTRUCTION_PLAN.md §6 stage 6).

Separate from decomposition/formalization: reviews the *whole* proof plus
the verdicts Lean/SymPy already produced, and flags anything it's
suspicious of. This never touches verdicts — it's explicitly opinion, kept
in `claude_global_notes`, structurally and visually separate from the
per-step verifier results (§6: "never merged into the verdict").
"""
from __future__ import annotations

from ..claude_client import cached_system_message, cached_tool, get_llm, invoke_llm
from ..models.schema import Step

SYSTEM_PROMPT = """You are the advisory stage of Tark, a proof verification tool.

Per-step verdicts have already been produced by Lean/SymPy — you are not changing or \
second-guessing those. Your job is different: read the whole proof, with the verdicts \
already assigned to each step, and flag anything a careful mathematician reviewing this \
proof would want to double check. Independent of what Lean/SymPy found, look for:
- Logical gaps between consecutive steps that the step-by-step decomposition might have \
smoothed over.
- Hidden assumptions that were never stated as premises.
- Steps whose formal verdict (e.g. UNVERIFIED) might be masking a more fundamental issue \
with the proof strategy, versus just a formalization difficulty.
- Anything about the proof's structure or rigor worth a human's attention.

Do not repeat what's already visible in the per-step verdicts or notes. Do not claim \
anything is correct or incorrect — you are not a verifier. If you have nothing beyond what \
the step-level results already show, return an empty list; do not manufacture filler \
observations."""

ADVISORY_TOOL = {
    "name": "record_advisory_notes",
    "description": "Record whole-proof observations, independent of per-step verdicts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Each a short, standalone observation. Empty list if none.",
            }
        },
        "required": ["notes"],
    },
}


def _describe_step(step: Step) -> str:
    return f"{step.id} [{step.classification.value} -> {step.verdict.value}]: {step.statement}"


async def run_advisory_pass(normalized_source: str, steps: list[Step]) -> list[str]:
    """Never raises — this is supplementary commentary on an already-complete
    report. A failed advisory call (network, API) just means no extra notes,
    not a failed verification run.
    """
    try:
        step_summary = "\n".join(_describe_step(s) for s in steps)
        user_message = (
            f"Proof source:\n\n{normalized_source}\n\n"
            f"Steps with their already-assigned verdicts:\n\n{step_summary}"
        )
        llm = get_llm(max_tokens=1024).bind_tools(
            [cached_tool(ADVISORY_TOOL)], tool_choice={"type": "tool", "name": "record_advisory_notes"}
        )
        response = await invoke_llm(
            llm,
            [cached_system_message(SYSTEM_PROMPT), {"role": "user", "content": user_message}],
        )
    except Exception:  # noqa: BLE001 - advisory notes are non-critical, never block the report
        return []

    tool_call = next((tc for tc in response.tool_calls if tc["name"] == "record_advisory_notes"), None)
    if tool_call is None:
        return []
    notes = tool_call["args"].get("notes")
    if not isinstance(notes, list):
        return []
    return [str(n) for n in notes]
