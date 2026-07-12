import { useEffect, useMemo, useRef } from "react";
import { buildSourceSegments, LatexPassage, type HighlightableStep } from "../latex/latexRender";

export function SourcePane({
  normalizedSource,
  steps,
  focusedStepId,
  focusOrigin,
  onFocus,
}: {
  normalizedSource: string;
  steps: HighlightableStep[];
  focusedStepId: string | null;
  focusOrigin: "source" | "sidebar" | null;
  onFocus: (id: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const segments = useMemo(
    () => buildSourceSegments(normalizedSource, steps),
    [normalizedSource, steps],
  );

  useEffect(() => {
    if (focusOrigin !== "sidebar" || !focusedStepId) return;
    const el = containerRef.current?.querySelector(`[data-step-id="${focusedStepId}"]`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusedStepId, focusOrigin]);

  return (
    <div className="paper source-pane" ref={containerRef}>
      <div className="paper-text">
        <LatexPassage
          segments={segments}
          activeStepId={focusedStepId}
          onStepEnter={onFocus}
          onStepClick={onFocus}
        />
      </div>
    </div>
  );
}
