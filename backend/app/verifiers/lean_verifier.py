"""Lean 4 verifier backend — CONSTRUCTION_PLAN.md §8.

Writes a Lean snippet to a temp file inside the warm `tark_lean/` project and
invokes `lake env lean <file>.lean` against it as a subprocess. Never trusts
Claude-generated code with more than a hard timeout and a scratch directory.
"""
from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

from ..models.schema import Evidence, Verdict, VerifierName
from .base import Verifier, VerdictResult

# tark_lean/ is the warm, pre-built Lean project the backend writes into.
LEAN_PROJECT_DIR = Path(__file__).resolve().parents[3] / "tark_lean"
SCRATCH_DIR = LEAN_PROJECT_DIR / ".tark_scratch"

DEFAULT_TIMEOUT = 90.0  # seconds — see notes below for why this is above §8.2's 20-30s suggestion

# `import Mathlib` (the whole library) takes 50s+ per cold subprocess even
# with the prebuilt .olean cache — it blows the timeout above. Formalization
# prompts (Days 3-5) must ask Claude for targeted imports, e.g.
# `import Mathlib.Data.Nat.GCD.Basic`, not the whole-library import.
#
# Even a targeted import took ~20s on a cold OS file cache and ~11s once
# warm (measured against tark_lean/ on a OneDrive-synced path on Windows).
# The gap is disk I/O for the .olean dependency chain, not elaboration —
# expect the first check after a backend restart to be noticeably slower
# than subsequent ones.
#
# §8.2 suggests 20-30s; this is intentionally higher, and was raised a
# second time in a later session. Measured directly:
# `import Mathlib.Analysis.Real.Sqrt` alone (proved by testing it against a
# *trivial* goal, isolating import cost from proof cost) takes ~25s warm on
# this environment. `import Mathlib.FieldTheory.Finite.Basic` (needed for
# ZMod-field facts — self-inverse/unique-inverse patterns, and transitively
# `Mathlib.NumberTheory.Wilson`) is far heavier: measured at 58s warm and
# 3m10s when the OS file cache was under memory pressure (0.6GB free RAM at
# the time — see CLAUDE.md's concurrency/memory note; this is the same
# failure mode, just from a different heavy import than Real.sqrt). A short
# cap makes every step using these imports time out regardless of whether
# the formalization is correct — that isn't "genuinely too hard to verify",
# it's "the timeout is shorter than baseline import cost." Raised from 45s
# to 90s to give these steps a realistic chance under normal (non-memory-
# starved) conditions; still not enough under severe memory pressure, which
# needs a different fix (free memory / lower _LEAN_CONCURRENCY_LIMIT), not
# an ever-larger timeout — see real_pipeline.py.


def _kill_process_tree(pid: int) -> None:
    """`lake env lean` spawns `lean.exe` as a child rather than exec'ing
    into it, and Windows doesn't kill process trees on its own — a plain
    proc.kill() on timeout leaves `lean.exe` running indefinitely, still
    holding CPU/memory. `taskkill /T` kills the whole tree.
    """
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
        )
    else:
        import os
        import signal

        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


def _classify_failure(stdout: str, stderr: str) -> Verdict:
    """Almost every Lean compiler failure in an LLM-generated-tactic setting
    is a proof-engineering bug (wrong lemma, unsolved goal, bad import),
    not evidence the theorem statement is false — "type mismatch" in
    particular fires just as often when a *true* statement is proved with
    the wrong lemma as it would for a false one (observed directly: a true
    statement misclassified REFUTED because Claude cited a lemma with a
    mismatched shape). Lean does not hand us a reliable "this claim is
    false" signal the way a direct SymPy computation does, so this always
    returns UNVERIFIED — a false REFUTED (telling a user their true step is
    wrong) is worse than an UNVERIFIED that just means "couldn't confirm".
    REFUTED for Lean is intentionally unreachable in v1; only §9's SymPy
    verifier (a direct False result) produces it.
    """
    return Verdict.UNVERIFIED


class LeanVerifier(Verifier):
    def check(self, code: str, timeout: float = DEFAULT_TIMEOUT) -> VerdictResult:
        SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
        file_path = SCRATCH_DIR / f"check_{uuid.uuid4().hex}.lean"
        file_path.write_text(code, encoding="utf-8")

        proc = subprocess.Popen(
            ["lake", "env", "lean", str(file_path)],
            cwd=str(LEAN_PROJECT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            # Without an explicit encoding, Popen falls back to the OS
            # locale encoding — cp1252 on Windows, which can't decode the
            # Unicode math notation Lean/Mathlib output is full of (⊢, ¬,
            # ∀, ≠, ...). That silently crashed the internal reader thread
            # mid-read on every such check, truncating stdout/stderr right
            # where the corrupting character appeared. errors="replace" is
            # a defensive fallback, not the primary fix — Lean's output is
            # UTF-8.
            encoding="utf-8",
            errors="replace",
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc.pid)
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""
            # Windows Popen.communicate() has been observed to return None
            # (not "") for a stream after the process was killed externally
            # via taskkill rather than proc.kill() — coerce defensively.
            stdout, stderr = stdout or "", stderr or ""
            return VerdictResult(
                verdict=Verdict.UNVERIFIED,
                verifier=VerifierName.LEAN,
                evidence=Evidence(
                    raw_output=f"Lean check timed out after {timeout}s.\n"
                    f"stdout so far:\n{stdout}\nstderr so far:\n{stderr}",
                    exit_code=None,
                ),
            )
        finally:
            file_path.unlink(missing_ok=True)

        stdout, stderr = stdout or "", stderr or ""
        combined_output = (stdout + stderr).lower()
        uses_sorry = "uses" in combined_output and "sorry" in combined_output
        if proc.returncode == 0 and uses_sorry:
            # Lean treats `sorry` as a warning, not an error — exit code 0.
            # An incomplete proof must never read as VERIFIED (§11).
            verdict = Verdict.UNVERIFIED
        elif proc.returncode == 0:
            verdict = Verdict.VERIFIED
        else:
            verdict = _classify_failure(stdout, stderr)

        return VerdictResult(
            verdict=verdict,
            verifier=VerifierName.LEAN,
            evidence=Evidence(
                raw_output=f"$ lake env lean {file_path.name}\n"
                f"exit code: {proc.returncode}\n"
                f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}",
                exit_code=proc.returncode,
            ),
        )
