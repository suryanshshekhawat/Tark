import type { Report } from "../types";

const STATUS_LABEL: Record<Report["overall_status"], string> = {
  FULLY_VERIFIED: "FULLY VERIFIED",
  PARTIALLY_VERIFIED: "PARTIALLY VERIFIED",
  REFUTED_SOMEWHERE: "REFUTED",
};

export function SummaryHeader({ report }: { report: Report }) {
  return (
    <div className={`summary-header status-${report.overall_status.toLowerCase()}`}>
      <div className="summary-status">{STATUS_LABEL[report.overall_status]}</div>
      <div className="summary-count">
        {report.steps_verified}/{report.steps_total} steps verified
      </div>
      <p className="summary-disclaimer">
        Verified steps are checked by the Lean 4 theorem prover or by executable
        computation — not by the AI's judgment.
      </p>
    </div>
  );
}
