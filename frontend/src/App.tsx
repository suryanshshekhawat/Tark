import { useState } from "react";
import "./App.css";
import { streamVerify } from "./api";
import { StepCard } from "./components/StepCard";
import { SummaryHeader } from "./components/SummaryHeader";
import type { AutoRepair, IngestError, Report, Step } from "./types";

const EXAMPLE_PROOF = String.raw`Suppose, for contradiction, that $\sqrt{2}$ is rational. Then
$\sqrt{2} = p/q$ for some integers $p, q$ with $\gcd(p, q) = 1$.
Squaring both sides gives $p^2 = 2q^2$, so $p^2$ is even, so $p$ is even.
Write $p = 2k$. Then $4k^2 = 2q^2$, so $q^2 = 2k^2$, so $q$ is also even.
But this contradicts $\gcd(p, q) = 1$. Hence $\sqrt{2}$ is irrational.`;

type Status = "idle" | "streaming" | "error" | "done";

function App() {
  const [latex, setLatex] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [steps, setSteps] = useState<Step[]>([]);
  const [autoRepairs, setAutoRepairs] = useState<AutoRepair[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [ingestError, setIngestError] = useState<IngestError | null>(null);

  async function handleVerify() {
    setStatus("streaming");
    setSteps([]);
    setAutoRepairs([]);
    setReport(null);
    setIngestError(null);

    try {
      await streamVerify(latex, {
        onAutoRepair: (repair) => setAutoRepairs((prev) => [...prev, repair]),
        onStep: (step) => setSteps((prev) => [...prev, step]),
        onDone: (rep) => {
          setReport(rep);
          setStatus("done");
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
        <p className="tagline">Claude proposes. Verifiers dispose.</p>
      </header>

      <section className="input-screen">
        <textarea
          placeholder="Paste a LaTeX proof (not plain text — LaTeX only)."
          value={latex}
          onChange={(e) => setLatex(e.target.value)}
          rows={10}
        />
        <div className="input-actions">
          <button onClick={handleVerify} disabled={status === "streaming" || !latex.trim()}>
            {status === "streaming" ? "Verifying..." : "Verify"}
          </button>
          <button className="secondary" onClick={() => setLatex(EXAMPLE_PROOF)}>
            Load example (√2 irrational)
          </button>
        </div>
      </section>

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

      {autoRepairs.length > 0 && (
        <section className="auto-repairs">
          {autoRepairs.map((r, i) => (
            <div key={i} className="auto-repair">
              Auto-repaired: {r.issue} — {r.action} (confidence: {r.confidence})
            </div>
          ))}
        </section>
      )}

      {report && <SummaryHeader report={report} />}

      {steps.length > 0 && (
        <section className="report-view">
          {steps.map((step) => (
            <StepCard key={step.id} step={step} />
          ))}
        </section>
      )}

      {report && report.claude_global_notes.length > 0 && (
        <section className="claude-global-notes">
          <div className="claude-notes-label">Claude's global notes (unverified opinion)</div>
          {report.claude_global_notes.map((note, i) => (
            <div key={i} className="claude-note claude-note-suspicion">
              {note}
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

export default App;
