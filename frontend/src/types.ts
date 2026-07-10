// Mirrors backend/app/models/schema.py — CONSTRUCTION_PLAN.md §7.
// This is the contract; keep the two in sync by hand until there's a
// codegen step worth adding.

export type Classification = "lean_candidate" | "computational" | "unformalizable";

export type Verdict = "VERIFIED" | "REFUTED" | "UNVERIFIED";

export type VerifierName = "lean" | "sympy";

export type OverallStatus = "FULLY_VERIFIED" | "PARTIALLY_VERIFIED" | "REFUTED_SOMEWHERE";

export type ErrorType =
  | "unbalanced_environment"
  | "empty_input"
  | "no_math_content"
  | "unrecoverable_structure";

export interface SourceSpan {
  start: number;
  end: number;
  anchor_text: string | null;
}

export interface Formalization {
  lean_code: string | null;
  attempts: number;
  python_code: string | null;
}

export interface Evidence {
  raw_output: string;
  exit_code: number | null;
}

export interface ClaudeNote {
  type: "suspicion" | "style";
  text: string;
}

export interface Step {
  id: string;
  statement: string;
  source_span: SourceSpan;
  depends_on: string[];
  classification: Classification;
  formalization: Formalization | null;
  verdict: Verdict;
  verifier: VerifierName | null;
  evidence: Evidence | null;
  claude_notes: ClaudeNote[];
}

export interface Report {
  overall_status: OverallStatus;
  steps_verified: number;
  steps_total: number;
  normalized_source: string;
  steps: Step[];
  claude_global_notes: string[];
}

export interface AutoRepair {
  issue: string;
  action: string;
  confidence: string;
}

export interface Location {
  line: number;
  char_offset: number;
}

export interface IngestError {
  error_type: ErrorType;
  message: string;
  location: Location | null;
  auto_repairs_attempted: AutoRepair[];
}
