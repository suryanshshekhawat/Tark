import { CLASSIFICATION_LABEL, STATUS_ICON } from "./components/StatementCard";
import type { Report, Step } from "./types";

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
