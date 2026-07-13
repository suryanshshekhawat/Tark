"""Advisory-only counterexample probe.

For a Lean-candidate step that ends UNVERIFIED after every formalization and
repair attempt, ask Claude for a small, deterministic search over concrete
values for a counterexample to the step's claim. This NEVER changes the
step's verdict — UNVERIFIED stays UNVERIFIED, full stop — it only ever adds
a note (like Claude's existing "suspicion" notes) if the search actually
finds one, clearly labeled as a computational probe rather than an opinion.

Deliberately kept fully separate from `SympyVerifier` (which DOES produce
VERIFIED/REFUTED verdicts): this probe runs its own small sandboxed runner
with its own `found`/`counterexample` result shape, so a probe bug or a
mis-translated claim can never be mistaken for, or accidentally feed into,
an actual verdict. See CLAUDE.md — a false REFUTED is worse than a missed
one; this probe is not allowed anywhere near REFUTED at all.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from ..claude_client import cached_system_message, cached_tool, get_llm, invoke_llm
from ..models.schema import ClaudeNote, ClaudeNoteType

PROBE_TIMEOUT = 8.0

PROBE_SYSTEM_PROMPT = """You are the counterexample-probe stage of Tark, an advisory-only \
check — nothing you produce here can ever change a step's verdict, only add a labeled note \
a user can see. Given a number-theory claim that Lean could not verify, decide whether the \
claim is a concrete, decidable claim you could search small integer ranges for a \
counterexample to (e.g. a bounded or effectively-bounded universal statement) — most claims \
with unbounded quantifiers over all integers, or Real-number/analytic claims, are NOT \
concretely testable this way; decline rather than searching an unrepresentative window and \
implying it means something it doesn't.

If testable: write a Python/SymPy snippet that searches a small, explicit range (comment the \
range) for a concrete counterexample. Set `found` to True/False, and if True, set \
`counterexample` to a short string describing the concrete values found.

If not concretely testable: call the tool with testable=false and no code.

Rules:
- Only these modules are importable: math, sympy, fractions, itertools, functools, decimal, \
cmath, statistics, numbers.
- No I/O, no randomness, no network access — deterministic computation only.
- Keep the search small enough to run in a few seconds (at most a few thousand iterations)."""

PROBE_TOOL = {
    "name": "record_counterexample_probe",
    "description": "Record whether this claim is concretely testable, and if so, the search snippet.",
    "input_schema": {
        "type": "object",
        "properties": {
            "testable": {"type": "boolean"},
            "python_code": {
                "type": "string",
                "description": "Python snippet setting `found` (bool) and `counterexample` (str, only if found).",
            },
        },
        "required": ["testable"],
    },
}

_RUNNER_TEMPLATE = r"""
import json

ALLOWED_MODULES = {
    "math", "sympy", "fractions", "itertools", "functools", "decimal",
    "cmath", "statistics", "numbers",
}

def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if root not in ALLOWED_MODULES:
        raise ImportError(f"import of '{name}' is not allowed in the sandbox")
    return __import__(name, globals, locals, fromlist, level)

SAFE_BUILTINS = {
    name: getattr(__builtins__, name)
    for name in (
        "abs", "all", "any", "bool", "dict", "enumerate", "float", "frozenset",
        "int", "len", "list", "max", "min", "pow", "range", "reversed",
        "round", "set", "sorted", "str", "sum", "tuple", "zip", "True",
        "False", "None",
    )
    if hasattr(__builtins__, name)
}
SAFE_BUILTINS["__import__"] = _restricted_import

def _run():
    import math
    import sympy
    namespace = {"__builtins__": SAFE_BUILTINS, "sympy": sympy, "math": math}
    try:
        exec(USER_CODE, namespace)
    except Exception as exc:  # noqa: BLE001 - must report, never crash silently
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return
    found = namespace.get("found")
    if not isinstance(found, bool):
        print(json.dumps({"ok": False, "error": "snippet did not set `found` to a bool"}))
        return
    counterexample = namespace.get("counterexample")
    print(json.dumps({
        "ok": True,
        "found": found,
        "counterexample": str(counterexample) if counterexample else None,
    }))

_run()
"""


def _run_probe_code(code: str, timeout: float = PROBE_TIMEOUT) -> tuple[bool, str | None]:
    """Runs in a fresh, restricted subprocess — the same sandboxing pattern
    as SympyVerifier (separate process, restricted builtins, no filesystem/
    network access, timeout), but its own runner and result shape so this
    can never be confused with a verdict-producing check. Never raises;
    any failure just means "no counterexample found" — fail closed on the
    advisory note, exactly as if the probe were never run at all.
    """
    runner_source = "USER_CODE = " + repr(code) + "\n" + _RUNNER_TEMPLATE
    with tempfile.TemporaryDirectory() as tmp_dir:
        runner_path = Path(tmp_dir) / "probe.py"
        runner_path.write_text(runner_source, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(runner_path)],
                cwd=tmp_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, None

    if proc.returncode != 0:
        return False, None
    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return False, None
    if not payload.get("ok"):
        return False, None
    return bool(payload.get("found")), payload.get("counterexample")


async def probe_for_counterexample(statement: str) -> ClaudeNote | None:
    """Returns a ClaudeNote (type=SUSPICION, text clearly labeled as a
    computational probe) if a concrete counterexample was found, else None.
    Never raises — a probe failure just means no note, identical to the
    behavior with no probe at all.
    """
    try:
        llm = get_llm(max_tokens=1024).bind_tools(
            [cached_tool(PROBE_TOOL)], tool_choice={"type": "tool", "name": "record_counterexample_probe"}
        )
        response = await invoke_llm(
            llm,
            [
                cached_system_message(PROBE_SYSTEM_PROMPT),
                {"role": "user", "content": f"Claim Lean could not verify:\n\n{statement}"},
            ],
        )
        tool_call = next(
            (tc for tc in response.tool_calls if tc["name"] == "record_counterexample_probe"), None
        )
        if tool_call is None:
            return None
        args = tool_call["args"]
        if not args.get("testable") or not args.get("python_code"):
            return None

        found, counterexample_desc = await asyncio.to_thread(_run_probe_code, args["python_code"])
    except Exception:  # noqa: BLE001 - advisory only, never let a probe failure affect the pipeline
        return None

    if not found:
        return None

    text = "Computational probe: a search over concrete values found a counterexample"
    if counterexample_desc:
        text += f" ({counterexample_desc})"
    text += (
        ". This is an advisory signal from a small automated search, not a verdict — it does "
        "not change this step's UNVERIFIED status, but is worth checking directly."
    )
    return ClaudeNote(type=ClaudeNoteType.SUSPICION, text=text)
