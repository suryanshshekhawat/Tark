import type { Step } from "../types";

export const CLASSIFICATION_LABEL: Record<Step["classification"], string> = {
  lean_candidate: "Lean Candidate",
  computational: "Computational",
  unformalizable: "Unformalizable",
  premise: "Premise",
};

export const STATUS_ICON: Record<Step["verdict"], string> = {
  VERIFIED: "✓",
  REFUTED: "✕",
  UNVERIFIED: "–",
  ASSUMED: "●",
};

function statementLabel(id: string): string {
  const match = id.match(/(\d+)/);
  return match ? `Statement ${match[1]}` : id;
}

export function StatementCard({
  step,
  pending = false,
  hideIcon = false,
  focused = false,
  onFocus,
}: {
  step: Step;
  /** True when this card is still a decomposition placeholder — Claude has
   * classified it but formalize/verify hasn't finished (or started) yet.
   * Distinct from a resolved step that simply has nothing to formalize
   * (premise/unformalizable) — those show as resolved immediately. */
  pending?: boolean;
  hideIcon?: boolean;
  focused?: boolean;
  onFocus?: (id: string) => void;
}) {
  const code = step.formalization?.lean_code || step.formalization?.python_code || null;
  const stdout = step.evidence?.raw_output || null;
  const hasEvidence = code !== null || stdout !== null;
  const attempts = step.formalization?.attempts ?? 0;
  const showAttempts = attempts > 1 && step.verdict !== "VERIFIED";

  return (
    <div
      id={`statement-${step.id}`}
      className={`statement-card verdict-${step.verdict.toLowerCase()}${pending ? " pending" : ""}${focused ? " focused" : ""}`}
      onMouseEnter={onFocus ? () => onFocus(step.id) : undefined}
      onClick={onFocus ? () => onFocus(step.id) : undefined}
    >
      <div className="statement-card-head">
        {!hideIcon && (
          <span
            className={`statement-status-icon ${pending ? "status-pending" : `status-${step.verdict.toLowerCase()}`}`}
          >
            {pending ? "" : STATUS_ICON[step.verdict]}
          </span>
        )}
        <span className="statement-label">{statementLabel(step.id)}</span>
        <span className="statement-tag">{CLASSIFICATION_LABEL[step.classification]}</span>
        {pending && <span className="statement-pending-label">Checking…</span>}
        {showAttempts && <span className="statement-attempts">{attempts} attempts</span>}
        {step.depends_on.length > 0 && (
          <span className="statement-deps">depends on {step.depends_on.join(", ")}</span>
        )}
      </div>

      <p className="statement-text">{step.statement}</p>

      {hasEvidence && (
        <div className="statement-evidence-grid">
          <div className="statement-evidence-pane">
            <div className="statement-evidence-label">Code</div>
            <pre>{code}</pre>
          </div>
          <div className="statement-evidence-pane">
            <div className="statement-evidence-label">stdout</div>
            <pre>{stdout}</pre>
          </div>
        </div>
      )}

      {step.claude_notes.length > 0 && (
        <div className="claude-notes">
          {step.claude_notes.map((note, i) => (
            <div key={i} className="claude-note" title="Unverified opinion">
              {note.text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
