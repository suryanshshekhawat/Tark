import { useEffect, useRef } from "react";
import { STATUS_ICON, StatementCard } from "./StatementCard";
import type { DecompositionSummary, Step } from "../types";

function lineClass(step: Step, resolved: boolean): string {
  if (!resolved) return "pending";
  if (step.verdict === "REFUTED") return "verdict-refuted";
  if (step.verdict === "UNVERIFIED") return "verdict-unverified";
  return "verdict-verified"; // VERIFIED | ASSUMED
}

/**
 * Renders the decomposed proof statements.
 * "live" mode: a vertical timeline with connecting lines, a decomposition
 * summary node (real total from `decomposition`, known immediately — not
 * inferred from how many steps have merely finished so far), a live
 * checked-count, and a per-statement pending state for anything Claude has
 * classified but not yet formalized/verified — used while streaming.
 * "final" mode: a flat stacked list, no connectors, a "Verification
 * complete" header — used once the report has fully arrived.
 */
export function StatementList({
  steps,
  decomposition,
  resolvedIds,
  mode,
  focusedStepId = null,
  focusOrigin = null,
  onFocus,
}: {
  steps: Step[];
  decomposition: DecompositionSummary | null;
  resolvedIds: Set<string>;
  mode: "live" | "final";
  focusedStepId?: string | null;
  focusOrigin?: "source" | "sidebar" | null;
  onFocus?: (id: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (focusOrigin !== "source" || !focusedStepId) return;
    const el = containerRef.current?.querySelector(`#statement-${focusedStepId}`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusedStepId, focusOrigin]);

  if (mode === "final") {
    return (
      <div className="statement-list statement-list-final" ref={containerRef}>
        <div className="verification-complete">✓ Verification complete</div>
        {steps.map((step) => (
          <StatementCard
            key={step.id}
            step={step}
            focused={focusedStepId === step.id}
            onFocus={onFocus}
          />
        ))}
      </div>
    );
  }

  const resolvedCount = steps.filter((s) => resolvedIds.has(s.id)).length;

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
          {!decomposition ? (
            <div className="decomposition-status">Decomposing Proof into Statements …</div>
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
        const resolved = resolvedIds.has(step.id);
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
              />
            </div>
          </div>
        );
      })}

      {decomposition && resolvedCount === decomposition.total && (
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
