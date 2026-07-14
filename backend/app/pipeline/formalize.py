"""Claude call #2 — per-step formalization (CONSTRUCTION_PLAN.md §6.3).

One call per step, meant to run in parallel across steps (the caller is
responsible for the concurrency — this module is just per-step logic).
"""
from __future__ import annotations

from langchain_core.messages import BaseMessage, ToolMessage

from ..claude_client import cached_system_message, cached_tool, get_llm, invoke_llm
from ..models.schema import Classification
from .mathlib_search import SEARCH_MATHLIB_TOOL, search_mathlib

# Measured directly on this branch (Phase 0 instrumentation): most repair
# rounds that don't converge are burned either re-guessing an import path
# across attempts, or hand-rolling a tactic proof for something Mathlib
# already has a lemma for, with a syntax mistake in the process. Both are
# checkable *before* paying for a Lean subprocess round-trip.
MAX_TOOL_ROUNDS = 4

LEAN_SYSTEM_PROMPT = """You are the Lean formalization stage of Tark. Given one step of a \
number theory proof, produce a COMPLETE, self-contained Lean 4 file that states the step \
as a theorem and attempts to prove it using Mathlib.

You have a `search_mathlib` tool (backed by Loogle) — use it before writing tactics or \
imports you're not certain of, to check a lemma actually exists and find its real import \
path, rather than guessing and finding out from a compiler error. This is optional but \
strongly encouraged for anything beyond `ring`/`omega`/`decide`-level arithmetic. Call it \
as many times as you need (a few short searches beat one wrong guess), then call \
`record_lean_formalization` once you have a final attempt.

If the step you're given lists earlier established steps, formalize this step's theorem \
*given those as hypotheses* — do not invent freestanding premises for something an earlier \
step already established, and do not re-prove the earlier steps yourselves; state your \
theorem so it takes them as parameters/hypotheses instead.

Rules:
- Use TARGETED Mathlib imports only (e.g. `import Mathlib.Data.Nat.GCD.Basic`). Never \
write bare `import Mathlib` — importing the whole library takes 50+ seconds and will time \
out the checker.
- Also avoid broad umbrella imports that pull in huge chunks of the library despite \
sounding narrow: `Mathlib.Tactic` (imports the entire tactic framework) and most of \
`Mathlib.Analysis.*`. Most `omega`, `ring`, `linarith`, `norm_num`, `decide`, `field_simp` \
tactics are available from a small, specific import or from core Lean — import the \
narrowest file that defines the specific lemma/definition you actually need, not a \
category-level umbrella. If the step genuinely needs `Real.sqrt`, use \
`import Mathlib.Analysis.Real.Sqrt` specifically (see pattern 5 below) — not \
`Mathlib.Analysis.SpecialFunctions.Sqrt`, which doesn't reliably exist at that path and, \
even when it resolves, pulls in more than needed.
- Mathlib reorganizes its file layout often, more often than your training data — a plausible \
import path may no longer exist (e.g. `Mathlib.Data.Nat.Parity` is now \
`Mathlib.Algebra.Ring.Parity`; `Mathlib.Data.Rat.Basic` is now `Mathlib.Data.Rat.Defs`). Use \
`search_mathlib` to confirm the real module path when unsure, rather than guessing.
- `import Tark.Prelude` is a precompiled bundle covering the imports that recur most often in \
this project's proofs (Nat/Int parity and GCD, Rat basics, Real.sqrt, Irrational, and the \
ring/linarith/norm_num tactics) — measured directly to load at the same speed as listing 3+ \
of those imports individually (both already come from Mathlib's precompiled cache), so if a \
step needs two or more of those areas, or you're at all unsure of an exact path among them, \
prefer this single import over guessing. For a step that only needs one narrow, well-known \
import (e.g. just `ring` or `Nat.GCD.Basic` alone), keep using that single targeted import — \
measured slightly slower (~0.5s) than a single small import alone, since it always loads the \
Real/Analysis content too even when unneeded.
- The checker gives each attempt a hard wall-clock budget shared with other concurrent \
checks (30s for a first-round attempt, 45s for a repair attempt) — favor Nat/Int arithmetic \
formulations over Real-number ones where the underlying proof allows it, since `Real.sqrt` \
alone costs ~25s to import regardless of proof complexity (measured by timing it against a \
trivial goal, isolating import cost from proof cost) — that's most of a first-round \
attempt's budget before any tactic even runs, so a Real.sqrt-based first attempt is much \
more likely to need a repair round than a Nat/Int one purely on import cost, not proof \
difficulty.
- The file must be syntactically complete: import lines, then \
`theorem <name> : <statement> := by <tactics>`.
- Attempt a real proof — do not use `sorry`. If you cannot complete the proof, submit \
your best attempt anyway; Lean will correctly report it as unverified, which is a fine \
outcome. You are not the source of truth here, Lean's compiler is — never claim the proof \
works, just submit your best formalization.
- `omega` needs NO import — it's a core Lean tactic, not Mathlib. `ring`/`ring_nf` needs \
`import Mathlib.Tactic.Ring`. `norm_num` needs `import Mathlib.Tactic.NormNum`. Forgetting \
these is a common, avoidable failure — the tactic itself being "basic" does not mean it's \
available for free.

The following patterns are verified to compile against this exact Mathlib pin. When a step \
matches one of these shapes, adapt the pattern directly rather than reconstructing an \
approach from memory — memory is exactly what tends to cite renamed/nonexistent lemmas.

1. A square is even iff its base is even:
```lean
import Mathlib.Algebra.Ring.Parity

theorem ex1 (n k : ℕ) (h : n ^ 2 = 2 * k ^ 2) : Even n := by
  have h2 : Even (n ^ 2) := ⟨k ^ 2, by omega⟩
  exact (Nat.even_pow.mp h2).1
```

2. Unpacking `Even n` into a witness `n = 2 * k`:
```lean
import Mathlib.Algebra.Ring.Parity

theorem ex2 (n : ℕ) (hn : Even n) : ∃ k : ℕ, n = 2 * k := by
  obtain ⟨k, hk⟩ := hn
  exact ⟨k, by omega⟩
```

3. Two even numbers can't be coprime (note: needs GCD.Basic AND Parity AND NormNum together \
— a step mixing concepts needs an import per concept, not just one):
```lean
import Mathlib.Data.Nat.GCD.Basic
import Mathlib.Algebra.Ring.Parity
import Mathlib.Tactic.NormNum

theorem ex3 (p q : ℕ) (hgcd : Nat.gcd p q = 1) (hp : Even p) (hq : Even q) : False := by
  have h2p : (2 : ℕ) ∣ p := hp.two_dvd
  have h2q : (2 : ℕ) ∣ q := hq.two_dvd
  have h2gcd : (2 : ℕ) ∣ Nat.gcd p q := Nat.dvd_gcd h2p h2q
  rw [hgcd] at h2gcd
  exact (by norm_num : ¬ (2 : ℕ) ∣ 1) h2gcd
```

4. Pure algebraic substitution/rearrangement — prefer `ring_nf` + `omega` over manual \
rewriting:
```lean
import Mathlib.Tactic.Ring

theorem ex4 (p q k : ℕ) (hp : p = 2 * k) (h : p ^ 2 = 2 * q ^ 2) : 4 * k ^ 2 = 2 * q ^ 2 := by
  subst hp
  ring_nf
  ring_nf at h
  omega
```

5. Squaring a `Real.sqrt` equation (the ~25s cost below is the import alone, proved by \
timing it against a trivial goal — budget for it, don't avoid the statement because of it):
```lean
import Mathlib.Analysis.Real.Sqrt

theorem ex5 (p q : ℤ) (h : (p:ℝ) = (q:ℝ) * Real.sqrt 2) :
    (p:ℝ) ^ 2 = 2 * (q:ℝ) ^ 2 := by
  have hsq : Real.sqrt 2 ^ 2 = 2 := Real.sq_sqrt (by norm_num)
  rw [h, mul_pow, hsq]
  ring
```
Prefer the multiplicative form (`p = q * sqrt 2`) over a division form (`p / q = sqrt 2`) \
where the source allows it — it avoids needing `field_simp` on top of the already-heavy \
import.

6. `sqrt(2)` (or any prime) is irrational — the whole proof is one line, don't overcomplicate \
it with a manual contradiction argument:
```lean
import Mathlib.Analysis.Real.Sqrt
import Mathlib.NumberTheory.Real.Irrational

theorem ex6 : Irrational (Real.sqrt 2) :=
  Nat.prime_two.irrational_sqrt
```
`Irrational` lives at `Mathlib.NumberTheory.Real.Irrational`, not \
`Mathlib.Data.Real.Irrational` (renamed). `Nat.Prime.irrational_sqrt` takes the primality \
proof directly (`Nat.prime_two`, or `by norm_num` for other primes) — no need to unfold \
`Nat.Prime` into its components first."""

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
- No I/O, no randomness, no network access — deterministic computation only.
- If the step lists earlier established steps, take their conclusions as given (hardcode \
values/facts they establish rather than recomputing or ignoring them) instead of treating \
this step as if it stood alone."""

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


def _dependency_context_block(dependency_statements: list[tuple[str, str]] | None) -> str:
    """Without this, a step is formalized as a freestanding claim even when
    it logically depends on earlier steps in the proof — e.g. "gcd(p,q) = 1
    and p^2 = 2q^2, so p is even" gets formalized with *invented* hypotheses
    for gcd(p,q)=1 and p^2=2q^2 instead of taking them as given, which is
    both a fidelity problem (verifying a different, standalone claim than
    the one the proof actually makes) and a success-rate problem (some
    steps are only easy to prove *given* their dependencies).
    """
    if not dependency_statements:
        return ""
    lines = "\n".join(f"- {step_id}: {statement}" for step_id, statement in dependency_statements)
    return (
        "\n\nThe following earlier steps in this proof have already been established — "
        "you do not need to reprove them, and you should take them as given hypotheses "
        "in your theorem statement rather than reproving or ignoring them:\n" + lines
    )


# Ensemble candidates were originally generated with a generic "try something
# different" suffix, which measurably produced near-identical (sometimes
# byte-identical) candidates across the "variants" — 3 Lean subprocess slots
# spent to verify 1 actual attempt. These are concrete, differently-shaped
# strategies instead, so the 3 candidates are genuinely likely to diverge.
#
# Kept at exactly 3 entries deliberately, matching the previously-tuned
# ensemble/semaphore concurrency budget — measured directly (this branch,
# bench.py): a 4th strategy pushed real per-step Lean-check load from 3 to 4,
# and because real diversity means there's nothing left to dedup, that load
# increase showed up directly as more semaphore contention with no wall-time
# win. Add a 4th only alongside re-validating (and likely raising) the
# concurrency budget, not silently.
ENSEMBLE_STRATEGIES: list[str | None] = [
    None,  # first attempt: no steering, Claude's own default approach
    (
        "Strategy for this attempt: use `search_mathlib` to find an existing Mathlib "
        "lemma whose type shape already matches this claim (or is one step away from "
        "it), and build the proof primarily by applying that lemma directly rather "
        "than a from-scratch tactic sequence."
    ),
    (
        "Strategy for this attempt: write a self-contained elementary proof using only "
        "basic tactics (`omega`, `decide`, `norm_num`, `ring`, `simp`) over Nat/Int "
        "arithmetic — avoid searching for or citing named Mathlib lemmas beyond core "
        "definitions, and avoid Real-number formulations entirely."
    ),
]


async def _run_lean_agent(user_message: str) -> str:
    """Runs the Lean-formalization tool loop: Claude may call `search_mathlib`
    zero or more times to check lemma/import names against real Mathlib
    before submitting `record_lean_formalization`. `tool_choice="any"` (not a
    specific tool) is what makes this a real choice each round — forcing
    `record_lean_formalization` specifically, as a single direct call would,
    makes the search tool unreachable.
    """
    tools = [SEARCH_MATHLIB_TOOL, cached_tool(LEAN_TOOL)]
    messages: list[BaseMessage | dict] = [
        cached_system_message(LEAN_SYSTEM_PROMPT),
        {"role": "user", "content": user_message},
    ]

    for round_num in range(1, MAX_TOOL_ROUNDS + 1):
        # On the final round, force the formalization tool specifically —
        # otherwise a Claude that keeps searching without converging burns
        # the whole call on search_mathlib and produces zero Lean attempts,
        # which is strictly worse than submitting an imperfect best guess.
        is_last_round = round_num == MAX_TOOL_ROUNDS
        tool_choice = (
            {"type": "tool", "name": "record_lean_formalization"} if is_last_round else "any"
        )
        llm = get_llm(max_tokens=2048).bind_tools(tools, tool_choice=tool_choice)
        response = await invoke_llm(llm, messages)

        if not response.tool_calls:
            raise FormalizationError("Claude did not return a tool call.")

        formalization = next(
            (tc for tc in response.tool_calls if tc["name"] == "record_lean_formalization"), None
        )
        if formalization is not None:
            if "lean_code" not in formalization["args"]:
                raise FormalizationError("record_lean_formalization call missing lean_code.")
            return str(formalization["args"]["lean_code"])

        # Only search_mathlib calls this round: execute them and continue the
        # conversation so Claude can use the results before its next attempt.
        messages.append(response)
        for tc in response.tool_calls:
            if tc["name"] != "search_mathlib":
                continue
            query = str(tc["args"].get("query", ""))
            result_text = await search_mathlib(query)
            messages.append(ToolMessage(content=result_text, tool_call_id=tc["id"]))

    raise FormalizationError("Exceeded max tool-use rounds without a final Lean formalization.")


async def formalize_lean(
    statement: str,
    strategy_hint: str | None = None,
    dependency_statements: list[tuple[str, str]] | None = None,
) -> str:
    user_message = f"Step to formalize:\n\n{statement}"
    user_message += _dependency_context_block(dependency_statements)
    if strategy_hint:
        user_message += f"\n\n{strategy_hint}"
    return await _run_lean_agent(user_message)


async def formalize_lean_repair(
    statement: str,
    previous_code: str,
    lean_error: str,
    dependency_statements: list[tuple[str, str]] | None = None,
) -> str:
    """The repair loop (CONSTRUCTION_PLAN.md §8.3) — Lean's compiler is the
    adversary. Only called for syntax/tactic-level failures, never for a
    genuine mathematical REFUTED (the caller decides that, not this).
    """
    user_message = (
        f"Step to formalize:\n\n{statement}"
        f"{_dependency_context_block(dependency_statements)}\n\n"
        "Your previous attempt did not compile. Here is exactly what you submitted:\n\n"
        f"```lean\n{previous_code}\n```\n\n"
        f"Here is Lean's exact compiler output:\n\n{lean_error}\n\n"
        "Fix it and submit a corrected, complete Lean 4 file. If the error is "
        "\"object file ... does not exist\" for one of your imports, that module has been "
        "renamed or moved in this Mathlib version — use search_mathlib to find the real "
        "current path rather than guessing again. If the error is an unsolved goal or unknown "
        "tactic, use search_mathlib to check whether Mathlib already has a lemma matching the "
        "goal shape before hand-rolling another tactic proof."
    )
    return await _run_lean_agent(user_message)


async def formalize_computational(
    statement: str, dependency_statements: list[tuple[str, str]] | None = None
) -> str:
    llm = get_llm(max_tokens=1024).bind_tools(
        [cached_tool(SYMPY_TOOL)], tool_choice={"type": "tool", "name": "record_computational_formalization"}
    )
    user_content = f"Step to check:\n\n{statement}" + _dependency_context_block(dependency_statements)
    response = await invoke_llm(
        llm,
        [
            cached_system_message(SYMPY_SYSTEM_PROMPT),
            {"role": "user", "content": user_content},
        ],
    )
    tool_call = next(
        (tc for tc in response.tool_calls if tc["name"] == "record_computational_formalization"), None
    )
    if tool_call is None or "python_code" not in tool_call["args"]:
        raise FormalizationError(
            "Claude did not return a record_computational_formalization tool call."
        )
    return str(tool_call["args"]["python_code"])


async def formalize(
    classification: Classification,
    statement: str,
    dependency_statements: list[tuple[str, str]] | None = None,
) -> tuple[str | None, str | None]:
    """Returns (lean_code, python_code) — exactly one populated."""
    if classification == Classification.LEAN_CANDIDATE:
        return await formalize_lean(statement, dependency_statements=dependency_statements), None
    if classification == Classification.COMPUTATIONAL:
        return None, await formalize_computational(statement, dependency_statements=dependency_statements)
    raise FormalizationError(f"formalize() called for non-formalizable classification: {classification}")
