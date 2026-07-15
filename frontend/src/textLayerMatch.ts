import type { PDFDocumentProxy } from "pdfjs-dist";

/** A highlight rectangle in raw, unscaled PDF user-space (the same space
 * `page.getViewport({ scale: 1 })` operates in) — scale-independent, so it
 * only needs recomputing when the document changes, not on zoom. */
export interface TextBox {
  page: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

interface PageItem {
  str: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

interface PageIndex {
  page: number;
  items: PageItem[];
  /** Normalized (lowercase, alnum-only, whitespace-collapsed) page text. */
  norm: string;
  /** norm[i] came from raw concatenated text at rawIndexOfNormChar[i]. */
  rawIndexOfNormChar: number[];
  /** itemBoundaries[j] = raw offset where items[j] starts. */
  itemBoundaries: number[];
}

function normalizeWithIndex(raw: string): { norm: string; rawIndexOfNormChar: number[] } {
  let norm = "";
  const rawIndexOfNormChar: number[] = [];
  let prevWasSpace = true;
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i].toLowerCase();
    if (/[a-z0-9]/.test(ch)) {
      norm += ch;
      rawIndexOfNormChar.push(i);
      prevWasSpace = false;
    } else if (!prevWasSpace) {
      norm += " ";
      rawIndexOfNormChar.push(i);
      prevWasSpace = true;
    }
  }
  return { norm, rawIndexOfNormChar };
}

async function buildPageIndex(doc: PDFDocumentProxy, pageNum: number): Promise<PageIndex> {
  const page = await doc.getPage(pageNum);
  const content = await page.getTextContent();
  const items: PageItem[] = (content.items as { str: string; transform: number[]; width: number; height: number }[])
    .filter((it) => typeof it.str === "string")
    .map((it) => ({ str: it.str, x: it.transform[4], y: it.transform[5], w: it.width, h: it.height }));

  let raw = "";
  const itemBoundaries: number[] = [];
  for (const it of items) {
    itemBoundaries.push(raw.length);
    raw += it.str + " ";
  }
  const { norm, rawIndexOfNormChar } = normalizeWithIndex(raw);
  return { page: pageNum, items, norm, rawIndexOfNormChar, itemBoundaries };
}

function itemIndexForRawOffset(index: PageIndex, rawOffset: number): number {
  // itemBoundaries is sorted ascending; find the last boundary <= rawOffset.
  let lo = 0;
  let hi = index.itemBoundaries.length - 1;
  let result = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (index.itemBoundaries[mid] <= rawOffset) {
      result = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return result;
}

function bigrams(s: string): Map<string, number> {
  const m = new Map<string, number>();
  for (let i = 0; i < s.length - 1; i++) {
    const bg = s.slice(i, i + 2);
    m.set(bg, (m.get(bg) ?? 0) + 1);
  }
  return m;
}

function diceCoefficient(a: string, b: string): number {
  if (a.length < 2 || b.length < 2) return a === b ? 1 : 0;
  const bgA = bigrams(a);
  let overlap = 0;
  let totalB = 0;
  for (const [bg, count] of bigrams(b)) {
    totalB += count;
    const inA = bgA.get(bg) ?? 0;
    overlap += Math.min(inA, count);
  }
  let totalA = 0;
  for (const c of bgA.values()) totalA += c;
  return (2 * overlap) / (totalA + totalB || 1);
}

const FUZZY_THRESHOLD = 0.55;

/** Finds the best match for `needle` (already normalized) inside
 * `index.norm`, exact substring first, then a sliding-window fuzzy fallback
 * — mirrors backend/app/pipeline/span_matching.py's philosophy (offset/text
 * drift between what we're searching for and the searched text is the
 * common case, not an edge case), applied here to LaTeX-source-vs-rendered-
 * PDF-text drift instead of LLM-offset drift. */
function findBestMatch(needle: string, index: PageIndex): { start: number; end: number } | null {
  if (needle.length === 0) return null;

  const exact = index.norm.indexOf(needle);
  if (exact !== -1) return { start: exact, end: exact + needle.length };

  const window = needle.length;
  if (window > index.norm.length) return null;

  let bestScore = 0;
  let bestStart = -1;
  const stride = Math.max(1, Math.floor(window / 6));
  for (let i = 0; i <= index.norm.length - window; i += stride) {
    const score = diceCoefficient(needle, index.norm.slice(i, i + window));
    if (score > bestScore) {
      bestScore = score;
      bestStart = i;
    }
  }
  if (bestStart === -1 || bestScore < FUZZY_THRESHOLD) return null;
  return { start: bestStart, end: bestStart + window };
}

/** Groups a run of items into one box per source text-line (items whose y
 * is within half a line-height of each other), since a multi-word match
 * spans several pdf.js text items that should merge into as few visual
 * rectangles as possible rather than one per item. */
function itemsToBoxes(pageNum: number, items: PageItem[]): TextBox[] {
  if (items.length === 0) return [];
  const sorted = [...items].sort((a, b) => b.y - a.y || a.x - b.x);
  const boxes: TextBox[] = [];
  let group: PageItem[] = [sorted[0]];

  const flush = () => {
    const x = Math.min(...group.map((it) => it.x));
    const right = Math.max(...group.map((it) => it.x + it.w));
    const yTop = Math.max(...group.map((it) => it.y + it.h));
    const yBottom = Math.min(...group.map((it) => it.y));
    boxes.push({ page: pageNum, x, y: yBottom, w: right - x, h: yTop - yBottom });
  };

  for (let i = 1; i < sorted.length; i++) {
    const prev = group[group.length - 1];
    if (Math.abs(sorted[i].y - prev.y) < prev.h * 0.6) {
      group.push(sorted[i]);
    } else {
      flush();
      group = [sorted[i]];
    }
  }
  flush();
  return boxes;
}

/** Computes highlight boxes for every step by matching each step's exact
 * source text (already offset-resolved server-side into source_span, no
 * LLM drift left to worry about) against the compiled PDF's own extracted
 * text, page by page — real glyph positions from pdf.js, not an
 * approximation of SyncTeX's line-level boxes. Runs once per document +
 * step-span set; callers should memoize on something that only changes
 * when spans do (decomposition), not on every verdict update. */
export async function computeStepBoxes(
  doc: PDFDocumentProxy,
  normalizedSource: string,
  steps: { id: string; source_span: { start: number; end: number } }[],
): Promise<Map<string, TextBox[]>> {
  const pageIndexes: PageIndex[] = [];
  for (let p = 1; p <= doc.numPages; p++) {
    pageIndexes.push(await buildPageIndex(doc, p));
  }

  const result = new Map<string, TextBox[]>();
  for (const step of steps) {
    const { start, end } = step.source_span;
    if (end <= start) continue;
    const needleRaw = normalizedSource.slice(start, end);
    const { norm: needle } = normalizeWithIndex(needleRaw);
    if (!needle) continue;

    let found: { pageIndex: PageIndex; start: number; end: number } | null = null;
    for (const pageIndex of pageIndexes) {
      const match = findBestMatch(needle, pageIndex);
      if (match) {
        found = { pageIndex, ...match };
        break;
      }
    }
    if (!found) continue;

    const rawStart = found.pageIndex.rawIndexOfNormChar[found.start];
    const rawEnd = found.pageIndex.rawIndexOfNormChar[found.end - 1];
    const firstItem = itemIndexForRawOffset(found.pageIndex, rawStart);
    const lastItem = itemIndexForRawOffset(found.pageIndex, rawEnd);
    const matchedItems = found.pageIndex.items.slice(firstItem, lastItem + 1);
    result.set(step.id, itemsToBoxes(found.pageIndex.page, matchedItems));
  }
  return result;
}
