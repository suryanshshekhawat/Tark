import katex from "katex";
import type { ReactNode } from "react";

interface MathToken {
  type: "text" | "math";
  content: string;
  display: boolean;
}

// $$...$$ | $...$ (skipping \$ ) | \[...\] | \(...\)
const MATH_TOKEN_REGEX =
  /\$\$([\s\S]+?)\$\$|\$((?:\\.|[^$\\])+)\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)/g;

function tokenize(text: string): MathToken[] {
  const tokens: MathToken[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  const re = new RegExp(MATH_TOKEN_REGEX);
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      tokens.push({ type: "text", content: text.slice(lastIndex, match.index), display: false });
    }
    if (match[1] !== undefined) {
      tokens.push({ type: "math", content: match[1], display: true });
    } else if (match[2] !== undefined) {
      tokens.push({ type: "math", content: match[2], display: false });
    } else if (match[3] !== undefined) {
      tokens.push({ type: "math", content: match[3], display: true });
    } else if (match[4] !== undefined) {
      tokens.push({ type: "math", content: match[4], display: false });
    }
    lastIndex = re.lastIndex;
  }
  if (lastIndex < text.length) {
    tokens.push({ type: "text", content: text.slice(lastIndex), display: false });
  }
  return tokens;
}

function renderMathHtml(latex: string, display: boolean): string {
  try {
    return katex.renderToString(latex, { throwOnError: false, displayMode: display, strict: "ignore" });
  } catch {
    return latex.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
}

/** Renders a plain string (prose + inline/display math) as React nodes. */
export function renderLatexText(text: string, keyPrefix: string): ReactNode[] {
  return tokenize(text).map((tok, i) =>
    tok.type === "math" ? (
      <span
        key={`${keyPrefix}-${i}`}
        className="katex-inline"
        // katex.renderToString with throwOnError:false and trust:false (the
        // default) never emits attacker-controlled HTML/script — the math
        // source can't break out of KaTeX's own markup.
        dangerouslySetInnerHTML={{ __html: renderMathHtml(tok.content, tok.display) }}
      />
    ) : (
      <span key={`${keyPrefix}-${i}`}>{tok.content}</span>
    ),
  );
}

export type Verdict = "VERIFIED" | "REFUTED" | "UNVERIFIED" | "ASSUMED";
export type Classification = "lean_candidate" | "computational" | "unformalizable" | "premise";

export interface HighlightableStep {
  id: string;
  source_span: { start: number; end: number };
  verdict: Verdict;
  classification: Classification;
}

export interface SourceSegment {
  text: string;
  stepId: string | null;
  verdict: Verdict | null;
  classification: Classification | null;
}

/** Splits source into highlighted (per-step) and plain segments, in source
 * order. Zero-length spans (backend couldn't confidently locate the anchor)
 * are skipped — those steps just don't highlight, per §10a's fallback. */
export function buildSourceSegments(source: string, steps: HighlightableStep[]): SourceSegment[] {
  const spans = steps
    .filter((s) => s.source_span.end > s.source_span.start)
    .sort((a, b) => a.source_span.start - b.source_span.start);

  const segments: SourceSegment[] = [];
  let cursor = 0;

  for (const step of spans) {
    const { start, end } = step.source_span;
    if (start < cursor) continue; // overlapping span — first one wins
    if (start > cursor) {
      segments.push({ text: source.slice(cursor, start), stepId: null, verdict: null, classification: null });
    }
    segments.push({
      text: source.slice(start, end),
      stepId: step.id,
      verdict: step.verdict,
      classification: step.classification,
    });
    cursor = end;
  }
  if (cursor < source.length) {
    segments.push({ text: source.slice(cursor), stepId: null, verdict: null, classification: null });
  }
  return segments;
}

export function LatexPassage({
  segments,
  activeStepId,
  onStepEnter,
  onStepLeave,
  onStepClick,
}: {
  segments: SourceSegment[];
  activeStepId?: string | null;
  onStepEnter?: (id: string) => void;
  onStepLeave?: (id: string) => void;
  onStepClick?: (id: string) => void;
}) {
  return (
    <>
      {segments.map((seg, i) => {
        const content = renderLatexText(seg.text, `seg-${i}`);
        if (!seg.stepId) return <span key={i}>{content}</span>;

        const classes = [
          "source-highlight",
          `verdict-${seg.verdict?.toLowerCase()}`,
          seg.classification === "unformalizable" ? "unformalizable" : "",
          activeStepId === seg.stepId ? "active" : "",
        ]
          .filter(Boolean)
          .join(" ");

        return (
          <mark
            key={i}
            data-step-id={seg.stepId}
            className={classes}
            onMouseEnter={() => onStepEnter?.(seg.stepId!)}
            onMouseLeave={() => onStepLeave?.(seg.stepId!)}
            onClick={() => onStepClick?.(seg.stepId!)}
          >
            {content}
          </mark>
        );
      })}
    </>
  );
}
