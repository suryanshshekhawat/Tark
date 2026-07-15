import * as pdfjsLib from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
// eslint-disable-next-line import/no-unresolved -- Vite `?url` import, resolved at build time.
import workerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Step } from "../types";

pdfjsLib.GlobalWorkerOptions.workerSrc = workerSrc;

interface BoxEntry {
  stepId: string;
  verdict: Step["verdict"];
  classification: Step["classification"];
  pending: boolean;
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Real, page-by-page rendering of a compiled PDF (see
 * backend/app/rendering/) — replaces the old KaTeX-approximated paper.
 * Highlight boxes come straight from the backend's SyncTeX lookup
 * (Step.pdf_boxes), already in the same PDF point space pdf.js reports for
 * an unscaled viewport, so positioning them is just `* scale`. */
export function PdfPaperViewer({
  pdfUrl,
  steps,
  resolvedIds,
  focusedStepId = null,
  focusOrigin = null,
  onFocus,
}: {
  pdfUrl: string;
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
  const ratiosRef = useRef<Map<number, number>>(new Map());

  const [pdfDoc, setPdfDoc] = useState<PDFDocumentProxy | null>(null);
  const [pageCount, setPageCount] = useState(0);
  const [scale, setScale] = useState(1);
  const [currentPage, setCurrentPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const boxesByPage = useMemo(() => {
    const map = new Map<number, BoxEntry[]>();
    for (const step of steps ?? []) {
      const pending = resolvedIds ? !resolvedIds.has(step.id) : false;
      for (const box of step.pdf_boxes ?? []) {
        const list = map.get(box.page) ?? [];
        list.push({
          stepId: step.id,
          verdict: step.verdict,
          classification: step.classification,
          pending,
          x: box.x,
          y: box.y,
          w: box.w,
          h: box.h,
        });
        map.set(box.page, list);
      }
    }
    return map;
  }, [steps, resolvedIds]);

  // Load the document and get page count.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPdfDoc(null);
    setPageCount(0);
    ratiosRef.current.clear();
    pageWrapperRefs.current = [];
    canvasRefs.current = [];

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

  // Render each page to its canvas once the wrapper DOM (sized by
  // pageCount) exists. Runs after the effect above updates pageCount, so
  // the canvas refs below are guaranteed to be populated.
  useEffect(() => {
    if (!pdfDoc) return;
    let cancelled = false;

    (async () => {
      const containerWidth = scrollRef.current?.clientWidth ?? 600;
      const firstPage = await pdfDoc.getPage(1);
      const unscaled = firstPage.getViewport({ scale: 1 });
      const computedScale = Math.max(0.4, (containerWidth - 12) / unscaled.width);
      if (cancelled) return;
      setScale(computedScale);

      for (let i = 1; i <= pdfDoc.numPages; i++) {
        if (cancelled) return;
        const page = i === 1 ? firstPage : await pdfDoc.getPage(i);
        const viewport = page.getViewport({ scale: computedScale });
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
  }, [pdfDoc]);

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
    const step = steps?.find((s) => s.id === focusedStepId);
    const firstBox = step?.pdf_boxes?.[0];
    if (!firstBox) return;
    pageWrapperRefs.current[firstBox.page - 1]?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
  }, [focusedStepId, focusOrigin, steps]);

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
                  {boxes.map((entry, j) => (
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
                        left: entry.x * scale,
                        top: entry.y * scale,
                        width: entry.w * scale,
                        height: entry.h * scale,
                      }}
                      onMouseEnter={() => onFocus?.(entry.stepId)}
                      onClick={() => onFocus?.(entry.stepId)}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div className="paper-page-badge">
        {currentPage} / {pageCount || 1}
      </div>
    </div>
  );
}
