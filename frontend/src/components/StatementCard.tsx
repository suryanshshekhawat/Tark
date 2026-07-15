import { useLayoutEffect, useRef, useState } from "react";
import type { Classification, Step, Verdict } from "../types";

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

// Steps of this classification actually go through formalize+verify (with a
// repair loop) — the attempt dots and retry button only make sense for them.
// PREMISE/UNFORMALIZABLE resolve instantly with nothing to attempt or retry.
const ATTEMPTABLE: Classification[] = ["lean_candidate", "computational"];

// What's actually happening server-side for a still-pending step, by
// classification — there's no per-substep SSE event, so this is a static
// description of the pipeline stages that step is somewhere inside of, not a
// live per-stage tracker.
const PROCESS_TRAIL: Record<string, string> = {
  lean_candidate:
    "Formalizing into Lean 4 → checking against Mathlib (up to 3 attempts, auto-repairing the proof term between attempts on a recoverable failure)",
  computational:
    "Translating into a Python snippet → evaluating it in a sandboxed SymPy execution",
};

const DOT_COUNT = 5;
type DotColor = "grey" | "red" | "green";

// Fallback for a resolved step we have no live attempt history for (e.g. a
// page that skipped the live run) — derives the same red.../green/grey
// pattern from just the final attempt count + verdict, all at once instead
// of progressively.
function attemptDotsFromFinal(step: Step): DotColor[] {
  const attempts = Math.min(step.formalization?.attempts ?? 0, DOT_COUNT);
  const verified = step.verdict === "VERIFIED";
  const red = verified ? Math.max(attempts - 1, 0) : attempts;
  const green = verified ? 1 : 0;
  const dots: DotColor[] = [];
  for (let i = 0; i < DOT_COUNT; i++) {
    if (i < red) dots.push("red");
    else if (i < red + green) dots.push("green");
    else dots.push("grey");
  }
  return dots;
}

function AttemptDots({
  step,
  resolved,
  history,
}: {
  step: Step;
  resolved: boolean;
  /** Verdict of each attempt so far, in order, as `step_attempt` SSE events
   * arrive live — lets a dot turn red the moment that attempt fails, rather
   * than only learning the whole history at once when the step resolves. */
  history?: Verdict[];
}) {
  let dots: DotColor[];
  if (history && history.length > 0) {
    dots = [];
    for (let i = 0; i < DOT_COUNT; i++) {
      dots.push(i < history.length ? (history[i] === "VERIFIED" ? "green" : "red") : "grey");
    }
  } else if (resolved) {
    dots = attemptDotsFromFinal(step);
  } else {
    dots = Array(DOT_COUNT).fill("grey");
  }
  return (
    <span className="attempt-dots" title="Attempt history: grey = unused, red = failed attempt, green = verified">
      {dots.map((color, i) => (
        <span key={i} className={`attempt-dot attempt-dot-${color}`} />
      ))}
    </span>
  );
}

function CollapsiblePane({ label, content }: { label: string; content: string }) {
  const [expanded, setExpanded] = useState(false);
  // Whether this pane's own content overflows the shared collapsed height —
  // measured against the DOM, not guessed from string length, so Code and
  // stdout always collapse to the exact same height as each other (a
  // length/line-count heuristic judged them independently and could collapse
  // one but not the other, which is what looked inconsistent card-to-card).
  const [overflowing, setOverflowing] = useState(false);
  const preRef = useRef<HTMLPreElement>(null);

  useLayoutEffect(() => {
    // Only re-measure while collapsed — once expanded, the element's own
    // clientHeight grows to match scrollHeight, which would zero this out
    // and hide the "Show less" button right when it's needed.
    if (expanded) return;
    const el = preRef.current;
    if (!el) return;
    setOverflowing(el.scrollHeight > el.clientHeight + 1);
  }, [content, expanded]);

  return (
    <div className="statement-evidence-pane">
      <div className="statement-evidence-label">{label}</div>
      <pre ref={preRef} className={!expanded ? "evidence-collapsed" : undefined}>
        {content}
      </pre>
      {overflowing && (
        <button
          type="button"
          className="evidence-toggle"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded((v) => !v);
          }}
        >
          {expanded ? "Show less" : "Read more"}
        </button>
      )}
    </div>
  );
}

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
  onRetry,
  retrying = false,
  attemptHistory,
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
  onRetry?: (id: string) => void;
  retrying?: boolean;
  attemptHistory?: Verdict[];
}) {
  const code = step.formalization?.lean_code || step.formalization?.python_code || null;
  const stdout = step.evidence?.raw_output || null;
  const hasEvidence = code !== null || stdout !== null;
  const attempts = step.formalization?.attempts ?? 0;
  const showAttempts = attempts > 1 && step.verdict !== "VERIFIED";
  const attemptable = ATTEMPTABLE.includes(step.classification);
  const failed = step.verdict === "REFUTED" || step.verdict === "UNVERIFIED";
  const showRetry = attemptable && failed && !pending && !retrying && onRetry;
  const isPending = pending || retrying;

  return (
    <div
      id={`statement-${step.id}`}
      className={`statement-card verdict-${step.verdict.toLowerCase()}${isPending ? " pending" : ""}${focused ? " focused" : ""}`}
      onMouseEnter={onFocus ? () => onFocus(step.id) : undefined}
      onClick={onFocus ? () => onFocus(step.id) : undefined}
    >
      <div className="statement-card-head">
        {!hideIcon && (
          <span
            className={`statement-status-icon ${isPending ? "status-pending" : `status-${step.verdict.toLowerCase()}`}`}
          >
            {isPending ? "" : STATUS_ICON[step.verdict]}
          </span>
        )}
        <span className="statement-label">{statementLabel(step.id)}</span>
        <span className="statement-tag">{CLASSIFICATION_LABEL[step.classification]}</span>
        {attemptable && <AttemptDots step={step} resolved={!isPending} history={attemptHistory} />}
        {isPending && (
          <span className="statement-pending-label">{retrying ? "Retrying…" : "Checking…"}</span>
        )}
        {showAttempts && <span className="statement-attempts">{attempts} attempts</span>}
        {step.depends_on.length > 0 && (
          <span className="statement-deps">depends on {step.depends_on.join(", ")}</span>
        )}
        {showRetry && (
          <button
            type="button"
            className="statement-retry-btn"
            title="Rerun formalize + verify for this statement"
            onClick={(e) => {
              e.stopPropagation();
              onRetry(step.id);
            }}
          >
            ↻ Retry
          </button>
        )}
      </div>

      <p className="statement-text">{step.statement}</p>

      {isPending && attemptable && !hasEvidence && (
        <p className="statement-process-trail">{PROCESS_TRAIL[step.classification]}</p>
      )}

      {hasEvidence && (
        <div className="statement-evidence-grid">
          {code !== null && <CollapsiblePane label="Code" content={code} />}
          {stdout !== null && <CollapsiblePane label="stdout" content={stdout} />}
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
