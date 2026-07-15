"""SymPy / computational verifier backend — CONSTRUCTION_PLAN.md §9.

Claude-generated snippets are untrusted. They run in a fresh subprocess (not
`eval()` in-process), compiled with RestrictedPython rather than a hand-rolled
restricted-builtins dict — a plain `exec(code, {"__builtins__": {...safe...}})`
is escapable: `().__class__.__base__.__subclasses__()` reaches every live
Python class (including `subprocess.Popen`) without ever calling `import`,
bypassing any import allowlist entirely. Verified this directly against the
old implementation before switching. RestrictedPython rejects dunder
attribute access (`__class__`, `__globals__`, ...) at compile time.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from ..models.schema import Evidence, Verdict, VerifierName
from .base import Verifier, VerdictResult

DEFAULT_TIMEOUT = 8.0  # seconds — §9: ~5-10s

# Runs in a *separate* interpreter process, invoked with `-I` (isolated mode:
# ignores PYTHONPATH/user site). No `__import__` is exposed, so `import X`
# always fails — the modules below are the entire available surface, handed
# in as pre-bound names rather than importable ones.
_RUNNER_TEMPLATE = r"""
import json
import math
import operator
import sympy
import fractions
import itertools
import functools
import decimal
import cmath
import statistics
import numbers

from RestrictedPython import compile_restricted, safe_globals
from RestrictedPython.Eval import default_guarded_getitem
from RestrictedPython.Guards import (
    full_write_guard,
    guarded_iter_unpack_sequence,
    guarded_unpack_sequence,
    safer_getattr,
)

_INPLACE_OPS = {
    "+=": operator.iadd, "-=": operator.isub, "*=": operator.imul,
    "/=": operator.itruediv, "//=": operator.ifloordiv, "%=": operator.imod,
    "**=": operator.ipow,
}

def _inplacevar_(op, x, y):
    if op not in _INPLACE_OPS:
        raise TypeError(f"augmented assignment {op!r} is not allowed")
    return _INPLACE_OPS[op](x, y)

def _run():
    try:
        byte_code = compile_restricted(USER_CODE, filename="<snippet>", mode="exec")
    except SyntaxError as exc:
        print(json.dumps({"ok": False, "error": f"SyntaxError: {exc}"}))
        return

    restricted_globals = dict(safe_globals)
    # RestrictedPython's compiled bytecode calls out to these seven guard
    # hooks for ordinary Python constructs (attribute access, subscripting,
    # iteration, unpacking, augmented assignment, writes) — there is no
    # built-in default for any of them, `safe_globals` supplies none of
    # them, and a missing one doesn't fail loudly: the snippet just dies
    # with a bare, misleading NameError. This list was pulled directly from
    # RestrictedPython's transformer source (every `ast.Name('_..._')` it
    # emits), not assembled by discovering gaps one at a time.
    restricted_globals["_getattr_"] = safer_getattr
    restricted_globals["_getitem_"] = default_guarded_getitem
    restricted_globals["_getiter_"] = iter
    restricted_globals["_iter_unpack_sequence_"] = guarded_iter_unpack_sequence
    restricted_globals["_unpack_sequence_"] = guarded_unpack_sequence
    restricted_globals["_inplacevar_"] = _inplacevar_
    restricted_globals["_write_"] = full_write_guard
    restricted_globals.update({
        "math": math, "sympy": sympy, "fractions": fractions,
        "itertools": itertools, "functools": functools, "decimal": decimal,
        "cmath": cmath, "statistics": statistics, "numbers": numbers,
    })

    try:
        exec(byte_code, restricted_globals)
    except Exception as exc:  # noqa: BLE001 - must report, never crash silently
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return

    if "result" not in restricted_globals:
        print(json.dumps({"ok": False, "error": "snippet did not set a `result` variable"}))
        return
    result = restricted_globals["result"]
    if not isinstance(result, bool):
        print(json.dumps({"ok": False, "error": f"`result` must be bool, got {type(result).__name__}"}))
        return
    print(json.dumps({"ok": True, "result": result}))

_run()
"""


class SympyVerifier(Verifier):
    def check(self, code: str, timeout: float = DEFAULT_TIMEOUT) -> VerdictResult:
        runner_source = "USER_CODE = " + repr(code) + "\n" + _RUNNER_TEMPLATE

        with tempfile.TemporaryDirectory() as tmp_dir:
            runner_path = Path(tmp_dir) / "runner.py"
            runner_path.write_text(runner_source, encoding="utf-8")

            try:
                proc = subprocess.run(
                    [sys.executable, "-I", str(runner_path)],
                    cwd=tmp_dir,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    # See lean_verifier.py: without this, Windows decodes
                    # subprocess output with the cp1252 locale encoding
                    # instead of UTF-8, which can crash mid-read on
                    # non-cp1252 output (e.g. a traceback quoting Unicode
                    # from the user's proof).
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.TimeoutExpired:
                return VerdictResult(
                    verdict=Verdict.UNVERIFIED,
                    verifier=VerifierName.SYMPY,
                    evidence=Evidence(
                        raw_output=f"Computational check timed out after {timeout}s.",
                        exit_code=None,
                    ),
                )

        raw_output = f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"

        if proc.returncode != 0:
            return VerdictResult(
                verdict=Verdict.UNVERIFIED,
                verifier=VerifierName.SYMPY,
                evidence=Evidence(raw_output=raw_output, exit_code=proc.returncode),
            )

        try:
            payload = json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            return VerdictResult(
                verdict=Verdict.UNVERIFIED,
                verifier=VerifierName.SYMPY,
                evidence=Evidence(
                    raw_output=raw_output + "\n(parent: could not parse runner output as JSON)",
                    exit_code=proc.returncode,
                ),
            )

        if not payload.get("ok"):
            return VerdictResult(
                verdict=Verdict.UNVERIFIED,
                verifier=VerifierName.SYMPY,
                evidence=Evidence(raw_output=raw_output, exit_code=proc.returncode),
            )

        verdict = Verdict.VERIFIED if payload["result"] else Verdict.REFUTED
        return VerdictResult(
            verdict=verdict,
            verifier=VerifierName.SYMPY,
            evidence=Evidence(raw_output=raw_output, exit_code=proc.returncode),
        )
