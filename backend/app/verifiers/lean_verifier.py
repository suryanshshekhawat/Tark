"""Lean 4 verifier backend — CONSTRUCTION_PLAN.md §8.

Writes a Lean snippet to a temp file inside the warm `tark_lean/` project and
invokes `lake env lean <file>.lean` against it as a subprocess. Never trusts
Claude-generated code with more than a hard timeout and a scratch directory.
"""
from __future__ import annotations

import subprocess
import tempfile
import uuid
from pathlib import Path

from ..models.schema import Evidence, Verdict, VerifierName
from .base import Verifier, VerdictResult

# tark_lean/ is the warm, pre-built Lean project the backend writes into.
LEAN_PROJECT_DIR = Path(__file__).resolve().parents[3] / "tark_lean"
SCRATCH_DIR = LEAN_PROJECT_DIR / ".tark_scratch"

DEFAULT_TIMEOUT = 30.0  # seconds — §8.2: 20-30s hard timeout (upper bound; see notes below)

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


class LeanTimeoutError(Exception):
    pass


def _classify_failure(stdout: str, stderr: str) -> Verdict:
    """Distinguish a genuine mathematical rejection from a syntax/tactic
    failure so the repair loop (§8.3) knows whether to retry or give up.

    Lean reports both as nonzero exit + "error:" lines, so this is a
    best-effort heuristic on the message text — the caller (pipeline repair
    loop) is what actually decides whether to retry, not this function. This
    function only ever returns REFUTED or UNVERIFIED, never VERIFIED.
    """
    combined = (stdout + stderr).lower()
    # `sorry` means an incomplete proof, not a rejection of the claim. Match
    # loosely on "uses" + "sorry" rather than the exact quote glyph Lean uses
    # around the identifier, since that has changed between Lean versions.
    if "uses" in combined and "sorry" in combined:
        return Verdict.UNVERIFIED
    # A type mismatch on the theorem statement itself (not tactic syntax)
    # is the closest signal we get to "Lean rejected the mathematical claim".
    if "type mismatch" in combined and "tactic" not in combined:
        return Verdict.REFUTED
    return Verdict.UNVERIFIED


class LeanVerifier(Verifier):
    def check(self, code: str, timeout: float = DEFAULT_TIMEOUT) -> VerdictResult:
        SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
        file_path = SCRATCH_DIR / f"check_{uuid.uuid4().hex}.lean"
        file_path.write_text(code, encoding="utf-8")

        try:
            proc = subprocess.run(
                ["lake", "env", "lean", str(file_path)],
                cwd=str(LEAN_PROJECT_DIR),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return VerdictResult(
                verdict=Verdict.UNVERIFIED,
                verifier=VerifierName.LEAN,
                evidence=Evidence(
                    raw_output=f"Lean check timed out after {timeout}s.\n"
                    f"stdout so far:\n{exc.stdout or ''}\nstderr so far:\n{exc.stderr or ''}",
                    exit_code=None,
                ),
            )
        finally:
            file_path.unlink(missing_ok=True)

        combined_output = (proc.stdout + proc.stderr).lower()
        uses_sorry = "uses" in combined_output and "sorry" in combined_output
        if proc.returncode == 0 and uses_sorry:
            # Lean treats `sorry` as a warning, not an error — exit code 0.
            # An incomplete proof must never read as VERIFIED (§11).
            verdict = Verdict.UNVERIFIED
        elif proc.returncode == 0:
            verdict = Verdict.VERIFIED
        else:
            verdict = _classify_failure(proc.stdout, proc.stderr)

        return VerdictResult(
            verdict=verdict,
            verifier=VerifierName.LEAN,
            evidence=Evidence(
                raw_output=f"$ lake env lean {file_path.name}\n"
                f"exit code: {proc.returncode}\n"
                f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}",
                exit_code=proc.returncode,
            ),
        )
