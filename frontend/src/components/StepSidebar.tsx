import { useEffect, useRef } from "react";
import { StepRow } from "./StepRow";
import type { Step } from "../types";

export function StepSidebar({
  steps,
  focusedStepId,
  focusOrigin,
  onFocus,
}: {
  steps: Step[];
  focusedStepId: string | null;
  focusOrigin: "source" | "sidebar" | null;
  onFocus: (id: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (focusOrigin !== "source" || !focusedStepId) return;
    const el = containerRef.current?.querySelector(`#row-${focusedStepId}`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusedStepId, focusOrigin]);

  return (
    <div className="step-sidebar" ref={containerRef}>
      {steps.map((step) => (
        <StepRow
          key={step.id}
          step={step}
          expanded={focusedStepId === step.id}
          onFocus={onFocus}
        />
      ))}
    </div>
  );
}
