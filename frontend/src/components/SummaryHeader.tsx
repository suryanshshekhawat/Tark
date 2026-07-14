import type { Report } from "../types";

const STATUS_LABEL: Record<Report["overall_status"], string> = {
  FULLY_VERIFIED: "FULLY VERIFIED",
  PARTIALLY_VERIFIED: "PARTIALLY VERIFIED",
  REFUTED_SOMEWHERE: "REFUTED",
};

export function SummaryHeader({ report }: { report: Report }) {
  return (
    <div
      className={`summary-header status-${report.overall_status.toLowerCase()}`}
      title="Verified = checked by Lean 4 or executable computation, not AI judgment."
    >
      <div className="summary-status">{STATUS_LABEL[report.overall_status]}</div>
      <div className="summary-count">
        {report.steps_verified}/{report.steps_total} verified
        {report.steps_assumed > 0 && ` · ${report.steps_assumed} assumed`}
      </div>
    </div>
  );
}
