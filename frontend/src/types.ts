// Mirrors backend/app/models/schema.py — CONSTRUCTION_PLAN.md §7.
// This is the contract; keep the two in sync by hand until there's a
// codegen step worth adding.

export type Classification = "lean_candidate" | "computational" | "unformalizable" | "premise";

export type Verdict = "VERIFIED" | "REFUTED" | "UNVERIFIED" | "ASSUMED";

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

// Emitted once, right after decomposition (Claude call #1) finishes and
// before any formalize/verify work starts — the true total/breakdown and
// every step's id/statement/classification/source_span are already known
// at this point. `steps` here are placeholders for anything not yet checked
// (lean_candidate/computational); a later `step` event with the same id
// supersedes it once verification actually finishes. `normalized_source`
// lets the frontend start matching each step's source_span against the
// compiled PDF's text layer immediately — see src/textLayerMatch.ts.
export interface DecompositionSummary {
  total: number;
  assumptions: number;
  verifiable: number;
  computational: number;
  normalized_source: string;
  steps: Step[];
}

export interface Report {
  overall_status: OverallStatus;
  steps_verified: number;
  steps_total: number;
  steps_assumed: number;
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

export interface CompileResult {
  doc_id: string;
  page_count: number;
}

export interface CompileError {
  message: string;
  log: string;
}
