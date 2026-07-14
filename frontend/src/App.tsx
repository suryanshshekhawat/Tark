import { useMemo, useState } from "react";
import "./App.css";
import { streamVerify } from "./api";
import { LatexPreview } from "./components/LatexPreview";
import { SourcePane } from "./components/SourcePane";
import { StepCard } from "./components/StepCard";
import { StepSidebar } from "./components/StepSidebar";
import { SummaryHeader } from "./components/SummaryHeader";
import type { AutoRepair, IngestError, Report, Step } from "./types";

const EXAMPLES: { label: string; latex: string }[] = [
  {
    label: "√2 irrational",
    latex: String.raw`Suppose, for contradiction, that $\sqrt{2}$ is rational. Then
$\sqrt{2} = p/q$ for some integers $p, q$ with $\gcd(p, q) = 1$.
Squaring both sides gives $p^2 = 2q^2$, so $p^2$ is even, so $p$ is even.
Write $p = 2k$. Then $4k^2 = 2q^2$, so $q^2 = 2k^2$, so $q$ is also even.
But this contradicts $\gcd(p, q) = 1$. Hence $\sqrt{2}$ is irrational.`,
  },
  {
    label: "gcd & primality",
    latex: String.raw`We compute that $\gcd(48, 18) = 6$. Also, $1000003$ is prime. However, $\gcd(100, 45) = 10$.`,
  },
  {
    label: "even squares",
    latex: String.raw`Let $n$ be an even integer, so $n = 2k$ for some integer $k$. Then $n^2 = 4k^2 = 2(2k^2)$, so $n^2$ is even.`,
  },
];

type Stage = "input" | "preview" | "result";
type Status = "idle" | "streaming" | "error" | "done";
type ViewMode = "list" | "source";
type FocusOrigin = "source" | "sidebar" | null;

function stepSortKey(id: string): [string, number] {
  const match = id.match(/^(\D*)(\d+)$/);
  if (match) return [match[1], parseInt(match[2], 10)];
  return [id, 0];
}

function sortSteps(steps: Step[]): Step[] {
  return [...steps].sort((a, b) => {
    const [aPrefix, aNum] = stepSortKey(a.id);
    const [bPrefix, bNum] = stepSortKey(b.id);
    return aPrefix === bPrefix ? aNum - bNum : aPrefix.localeCompare(bPrefix);
  });
}

function App() {
  const [latex, setLatex] = useState("");
  const [stage, setStage] = useState<Stage>("input");
  const [status, setStatus] = useState<Status>("idle");
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [steps, setSteps] = useState<Step[]>([]);
  const [autoRepairs, setAutoRepairs] = useState<AutoRepair[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [ingestError, setIngestError] = useState<IngestError | null>(null);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [focusedStepId, setFocusedStepId] = useState<string | null>(null);
  const [focusOrigin, setFocusOrigin] = useState<FocusOrigin>(null);

  const sortedSteps = useMemo(() => sortSteps(steps), [steps]);

  function focusFromSource(id: string) {
    setFocusedStepId(id);
    setFocusOrigin("source");
  }

  function focusFromSidebar(id: string) {
    setFocusedStepId(id);
    setFocusOrigin("sidebar");
  }

  async function handleVerify() {
    setStage("result");
    setStatus("streaming");
    setSteps([]);
    setAutoRepairs([]);
    setReport(null);
    setIngestError(null);
    setPipelineError(null);
    setViewMode("list");
    setFocusedStepId(null);

    try {
      await streamVerify(latex, {
        onAutoRepair: (repair) => setAutoRepairs((prev) => [...prev, repair]),
        onStep: (step) => setSteps((prev) => [...prev, step]),
        onDone: (rep) => {
          setReport(rep);
          setStatus("done");
        },
        onPipelineError: (message) => {
          setPipelineError(message);
          setStatus("error");
        },
      });
    } catch (err) {
      if (err && typeof err === "object" && "error_type" in err) {
        setIngestError(err as IngestError);
      } else {
        setIngestError({
          error_type: "unrecoverable_structure",
          message: err instanceof Error ? err.message : "Unknown error while verifying.",
          location: null,
          auto_repairs_attempted: [],
        });
      }
      setStatus("error");
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Tark</h1>
      </header>

      {stage === "input" && (
        <section className="input-screen">
          <textarea
            placeholder="Paste a LaTeX proof"
            value={latex}
            onChange={(e) => setLatex(e.target.value)}
            rows={10}
          />
          <div className="input-actions">
            <button onClick={() => setStage("preview")} disabled={!latex.trim()}>
              Preview
            </button>
            {EXAMPLES.map((ex) => (
              <button key={ex.label} className="secondary" onClick={() => setLatex(ex.latex)}>
                {ex.label}
              </button>
            ))}
          </div>
        </section>
      )}

      {stage === "preview" && (
        <LatexPreview
          latex={latex}
          onEdit={() => setStage("input")}
          onConfirm={handleVerify}
        />
      )}

      {stage === "result" && (
        <>
          {ingestError && (
            <section className="ingest-error">
              <div className="ingest-error-type">{ingestError.error_type}</div>
              <p>{ingestError.message}</p>
              {ingestError.location && (
                <p className="ingest-error-location">
                  line {ingestError.location.line}, offset {ingestError.location.char_offset}
                </p>
              )}
            </section>
          )}

          {pipelineError && (
            <section className="ingest-error">
              <p>{pipelineError}</p>
            </section>
          )}

          {autoRepairs.length > 0 && (
            <section className="auto-repairs">
              {autoRepairs.map((r, i) => (
                <div key={i} className="auto-repair">
                  Auto-repaired: {r.issue} — {r.action}
                </div>
              ))}
            </section>
          )}

          {report && (
            <div className="result-header">
              <SummaryHeader report={report} />
              <div className="view-toggle">
                <button
                  className={viewMode === "list" ? "active" : ""}
                  onClick={() => setViewMode("list")}
                >
                  List
                </button>
                <button
                  className={viewMode === "source" ? "active" : ""}
                  onClick={() => setViewMode("source")}
                >
                  Source
                </button>
              </div>
            </div>
          )}

          {status === "streaming" && !report && <p className="status-line">Verifying…</p>}

          {viewMode === "list" && sortedSteps.length > 0 && (
            <section className="report-view">
              {sortedSteps.map((step) => (
                <StepCard key={step.id} step={step} />
              ))}
            </section>
          )}

          {viewMode === "source" && report && (
            <section className="split-view">
              <SourcePane
                normalizedSource={report.normalized_source}
                steps={report.steps}
                focusedStepId={focusedStepId}
                focusOrigin={focusOrigin}
                onFocus={focusFromSource}
              />
              <StepSidebar
                steps={sortSteps(report.steps)}
                focusedStepId={focusedStepId}
                focusOrigin={focusOrigin}
                onFocus={focusFromSidebar}
              />
            </section>
          )}

          {report && report.claude_global_notes.length > 0 && (
            <section className="claude-global-notes" title="Unverified opinion — not a verifier result">
              {report.claude_global_notes.map((note, i) => (
                <div key={i} className="claude-note">
                  {note}
                </div>
              ))}
            </section>
          )}

          {(status === "done" || status === "error") && (
            <button className="secondary restart-button" onClick={() => setStage("input")}>
              New proof
            </button>
          )}
        </>
      )}
    </div>
  );
}

export default App;
