import type { Step } from "../types";

const VERDICT_LABEL: Record<Step["verdict"], string> = {
  VERIFIED: "VERIFIED",
  REFUTED: "REFUTED",
  UNVERIFIED: "UNVERIFIED",
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

      {step.evidence && (
        <details className="evidence">
          <summary>Raw verifier evidence</summary>
          <pre>{step.evidence.raw_output}</pre>
        </details>
      )}

      {step.claude_notes.length > 0 && (
        <div className="claude-notes">
          <div className="claude-notes-label">Claude's notes (unverified opinion)</div>
          {step.claude_notes.map((note, i) => (
            <div key={i} className={`claude-note claude-note-${note.type}`}>
              {note.text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
