import type { AutoRepair, IngestError, Report, Step } from "./types";

export type VerifyStreamHandlers = {
  onAutoRepair?: (repair: AutoRepair) => void;
  onStep?: (step: Step) => void;
  onDone?: (report: Report) => void;
};

/**
 * POST /api/verify and parse the text/event-stream response.
 *
 * EventSource can't send a POST body, so this hand-rolls the SSE framing
 * ("event: X\ndata: Y\n\n") over a streamed fetch() response instead.
 */
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
  if (!res.ok || !res.body) {
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
      dispatchEvent(rawEvent, handlers);
    }
  }
}

function dispatchEvent(rawEvent: string, handlers: VerifyStreamHandlers): void {
  let eventName = "message";
  const dataLines: string[] = [];
  for (const line of rawEvent.split("\n")) {
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  }
  if (dataLines.length === 0) return;
  const payload = JSON.parse(dataLines.join("\n"));

  switch (eventName) {
    case "auto_repair":
      handlers.onAutoRepair?.(payload as AutoRepair);
      break;
    case "step":
      handlers.onStep?.(payload as Step);
      break;
    case "done":
      handlers.onDone?.(payload as Report);
      break;
  }
}
