import type { Step } from "../types";

const VERDICT_LABEL: Record<Step["verdict"], string> = {
  VERIFIED: "VERIFIED",
  REFUTED: "REFUTED",
  UNVERIFIED: "UNVERIFIED",
  ASSUMED: "ASSUMED",
};

export function StepCard({ step }: { step: Step }) {
  const verifierSuffix = step.verifier ? ` (${step.verifier})` : "";

  return (
    <div className={`step-card verdict-${step.verdict.toLowerCase()}`}>
      <div className="step-card-header">
        <span className="step-id">{step.id}</span>
        <span className={`verdict-badge verdict-badge-${step.verdict.toLowerCase()}`}>
          {VERDICT_LABEL[step.verdict]}
          {verifierSuffix}
        </span>
        {step.depends_on.length > 0 && (
          <span className="depends-on">
            depends on {step.depends_on.join(", ")}
          </span>
        )}
      </div>

      <p className="step-statement">{step.statement}</p>

      <span className="classification-chip">{step.classification}</span>

      {(step.formalization?.lean_code || step.formalization?.python_code || step.evidence) && (
        <details className="evidence">
          <summary>Evidence</summary>
          {(step.formalization?.lean_code || step.formalization?.python_code) && (
            <>
              <div className="evidence-label">Code checked</div>
              <pre>{step.formalization.lean_code || step.formalization.python_code}</pre>
            </>
          )}
          {step.evidence && (
            <>
              <div className="evidence-label">Output</div>
              <pre>{step.evidence.raw_output}</pre>
            </>
          )}
        </details>
      )}

      {step.claude_notes.length > 0 && (
        <div className="claude-notes">
          {step.claude_notes.map((note, i) => (
            <div key={i} className={`claude-note claude-note-${note.type}`} title="Unverified opinion">
              {note.text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
