import type {
  AutoRepair,
  CompileError,
  CompileResult,
  DecompositionSummary,
  IngestError,
  Report,
  Step,
  StepAttempt,
} from "./types";

/** POST /api/compile — real LaTeX -> PDF compilation. Throws the parsed
 * CompileError on a 422 (a genuine pdflatex failure, distinct from the
 * ingest-validation 422 /api/verify can return). */
export async function compileLatex(latex: string): Promise<CompileResult> {
  const res = await fetch("/api/compile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ latex }),
  });
  if (res.status === 422) {
    throw (await res.json()) as CompileError;
  }
  if (!res.ok) {
    throw new Error(`Unexpected response: ${res.status}`);
  }
  return (await res.json()) as CompileResult;
}

export function compiledPdfUrl(docId: string): string {
  return `/api/compile/${docId}/pdf`;
}

/**
 * Reads a text/event-stream fetch() response body and calls `dispatch` for
 * every "event: X\ndata: Y\n\n" frame. EventSource can't send a POST body,
 * so both /api/verify and /api/verify/retry hand-roll SSE framing over a
 * streamed fetch() response instead — this is the shared parsing loop both
 * of them drive through their own dispatch callback.
 */
async function consumeSSE(
  res: Response,
  dispatch: (eventName: string, payload: unknown) => void,
): Promise<void> {
  if (!res.body) {
    throw new Error(`Unexpected response: ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sepIndex: number;
    while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, sepIndex);
      buffer = buffer.slice(sepIndex + 2);

      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of rawEvent.split("\n")) {
        if (line.startsWith("event:")) {
          eventName = line.slice("event:".length).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice("data:".length).trim());
        }
      }
      if (dataLines.length === 0) continue;
      dispatch(eventName, JSON.parse(dataLines.join("\n")));
    }
  }
}

export type VerifyStreamHandlers = {
  onAutoRepair?: (repair: AutoRepair) => void;
  onDecomposition?: (summary: DecompositionSummary) => void;
  onAttempt?: (attempt: StepAttempt) => void;
  onStep?: (step: Step) => void;
  onDone?: (report: Report) => void;
  onPipelineError?: (message: string) => void;
};

/** POST /api/verify and stream decomposition/attempt/step/done events. */
export async function streamVerify(
  latex: string,
  handlers: VerifyStreamHandlers,
): Promise<void> {
  const res = await fetch("/api/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ latex }),
  });

  if (res.status === 422) {
    const error = (await res.json()) as IngestError;
    throw error;
  }
  if (!res.ok) {
    throw new Error(`Unexpected response: ${res.status}`);
  }

  await consumeSSE(res, (eventName, payload) => {
    switch (eventName) {
      case "auto_repair":
        handlers.onAutoRepair?.(payload as AutoRepair);
        break;
      case "decomposition":
        handlers.onDecomposition?.(payload as DecompositionSummary);
        break;
      case "step_attempt":
        handlers.onAttempt?.(payload as StepAttempt);
        break;
      case "step":
        handlers.onStep?.(payload as Step);
        break;
      case "done":
        handlers.onDone?.(payload as Report);
        break;
      case "pipeline_error":
        handlers.onPipelineError?.((payload as { message: string }).message);
        break;
    }
  });
}

export type RetryStreamHandlers = {
  onAttempt?: (attempt: StepAttempt) => void;
  onStep?: (step: Step) => void;
};

/** POST /api/verify/retry — re-run formalize+verify for one already-
 * decomposed step (a UI "retry" click), not the whole proof. Streams the
 * same step_attempt/step events as streamVerify, just scoped to one step,
 * so attempt progress shows up live instead of only at the end. */
export async function streamRetryStep(step: Step, handlers: RetryStreamHandlers): Promise<void> {
  const res = await fetch("/api/verify/retry", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(step),
  });
  if (!res.ok) {
    throw new Error(`Unexpected response: ${res.status}`);
  }

  await consumeSSE(res, (eventName, payload) => {
    switch (eventName) {
      case "step_attempt":
        handlers.onAttempt?.(payload as StepAttempt);
        break;
      case "step":
        handlers.onStep?.(payload as Step);
        break;
    }
  });
}
