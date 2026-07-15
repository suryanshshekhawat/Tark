import * as pdfjsLib from "pdfjs-dist";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";
// eslint-disable-next-line import/no-unresolved -- Vite `?url` import, resolved at build time.
import workerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useMemo, useRef, useState } from "react";
import { computeStepBoxes, type TextBox } from "../textLayerMatch";
import type { Step } from "../types";

pdfjsLib.GlobalWorkerOptions.workerSrc = workerSrc;

const ZOOM_MIN = 0.5;
const ZOOM_MAX = 3;
const ZOOM_STEP = 0.25;

interface BoxEntry {
  stepId: string;
  verdict: Step["verdict"];
  classification: Step["classification"];
  pending: boolean;
  box: TextBox;
}

/** Real, page-by-page rendering of a compiled PDF (see
 * backend/app/rendering/) — replaces the old KaTeX-approximated paper.
 * Highlight geometry comes from matching each step's exact source text
 * against the PDF's own extracted text layer (textLayerMatch.ts), not an
 * approximation of compiler-internal box structure — see that file for why. */
export function PdfPaperViewer({
  pdfUrl,
  normalizedSource,
  steps,
  resolvedIds,
  focusedStepId = null,
  focusOrigin = null,
  onFocus,
}: {
  pdfUrl: string;
  normalizedSource?: string;
  steps?: Step[];
  /** When provided, a step whose id isn't in this set renders as a neutral
   * "still checking" highlight instead of its (not-yet-final) verdict
   * color. Omit once every step is resolved (e.g. the final flat-list view). */
  resolvedIds?: Set<string>;
  focusedStepId?: string | null;
  focusOrigin?: "source" | "sidebar" | null;
  onFocus?: (id: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pageWrapperRefs = useRef<(HTMLDivElement | null)[]>([]);
  const canvasRefs = useRef<(HTMLCanvasElement | null)[]>([]);
  const viewportsRef = useRef<ReturnType<PDFPageProxy["getViewport"]>[]>([]);
  const ratiosRef = useRef<Map<number, number>>(new Map());

  const [pdfDoc, setPdfDoc] = useState<PDFDocumentProxy | null>(null);
  const [pageCount, setPageCount] = useState(0);
  // null = not yet derived from the container's width; set once per document.
  const [baseScale, setBaseScale] = useState<number | null>(null);
  const [zoom, setZoom] = useState(1);
  const [currentPage, setCurrentPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stepBoxes, setStepBoxes] = useState<Map<string, TextBox[]>>(new Map());

  const scale = baseScale === null ? null : baseScale * zoom;

  // Stable signature that only changes when the *set of spans* changes, not
  // on every verdict update — box geometry only needs recomputing when
  // decomposition (re)happens, never on a verify result arriving.
  const spanSignature = useMemo(
    () => (steps ?? []).map((s) => `${s.id}:${s.source_span.start}-${s.source_span.end}`).join("|"),
    [steps],
  );

  const boxesByPage = useMemo(() => {
    const map = new Map<number, BoxEntry[]>();
    for (const step of steps ?? []) {
      const pending = resolvedIds ? !resolvedIds.has(step.id) : false;
      for (const box of stepBoxes.get(step.id) ?? []) {
        const list = map.get(box.page) ?? [];
        list.push({ stepId: step.id, verdict: step.verdict, classification: step.classification, pending, box });
        map.set(box.page, list);
      }
    }
    return map;
  }, [steps, resolvedIds, stepBoxes]);

  // Load the document and get page count.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPdfDoc(null);
    setPageCount(0);
    setBaseScale(null);
    setZoom(1);
    setStepBoxes(new Map());
    ratiosRef.current.clear();
    pageWrapperRefs.current = [];
    canvasRefs.current = [];
    viewportsRef.current = [];

    const loadingTask = pdfjsLib.getDocument({ url: pdfUrl });
    loadingTask.promise
      .then((pdf) => {
        if (cancelled) return;
        setPdfDoc(pdf);
        setPageCount(pdf.numPages);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load PDF.");
        setLoading(false);
      });

    return () => {
      cancelled = true;
      loadingTask.destroy();
    };
  }, [pdfUrl]);

  // First pass per document: derive a fit-to-width base scale from the
  // container. Triggers a re-render (baseScale changes null -> number),
  // which the effect below picks up to do the actual page rendering.
  useEffect(() => {
    if (!pdfDoc || baseScale !== null) return;
    let cancelled = false;
    (async () => {
      const containerWidth = scrollRef.current?.clientWidth ?? 600;
      const firstPage = await pdfDoc.getPage(1);
      const unscaled = firstPage.getViewport({ scale: 1 });
      if (!cancelled) setBaseScale(Math.max(0.4, (containerWidth - 12) / unscaled.width));
    })();
    return () => {
      cancelled = true;
    };
  }, [pdfDoc, baseScale]);

  // Render each page to its canvas whenever the effective scale (zoom)
  // changes — re-rendered at the new resolution, not just CSS-scaled, so
  // text stays crisp when zoomed in.
  useEffect(() => {
    if (!pdfDoc || scale === null) return;
    let cancelled = false;

    (async () => {
      for (let i = 1; i <= pdfDoc.numPages; i++) {
        if (cancelled) return;
        const page = await pdfDoc.getPage(i);
        const viewport = page.getViewport({ scale });
        viewportsRef.current[i - 1] = viewport;
        const canvas = canvasRefs.current[i - 1];
        if (!canvas) continue;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        const ctx = canvas.getContext("2d");
        if (!ctx) continue;
        await page.render({ canvasContext: ctx, viewport, canvas }).promise;
      }
      if (!cancelled) setLoading(false);
    })().catch((err) => {
      if (!cancelled) {
        setError(err instanceof Error ? err.message : "Failed to render PDF.");
        setLoading(false);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [pdfDoc, scale]);

  // Compute highlight geometry once per document + span set, by matching
  // each step's exact source text against the PDF's own text layer — not
  // on every verdict update (spanSignature only changes at decomposition).
  useEffect(() => {
    if (!pdfDoc || !normalizedSource || !steps || steps.length === 0) {
      setStepBoxes(new Map());
      return;
    }
    let cancelled = false;
    computeStepBoxes(pdfDoc, normalizedSource, steps).then((map) => {
      if (!cancelled) setStepBoxes(map);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on spanSignature, not `steps` itself
  }, [pdfDoc, normalizedSource, spanSignature]);

  // Track the current page via how much of each page wrapper is visible.
  useEffect(() => {
    const scrollEl = scrollRef.current;
    if (!scrollEl || pageCount === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const page = Number((entry.target as HTMLElement).dataset.page);
          ratiosRef.current.set(page, entry.intersectionRatio);
        }
        let bestPage = 1;
        let bestRatio = -1;
        for (const [page, ratio] of ratiosRef.current) {
          if (ratio > bestRatio) {
            bestRatio = ratio;
            bestPage = page;
          }
        }
        if (bestRatio > 0) setCurrentPage(bestPage);
      },
      { root: scrollEl, threshold: [0, 0.25, 0.5, 0.75, 1] },
    );
    for (const el of pageWrapperRefs.current) {
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [pageCount]);

  // Sidebar -> source: scroll the focused step's first box into view.
  useEffect(() => {
    if (focusOrigin !== "sidebar" || !focusedStepId) return;
    const firstBox = stepBoxes.get(focusedStepId)?.[0];
    if (!firstBox) return;
    pageWrapperRefs.current[firstBox.page - 1]?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
  }, [focusedStepId, focusOrigin, stepBoxes]);

  function projectBox(pageIndex: number, box: TextBox) {
    const viewport = viewportsRef.current[pageIndex];
    if (!viewport) return null;
    const [x1, y1] = viewport.convertToViewportPoint(box.x, box.y);
    const [x2, y2] = viewport.convertToViewportPoint(box.x + box.w, box.y + box.h);
    return {
      left: Math.min(x1, x2),
      top: Math.min(y1, y2),
      width: Math.abs(x2 - x1),
      height: Math.abs(y2 - y1),
    };
  }

  function adjustZoom(delta: number) {
    setZoom((z) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round((z + delta) * 100) / 100)));
  }

  return (
    <div className="paper">
      <div className="paper-scroll pdf-scroll" ref={scrollRef}>
        {loading && !error && <div className="pdf-status">Rendering PDF…</div>}
        {error && <div className="pdf-status pdf-error">{error}</div>}

        <div className="pdf-pages">
          {Array.from({ length: pageCount }, (_, i) => {
            const pageNum = i + 1;
            const boxes = boxesByPage.get(pageNum) ?? [];
            return (
              <div
                key={pageNum}
                className="pdf-page-wrapper"
                data-page={pageNum}
                ref={(el) => {
                  pageWrapperRefs.current[i] = el;
                }}
              >
                <canvas
                  ref={(el) => {
                    canvasRefs.current[i] = el;
                  }}
                />
                <div className="pdf-overlay">
                  {boxes.map((entry, j) => {
                    const rect = projectBox(i, entry.box);
                    if (!rect) return null;
                    return (
                      <div
                        key={j}
                        className={[
                          "pdf-highlight-box",
                          entry.pending ? "pending" : `verdict-${entry.verdict.toLowerCase()}`,
                          !entry.pending && entry.classification === "unformalizable"
                            ? "unformalizable"
                            : "",
                          focusedStepId === entry.stepId ? "active" : "",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                        style={{
                          left: rect.left,
                          top: rect.top,
                          width: rect.width,
                          height: rect.height,
                        }}
                        onMouseEnter={() => onFocus?.(entry.stepId)}
                        onClick={() => onFocus?.(entry.stepId)}
                      />
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="pdf-toolbar">
        <button
          type="button"
          className="pdf-zoom-btn"
          onClick={() => adjustZoom(-ZOOM_STEP)}
          disabled={zoom <= ZOOM_MIN}
          aria-label="Zoom out"
        >
          −
        </button>
        <span className="pdf-zoom-level">{Math.round(zoom * 100)}%</span>
        <button
          type="button"
          className="pdf-zoom-btn"
          onClick={() => adjustZoom(ZOOM_STEP)}
          disabled={zoom >= ZOOM_MAX}
          aria-label="Zoom in"
        >
          +
        </button>
      </div>

      <div className="paper-page-badge">
        {currentPage} / {pageCount || 1}
      </div>
    </div>
  );
}
