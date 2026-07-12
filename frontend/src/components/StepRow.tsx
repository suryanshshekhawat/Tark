import type { Step } from "../types";

const VERDICT_LABEL: Record<Step["verdict"], string> = {
  VERIFIED: "Verified",
  REFUTED: "Refuted",
  UNVERIFIED: "Unverified",
};

export function StepRow({
  step,
  expanded,
  onFocus,
}: {
  step: Step;
  expanded: boolean;
  onFocus: (id: string) => void;
}) {
  return (
    <div
      id={`row-${step.id}`}
      className={`step-row verdict-${step.verdict.toLowerCase()}${expanded ? " expanded" : ""}`}
      onMouseEnter={() => onFocus(step.id)}
      onClick={() => onFocus(step.id)}
    >
      <div className="step-row-head">
        <span className="step-row-id">{step.id}</span>
        <span className="step-row-verdict">{VERDICT_LABEL[step.verdict]}</span>
        {step.depends_on.length > 0 && (
          <span className="step-row-deps">{step.depends_on.join(", ")}</span>
        )}
      </div>

      {expanded && (
        <div className="step-row-body">
          <p>{step.statement}</p>

          {step.evidence && (
            <details onClick={(e) => e.stopPropagation()}>
              <summary>Evidence</summary>
              <pre>{step.evidence.raw_output}</pre>
            </details>
          )}

          {step.claude_notes.length > 0 && (
            <div className="claude-notes">
              {step.claude_notes.map((note, i) => (
                <div key={i} className="claude-note">
                  {note.text}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
