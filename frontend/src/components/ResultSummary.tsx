import { buildReportMarkdown, downloadTextFile } from "../report";
import type { Report } from "../types";

const STATUS_LABEL: Record<Report["overall_status"], string> = {
  FULLY_VERIFIED: "FULLY VERIFIED",
  PARTIALLY_VERIFIED: "PARTIALLY VERIFIED",
  REFUTED_SOMEWHERE: "REFUTED",
};

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

/** The short, on-screen result summary — 2-4 lines, not the full breakdown.
 * Everything else (statement-by-statement evidence, full Claude notes, the
 * original proof) lives in the downloadable report instead. */
export function ResultSummary({ report, latex }: { report: Report; latex: string }) {
  function handleDownload() {
    const markdown = buildReportMarkdown(latex, report);
    downloadTextFile("tark-verification-report.md", markdown, "text/markdown");
  }

  return (
    <div
      className={`result-summary status-${report.overall_status.toLowerCase()}`}
      title="Verified = checked by Lean 4 or executable computation, not AI judgment."
    >
      <div className="result-summary-status">{STATUS_LABEL[report.overall_status]}</div>
      <div className="result-summary-line">
        {report.steps_verified}/{report.steps_total} statements verified formally
        {report.steps_assumed > 0 && ` · ${report.steps_assumed} assumed`}
      </div>
      {report.claude_global_notes.length > 0 && (
        <div className="result-summary-line result-summary-note">
          {truncate(report.claude_global_notes[0], 140)}
        </div>
      )}
      <button className="download-report-btn" onClick={handleDownload}>
        Download Verification Report
      </button>
    </div>
  );
}
