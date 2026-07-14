"""Claude call #2 — per-step formalization (CONSTRUCTION_PLAN.md §6.3).

One call per step, meant to run in parallel across steps (the caller is
responsible for the concurrency — this module is just per-step logic).
"""
from __future__ import annotations

from ..claude_client import get_client
from ..config import settings
from ..models.schema import Classification

LEAN_SYSTEM_PROMPT = """You are the Lean formalization stage of Tark. Given one step of a \
number theory proof, produce a COMPLETE, self-contained Lean 4 file that states the step \
as a theorem and attempts to prove it using Mathlib.

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
`Mathlib.Algebra.Ring.Parity`; `Mathlib.Data.Rat.Basic` is now `Mathlib.Data.Rat.Defs`). \
Prefer well-established, long-lived paths (`Mathlib.Data.Nat.GCD.Basic`, \
`Mathlib.Data.Nat.Prime.Basic`) when you're unsure, and expect that a wrong import will \
come back as a compiler error you'll be asked to fix.
- The checker gives each attempt a hard ~45s wall-clock budget shared with other concurrent \
checks — favor Nat/Int arithmetic formulations over Real-number ones where the underlying \
proof allows it, since `Real.sqrt` alone costs ~25s to import regardless of proof \
complexity. That budget accounts for it, but a Nat/Int formulation is still faster and \
more likely to succeed under concurrency.
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
