import { useEffect, useRef } from "react";
import { STATUS_ICON, StatementCard } from "./StatementCard";
import type { DecompositionSummary, Step, Verdict } from "../types";

function lineClass(step: Step, resolved: boolean): string {
  if (!resolved) return "pending";
  if (step.verdict === "REFUTED") return "verdict-refuted";
  if (step.verdict === "UNVERIFIED") return "verdict-unverified";
  return "verdict-verified"; // VERIFIED | ASSUMED
}

/**
 * Renders the decomposed proof statements as a vertical timeline — a rail of
 * connecting lines and per-statement dots showing what's resolved and what's
 * still in flight, the same visual language whether verification is still
 * streaming ("live" mode: dots fill in live, a spinner marks anything still
 * pending) or has already finished ("final" mode: every dot is already
 * final, top node reads "Verification complete" immediately instead of the
 * live decomposition/countdown text).
 */
export function StatementList({
  steps,
  decomposition,
  resolvedIds,
  mode,
  focusedStepId = null,
  focusOrigin = null,
  onFocus,
  onRetry,
  retryingIds = new Set(),
  attemptHistory,
}: {
  steps: Step[];
  decomposition: DecompositionSummary | null;
  resolvedIds: Set<string>;
  mode: "live" | "final";
  focusedStepId?: string | null;
  focusOrigin?: "source" | "sidebar" | null;
  onFocus?: (id: string) => void;
  onRetry?: (id: string) => void;
  retryingIds?: Set<string>;
  attemptHistory?: Map<string, Verdict[]>;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (focusOrigin !== "source" || !focusedStepId) return;
    const el = containerRef.current?.querySelector(`#statement-${focusedStepId}`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusedStepId, focusOrigin]);

  const isFinal = mode === "final";
  const resolvedCount = isFinal ? steps.length : steps.filter((s) => resolvedIds.has(s.id)).length;

  return (
    <div className="statement-list statement-timeline" ref={containerRef}>
      <div className="timeline-node">
        <div className="timeline-rail">
          <span className={`timeline-icon ${decomposition ? "status-verified" : "spinner"}`}>
            {decomposition ? "✓" : ""}
          </span>
          <span className="timeline-line verdict-verified" />
        </div>
        <div className="timeline-content">
          {isFinal ? (
            <div className="decomposition-status">✓ Verification complete</div>
          ) : !decomposition ? (
            <>
              <div className="decomposition-status">Decomposing Proof into Statements …</div>
              <ul className="decomposition-process-trail">
                <li>Parsing the compiled LaTeX source</li>
                <li>Calling Claude to split it into individually-checkable statements</li>
                <li>
                  Classifying each one — lean_candidate / computational / premise / unformalizable
                </li>
                <li>Locating each statement's exact source span for highlighting</li>
              </ul>
            </>
          ) : (
            <>
              <div className="decomposition-status">
                Proof breaks down into {decomposition.total} statement
                {decomposition.total === 1 ? "" : "s"}
              </div>
              <div className="decomposition-breakdown">
                {decomposition.assumptions} assumption{decomposition.assumptions === 1 ? "" : "s"},{" "}
                {decomposition.verifiable} verifiable statement
                {decomposition.verifiable === 1 ? "" : "s"}, {decomposition.computational}{" "}
                computational claim{decomposition.computational === 1 ? "" : "s"}.
              </div>
              <div className="decomposition-progress">
                {resolvedCount} / {decomposition.total} checked
              </div>
            </>
          )}
        </div>
      </div>

      {steps.map((step, i) => {
        const resolved = isFinal || resolvedIds.has(step.id);
        return (
          <div className="timeline-node" key={step.id}>
            <div className="timeline-rail">
              <span
                className={`timeline-icon ${resolved ? `status-${step.verdict.toLowerCase()}` : "spinner"}`}
              >
                {resolved ? STATUS_ICON[step.verdict] : ""}
              </span>
              {i < steps.length - 1 && (
                <span className={`timeline-line ${lineClass(step, resolved)}`} />
              )}
            </div>
            <div className="timeline-content">
              <StatementCard
                step={step}
                pending={!resolved}
                hideIcon
                focused={focusedStepId === step.id}
                onFocus={onFocus}
                onRetry={onRetry}
                retrying={retryingIds.has(step.id)}
                attemptHistory={attemptHistory?.get(step.id)}
              />
            </div>
          </div>
        );
      })}

      {!isFinal && decomposition && resolvedCount === decomposition.total && (
        <div className="timeline-node">
          <div className="timeline-rail">
            <span className="timeline-icon status-verified">✓</span>
          </div>
          <div className="timeline-content">
            <div className="decomposition-status">Verification complete</div>
          </div>
        </div>
      )}
    </div>
  );
}
