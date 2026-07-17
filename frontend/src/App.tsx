import { useMemo, useRef, useState } from "react";
import "./App.css";
import { compiledPdfUrl, compileLatex, streamRetryStep, streamVerify } from "./api";
import { PdfPaperViewer } from "./components/PdfPaperViewer";
import { ResultSummary } from "./components/ResultSummary";
import { StatementList } from "./components/StatementList";
import { TopBar } from "./components/TopBar";
import { TypingWordmark } from "./components/TypingWordmark";
import { recomputeReportTally } from "./report";
import type {
  AutoRepair,
  CompileError,
  DecompositionSummary,
  IngestError,
  Report,
  Step,
  StepAttempt,
  Verdict,
} from "./types";

const MAX_LATEX_LENGTH = 10000;

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

type Stage = "landing" | "preview" | "result";
type Status = "idle" | "streaming" | "error" | "done";
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
  const [stage, setStage] = useState<Stage>("landing");
  const [status, setStatus] = useState<Status>("idle");
  const [inputError, setInputError] = useState<string | null>(null);
  const [compiling, setCompiling] = useState(false);
  const [compileError, setCompileError] = useState<CompileError | null>(null);
  const [pdfDocId, setPdfDocId] = useState<string | null>(null);
  const [decomposition, setDecomposition] = useState<DecompositionSummary | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [resolvedIds, setResolvedIds] = useState<Set<string>>(new Set());
  const [autoRepairs, setAutoRepairs] = useState<AutoRepair[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [ingestError, setIngestError] = useState<IngestError | null>(null);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [focusedStepId, setFocusedStepId] = useState<string | null>(null);
  const [focusOrigin, setFocusOrigin] = useState<FocusOrigin>(null);
  const [retryingIds, setRetryingIds] = useState<Set<string>>(new Set());
  // Per-step live attempt history — verdict of each attempt so far, in
  // order, filled in as `step_attempt` events arrive across the step's whole
  // lifetime (the initial run *and* every subsequent retry, not reset back
  // to empty each time). Distinct from `formalization.attempts` on Step,
  // which is just the last run's count with no per-attempt outcomes.
  const [attemptHistory, setAttemptHistory] = useState<Map<string, Verdict[]>>(new Map());
  // The backend numbers attempts 1..N *within* whichever run produced them —
  // a retry's own attempt 1 is unrelated to the original run's attempt 1.
  // This tracks, per step, how many attempts were already recorded before
  // the run currently in flight started, so a retry's events land *after*
  // the existing history instead of overwriting it at the same array index
  // (which was the bug: dots looked "stuck at 3" no matter how many times a
  // step was retried, because each retry's attempt-1..3 kept clobbering the
  // same three slots instead of continuing on). A plain ref, not state — it
  // isn't itself rendered, only used to compute where recordAttempt writes.
  const attemptOffsetRef = useRef<Map<string, number>>(new Map());

  const sortedSteps = useMemo(() => sortSteps(steps), [steps]);

  function recordAttempt(a: StepAttempt) {
    setAttemptHistory((prev) => {
      const next = new Map(prev);
      const offset = attemptOffsetRef.current.get(a.step_id) ?? 0;
      const arr = [...(next.get(a.step_id) ?? [])];
      arr[offset + a.attempt - 1] = a.verdict;
      next.set(a.step_id, arr);
      return next;
    });
  }

  function focusFromSource(id: string) {
    setFocusedStepId(id);
    setFocusOrigin("source");
  }

  function focusFromList(id: string) {
    setFocusedStepId(id);
    setFocusOrigin("sidebar");
  }

  async function handlePreview() {
    if (!latex.trim() || latex.length > MAX_LATEX_LENGTH) {
      setInputError("Please ensure your Latex file is complete and compiles ....");
      return;
    }
    setInputError(null);
    setCompileError(null);
    setCompiling(true);
    try {
      const result = await compileLatex(latex);
      setPdfDocId(result.doc_id);
      setStage("preview");
    } catch (err) {
      if (err && typeof err === "object" && "message" in err) {
        setCompileError(err as CompileError);
      } else {
        setCompileError({
          message: err instanceof Error ? err.message : "Failed to compile LaTeX.",
          log: "",
        });
      }
    } finally {
      setCompiling(false);
    }
  }

  async function handleVerify() {
    if (status === "streaming") return; // guard against duplicate/concurrent submissions
    setStage("result");
    setStatus("streaming");
    setDecomposition(null);
    setSteps([]);
    setResolvedIds(new Set());
    setAutoRepairs([]);
    setReport(null);
    setIngestError(null);
    setPipelineError(null);
    setFocusedStepId(null);
    setAttemptHistory(new Map());
    attemptOffsetRef.current = new Map();

    try {
      await streamVerify(latex, {
        onAutoRepair: (repair) => setAutoRepairs((prev) => [...prev, repair]),
        onDecomposition: (summary) => {
          setDecomposition(summary);
          setSteps(summary.steps);
        },
        onAttempt: recordAttempt,
        onStep: (step) => {
          setSteps((prev) => {
            const idx = prev.findIndex((s) => s.id === step.id);
            if (idx === -1) return [...prev, step];
            const next = [...prev];
            next[idx] = step;
            return next;
          });
          setResolvedIds((prev) => new Set(prev).add(step.id));
        },
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

  async function handleRetry(id: string) {
    const step = steps.find((s) => s.id === id);
    if (!step || retryingIds.has(id)) return;
    setRetryingIds((prev) => new Set(prev).add(id));
    // This retry's own attempt numbering starts back at 1 on the backend —
    // record how many attempts are already in this step's history so far,
    // so recordAttempt appends after them instead of overwriting from the
    // start (see attemptOffsetRef's comment above).
    attemptOffsetRef.current.set(id, attemptHistory.get(id)?.length ?? 0);

    let finalStep: Step | null = null;
    try {
      await streamRetryStep(step, {
        onAttempt: recordAttempt,
        onStep: (updated) => {
          finalStep = updated;
        },
      });
      if (finalStep) {
        const updated: Step = finalStep;
        const nextSteps = steps.map((s) => (s.id === id ? updated : s));
        setSteps(nextSteps);
        // If the report header is already showing (verification finished),
        // a retry that changes a verdict must be reflected there too — both
        // the per-step list inside `report` and the overall_status/counts
        // the header actually reads from.
        setReport((prev) =>
          prev
            ? {
                ...prev,
                steps: prev.steps.map((s) => (s.id === id ? updated : s)),
                ...recomputeReportTally(nextSteps),
              }
            : prev,
        );
      }
    } catch (err) {
      console.error("Retry failed:", err);
    } finally {
      setRetryingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }

  // Resolved (not still-pending) lean_candidate/computational steps whose
  // final verdict was REFUTED/UNVERIFIED — the same "did this fail and can
  // it be retried" test StatementCard uses per-card, computed once here so
  // a top-of-page "retry all failed" button knows whether to show up at all
  // without the user having to scroll down and check each card themselves.
  const failedAttemptableIds = useMemo(
    () =>
      sortedSteps
        .filter(
          (s) =>
            (s.verdict === "REFUTED" || s.verdict === "UNVERIFIED") &&
            (s.classification === "lean_candidate" || s.classification === "computational") &&
            resolvedIds.has(s.id),
        )
        .map((s) => s.id),
    [sortedSteps, resolvedIds],
  );

  async function handleRetryAll() {
    const idsToRetry = failedAttemptableIds.filter((id) => !retryingIds.has(id));
    await Promise.all(idsToRetry.map((id) => handleRetry(id)));
  }

  function handleBackToLanding() {
    setStage("landing");
  }

  function handleBackToPreview() {
    setStage("preview");
  }

  return (
    <div className="app">
      {stage === "landing" && (
        <>
          <TopBar showWordmark={false} />
          <section className="landing-screen">
            <div className="landing-inner">
              <TypingWordmark />
              <div className={`latex-input-row${inputError ? " has-error" : ""}`}>
                <textarea
                  className="latex-input"
                  placeholder="Paste Compilable Latex"
                  value={latex}
                  rows={1}
                  onChange={(e) => {
                    setLatex(e.target.value);
                    if (inputError) setInputError(null);
                  }}
                />
                <span className={`latex-input-count${inputError ? " has-error" : ""}`}>
                  {latex.length} / {MAX_LATEX_LENGTH}
                </span>
                <button className="preview-btn" onClick={handlePreview} disabled={compiling}>
                  {compiling ? "Compiling…" : "Preview"}
                </button>
              </div>
              {inputError && <p className="latex-input-error">{inputError}</p>}
              {compileError && (
                <div className="ingest-error compile-error">
                  <div className="ingest-error-type">LaTeX failed to compile</div>
                  <p>{compileError.message}</p>
                  {compileError.log && <pre className="compile-error-log">{compileError.log}</pre>}
                </div>
              )}

              <p className="landing-subtitle">
                Transparent Formal Verification and Computational Support for Mathematical Proofs
              </p>

              <div className="landing-examples">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex.label}
                    className="example-chip"
                    onClick={() => {
                      setLatex(ex.latex);
                      setInputError(null);
                    }}
                  >
                    {ex.label}
                  </button>
                ))}
              </div>
            </div>
          </section>
        </>
      )}

      {stage === "preview" && pdfDocId && (
        <>
          <TopBar onBack={handleBackToLanding} />
          <section className="split-screen">
            <PdfPaperViewer pdfUrl={compiledPdfUrl(pdfDocId)} />
            <div className="side-panel">
              <p className="side-copy">
                If the compiled version of Latex looks good, you can go ahead and verify, this is
                because we accept alternate inputs as well and intend to be sure that the content
                being fed to the system is accurate.
              </p>
              <button className="verify-btn" onClick={handleVerify}>
                Looks allright - Verify
              </button>
            </div>
          </section>
        </>
      )}

      {stage === "result" && pdfDocId && (
        <>
          <TopBar onBack={handleBackToPreview} />
          <section className="split-screen">
            <PdfPaperViewer
              pdfUrl={compiledPdfUrl(pdfDocId)}
              normalizedSource={decomposition?.normalized_source}
              steps={sortedSteps}
              resolvedIds={status === "streaming" ? resolvedIds : undefined}
              focusedStepId={focusedStepId}
              focusOrigin={focusOrigin}
              onFocus={focusFromSource}
            />
            <div className="side-panel">
              {failedAttemptableIds.length > 0 && !ingestError && !pipelineError && (
                <button
                  type="button"
                  className="retry-all-btn"
                  onClick={handleRetryAll}
                  disabled={failedAttemptableIds.every((id) => retryingIds.has(id))}
                >
                  ↻ Retry all failed ({failedAttemptableIds.length})
                </button>
              )}

              {ingestError && (
                <div className="ingest-error">
                  <div className="ingest-error-type">{ingestError.error_type}</div>
                  <p>{ingestError.message}</p>
                  {ingestError.location && (
                    <p className="ingest-error-location">
                      line {ingestError.location.line}, offset {ingestError.location.char_offset}
                    </p>
                  )}
                </div>
              )}

              {pipelineError && (
                <div className="ingest-error">
                  <p>{pipelineError}</p>
                </div>
              )}

              {autoRepairs.length > 0 && (
                <div className="auto-repairs">
                  {autoRepairs.map((r, i) => (
                    <div key={i} className="auto-repair">
                      Auto-repaired: {r.issue} — {r.action}
                    </div>
                  ))}
                </div>
              )}

              {status === "done" && report && <ResultSummary report={report} latex={latex} />}

              {(status === "streaming" || status === "done") && !ingestError && !pipelineError && (
                <StatementList
                  steps={sortedSteps}
                  decomposition={decomposition}
                  resolvedIds={resolvedIds}
                  mode={status === "done" ? "final" : "live"}
                  focusedStepId={focusedStepId}
                  focusOrigin={focusOrigin}
                  onFocus={focusFromList}
                  onRetry={handleRetry}
                  retryingIds={retryingIds}
                  attemptHistory={attemptHistory}
                />
              )}

              {(status === "done" || status === "error") && (
                <button className="new-proof-btn" onClick={handleBackToLanding}>
                  New proof
                </button>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

export default App;
