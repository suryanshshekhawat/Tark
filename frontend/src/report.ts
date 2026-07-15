import { CLASSIFICATION_LABEL, STATUS_ICON } from "./components/StatementCard";
import type { OverallStatus, Report, Step } from "./types";

const STATUS_LABEL: Record<Report["overall_status"], string> = {
  FULLY_VERIFIED: "FULLY VERIFIED",
  PARTIALLY_VERIFIED: "PARTIALLY VERIFIED",
  REFUTED_SOMEWHERE: "REFUTED",
};

function stepSection(step: Step): string {
  const lines = [
    `### ${step.id} — ${STATUS_ICON[step.verdict]} ${step.verdict} — ${CLASSIFICATION_LABEL[step.classification]}`,
    "",
    step.statement,
  ];

  const code = step.formalization?.lean_code || step.formalization?.python_code || null;
  const stdout = step.evidence?.raw_output || null;
  if (code) {
    lines.push("", "**Code:**", "```", code.trim(), "```");
  }
  if (stdout) {
    lines.push("", "**Output:**", "```", stdout.trim(), "```");
  }
  if (step.claude_notes.length > 0) {
    lines.push("", "**Notes (unverified opinion):**");
    for (const note of step.claude_notes) lines.push(`- ${note.text}`);
  }
  return lines.join("\n");
}

/** Mirrors backend/app/pipeline/report.py::build_report's tallying exactly
 * (ASSUMED steps are premises, not obligations; a genuine REFUTED anywhere
 * wins over everything else) — used to refresh the header's overall_status
 * and counts client-side after a step is re-verified via a retry, without
 * re-running the whole-proof advisory pass (claude_global_notes are left as
 * they were; a single step's retry doesn't invalidate whole-proof notes). */
export function recomputeReportTally(
  steps: Step[],
): Pick<Report, "overall_status" | "steps_verified" | "steps_total" | "steps_assumed"> {
  const verified = steps.filter((s) => s.verdict === "VERIFIED").length;
  const assumed = steps.filter((s) => s.verdict === "ASSUMED").length;
  const refuted = steps.some((s) => s.verdict === "REFUTED");
  const checkable = steps.filter((s) => s.verdict !== "ASSUMED");

  let overall_status: OverallStatus;
  if (refuted) {
    overall_status = "REFUTED_SOMEWHERE";
  } else if (checkable.length > 0 && verified === checkable.length) {
    overall_status = "FULLY_VERIFIED";
  } else {
    overall_status = "PARTIALLY_VERIFIED";
  }

  return { overall_status, steps_verified: verified, steps_total: steps.length, steps_assumed: assumed };
}

/** Builds a self-contained Markdown report: the original proof as pasted,
 * plus the statement-by-statement breakdown — not every internal detail
 * (repair-attempt history, SSE/box data, timings), just what a reader needs
 * to check the verification themselves. */
export function buildReportMarkdown(originalLatex: string, report: Report): string {
  const sections = [
    "# Tark Verification Report",
    "",
    `**Status:** ${STATUS_LABEL[report.overall_status]} — ${report.steps_verified}/${report.steps_total} statements verified formally` +
      (report.steps_assumed > 0 ? ` (${report.steps_assumed} assumed)` : ""),
    "",
    "_Verified = checked by the Lean 4 theorem prover or by executable computation, not by AI judgment._",
    "",
    "## Original Proof",
    "",
    "```latex",
    originalLatex.trim(),
    "```",
    "",
    "## Statement Breakdown",
    "",
    ...report.steps.map(stepSection).flatMap((s) => [s, ""]),
  ];

  if (report.claude_global_notes.length > 0) {
    sections.push("## Claude's Notes (unverified opinion)", "");
    for (const note of report.claude_global_notes) sections.push(`- ${note}`);
    sections.push("");
  }

  return sections.join("\n");
}

export function downloadTextFile(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
