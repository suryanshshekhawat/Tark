"""Pydantic models for the backend<->frontend JSON contract.

Mirrors CONSTRUCTION_PLAN.md §7 exactly. This schema is the contract between
backend and frontend, built first so both sides can be developed in parallel.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Classification(str, Enum):
    LEAN_CANDIDATE = "lean_candidate"
    COMPUTATIONAL = "computational"
    UNFORMALIZABLE = "unformalizable"
    # A premise/setup step ("let p, q be given", "suppose for contradiction") —
    # not a claim to check at all, distinct from UNFORMALIZABLE (a claim we
    # couldn't formalize). This is a structural judgment ("is this a claim or
    # a stipulation?"), not a correctness judgment — it never produces a
    # VERIFIED-like result. See CLAUDE.md.
    PREMISE = "premise"


class Verdict(str, Enum):
    VERIFIED = "VERIFIED"
    REFUTED = "REFUTED"
    UNVERIFIED = "UNVERIFIED"
    # Given/stipulated, not a claim — never assigned by Lean/SymPy and never
    # rendered as green. Distinct from UNVERIFIED, which means "this needed
    # checking and we couldn't". Only ever assigned to PREMISE-classified steps.
    ASSUMED = "ASSUMED"


class VerifierName(str, Enum):
    LEAN = "lean"
    SYMPY = "sympy"


class OverallStatus(str, Enum):
    FULLY_VERIFIED = "FULLY_VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    REFUTED_SOMEWHERE = "REFUTED_SOMEWHERE"


class ErrorType(str, Enum):
    UNBALANCED_ENVIRONMENT = "unbalanced_environment"
    EMPTY_INPUT = "empty_input"
    NO_MATH_CONTENT = "no_math_content"
    UNRECOVERABLE_STRUCTURE = "unrecoverable_structure"


class SourceSpan(BaseModel):
    start: int
    end: int
    anchor_text: Optional[str] = None


class Formalization(BaseModel):
    lean_code: Optional[str] = None
    attempts: int = 0
    python_code: Optional[str] = None


class Evidence(BaseModel):
    raw_output: str = ""
    exit_code: Optional[int] = None


class ClaudeNoteType(str, Enum):
    SUSPICION = "suspicion"
    STYLE = "style"


class ClaudeNote(BaseModel):
    type: ClaudeNoteType
    text: str


class Step(BaseModel):
    id: str
    statement: str
    source_span: SourceSpan
    depends_on: list[str] = Field(default_factory=list)
    classification: Classification
    formalization: Optional[Formalization] = None
    verdict: Verdict = Verdict.UNVERIFIED
    verifier: Optional[VerifierName] = None
    evidence: Optional[Evidence] = None
    claude_notes: list[ClaudeNote] = Field(default_factory=list)


class Report(BaseModel):
    overall_status: OverallStatus
    steps_verified: int
    steps_total: int
    steps_assumed: int = 0
    normalized_source: str
    steps: list[Step]
    claude_global_notes: list[str] = Field(default_factory=list)


class AutoRepair(BaseModel):
    issue: str
    action: str
    confidence: str


class Location(BaseModel):
    line: int
    char_offset: int


class IngestError(BaseModel):
    error_type: ErrorType
    message: str
    location: Optional[Location] = None
    auto_repairs_attempted: list[AutoRepair] = Field(default_factory=list)


class VerifyRequest(BaseModel):
    latex: str
