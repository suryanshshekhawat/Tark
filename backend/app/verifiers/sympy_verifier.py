"""SymPy / computational verifier backend — CONSTRUCTION_PLAN.md §9.

Claude-generated snippets are untrusted. They run in a fresh subprocess (not
`eval()` in-process), with restricted builtins and no filesystem/network
access, under a short timeout. The convention: the snippet must set a
variable named `result` to True/False — that's the entire verdict surface.
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

# Runs in a *separate* interpreter process. Restricted builtins block
# filesystem/network/process access; only a small safe subset plus sympy
# is reachable. Emits a single JSON line to stdout: the only channel the
# parent trusts.
_RUNNER_TEMPLATE = r"""
import json
import sys

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
    if "result" not in namespace:
        print(json.dumps({"ok": False, "error": "snippet did not set a `result` variable"}))
        return
    result = namespace["result"]
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
