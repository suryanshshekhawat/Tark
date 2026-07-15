"""LaTeX input validation pipeline — CONSTRUCTION_PLAN.md §4a.

Runs before any Claude call. Structural check -> normalization -> soft-fail
auto-repair -> hard-fail with a located, specific error.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models.schema import AutoRepair, ErrorType, IngestError, Location

_MATH_ENV_RE = re.compile(r"\\begin\{(align|equation|gather|multline|eqnarray)\*?\}")
_MATH_CONTENT_RE = re.compile(r"\$|\\\[|\\\(")
_ENV_RE = re.compile(r"\\begin\{([^}]*)\}|\\end\{([^}]*)\}")


@dataclass
class ValidationResult:
    normalized_source: str | None = None
    error: IngestError | None = None
    auto_repairs: list[AutoRepair] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None


def _line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def strip_preamble_with_offset(text: str) -> tuple[str, int]:
    """Like _strip_preamble, but also returns the char offset into `text`
    where the returned (stripped) body begins — i.e. text[offset:offset+len(body)] == body.
    Shared with rendering/latex_compiler.py so the PDF-compile step and the
    decomposition pipeline agree on exactly where "the body" starts; drift
    between the two would misalign every SyncTeX box lookup by however much
    they disagreed on stripped leading whitespace.
    """
    begin_match = re.search(r"\\begin\{document\}", text)
    end_match = re.search(r"\\end\{document\}", text)
    if begin_match and end_match and end_match.start() > begin_match.end():
        raw_body = text[begin_match.end():end_match.start()]
        lstrip_len = len(raw_body) - len(raw_body.lstrip())
        return raw_body.strip(), begin_match.end() + lstrip_len
    lstrip_len = len(text) - len(text.lstrip())
    return text.strip(), lstrip_len


def _strip_preamble(text: str) -> str:
    """Strip everything outside \\begin{document}...\\end{document}, if present."""
    body, _ = strip_preamble_with_offset(text)
    return body


def _check_balanced_braces(text: str) -> tuple[bool, int | None]:
    depth = 0
    escaped = False
    for i, ch in enumerate(text):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False, i
    if depth > 0:
        return False, len(text)
    return True, None


def _check_balanced_environments(text: str) -> tuple[bool, str | None, int | None]:
    stack: list[tuple[str, int]] = []
    for m in _ENV_RE.finditer(text):
        if m.group(1) is not None:
            stack.append((m.group(1), m.start()))
        else:
            env = m.group(2)
            if not stack:
                return False, f"\\end{{{env}}} with no matching \\begin{{{env}}}", m.start()
            top_env, top_offset = stack.pop()
            if top_env != env:
                return (
                    False,
                    f"\\begin{{{top_env}}} is closed by mismatched \\end{{{env}}}",
                    top_offset,
                )
    if stack:
        env, offset = stack[-1]
        return False, f"\\begin{{{env}}} has no matching \\end{{{env}}}", offset
    return True, None, None


def _has_math_content(text: str) -> bool:
    return bool(_MATH_CONTENT_RE.search(text) or _MATH_ENV_RE.search(text))


def _try_repair_unbalanced_dollars(text: str) -> tuple[str, AutoRepair | None]:
    """Odd count of unescaped, non-$$ '$' -> soft-repair by closing at EOF."""
    positions = []
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "$":
            positions.append(i)
        i += 1
    if len(positions) % 2 == 1:
        repaired = text + "$"
        return repaired, AutoRepair(
            issue=f"unmatched $ at offset {positions[-1]}",
            action="auto-closed with a trailing $",
            confidence="medium",
        )
    return text, None


class LatexValidator:
    """Stage 1 of the pipeline (CONSTRUCTION_PLAN.md §6.1)."""

    def validate(self, raw: str) -> ValidationResult:
        if raw is None or not raw.strip():
            return ValidationResult(
                error=IngestError(error_type=ErrorType.EMPTY_INPUT, message="Input is empty.")
            )

        normalized = _strip_preamble(raw)

        if not _has_math_content(normalized):
            return ValidationResult(
                error=IngestError(
                    error_type=ErrorType.NO_MATH_CONTENT,
                    message=(
                        "Input contains no math content ($...$, \\[...\\], or a math "
                        "environment) — this doesn't look like a LaTeX proof."
                    ),
                )
            )

        balanced, bad_offset = _check_balanced_braces(normalized)
        if not balanced:
            line = _line_for_offset(normalized, bad_offset)
            return ValidationResult(
                error=IngestError(
                    error_type=ErrorType.UNBALANCED_ENVIRONMENT,
                    message=(
                        f"Unbalanced braces at line {line} (offset {bad_offset}) — a '}}' "
                        "closes a brace that was never opened, or a '{' is never closed."
                    ),
                    location=Location(line=line, char_offset=bad_offset),
                )
            )

        env_ok, env_msg, env_offset = _check_balanced_environments(normalized)
        if not env_ok:
            line = _line_for_offset(normalized, env_offset)
            return ValidationResult(
                error=IngestError(
                    error_type=ErrorType.UNBALANCED_ENVIRONMENT,
                    message=f"{env_msg} (line {line}, offset {env_offset}).",
                    location=Location(line=line, char_offset=env_offset),
                )
            )

        auto_repairs: list[AutoRepair] = []
        normalized, repair = _try_repair_unbalanced_dollars(normalized)
        if repair:
            auto_repairs.append(repair)

        return ValidationResult(normalized_source=normalized, auto_repairs=auto_repairs)
