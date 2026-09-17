// Highlight geometry and inks, per docs/reference/klausmate-viewer-parity.md.
// Pure on purpose — no React and no DOM imports — so
// tests/highlights_test.mjs can run it under node:test.

/** klausmate's five inks (theme.HIGHLIGHT_INKS): deliberately never
 *  theme-forked — they end up baked into the PDF itself. */
export const HIGHLIGHT_INKS = ["#FADC50", "#8AE08C", "#7FC6F2", "#F79AC8", "#F7B267"] as const;
export const DEFAULT_INK = "#FADC50";
/** klausmate paints highlight fills at alpha 110/255. */
export const HIGHLIGHT_ALPHA = 110 / 255;

/** The fields of a DOMRect this module reads. */
export interface RectLike {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/** [x, y, w, h] in scale-1 page coordinates. */
export type Rect = [number, number, number, number];

export interface Highlight {
  id: string;
  rects: Rect[];
  color: string;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/**
 * Convert a selection's client rects into scale-1 page coordinates.
 * Clips to the page, drops rects that fall outside it, drops sub-2px
 * slivers (collapsed ranges, caret rects), and dedupes the double-reports
 * that nested text-layer spans produce.
 */
export function selectionRects(
  clientRects: RectLike[],
  pageRect: RectLike,
  scale: number,
): Rect[] {
  if (!(scale > 0)) {
    return [];
  }
  const out: Rect[] = [];
  const seen = new Set<string>();
  for (const r of clientRects) {
    const left = Math.max(r.left, pageRect.left);
    const top = Math.max(r.top, pageRect.top);
    const right = Math.min(r.right, pageRect.right);
    const bottom = Math.min(r.bottom, pageRect.bottom);
    if (right - left < 2 || bottom - top < 2) {
      continue;
    }
    const rect: Rect = [
      round2((left - pageRect.left) / scale),
      round2((top - pageRect.top) / scale),
      round2((right - left) / scale),
      round2((bottom - top) / scale),
    ];
    const key = rect.join(",");
    if (!seen.has(key)) {
      seen.add(key);
      out.push(rect);
    }
  }
  return out;
}

/** Paint an ink at an alpha; a malformed hex falls back to the default ink. */
export function rgba(hex: string, alpha: number): string {
  const m = /^#([0-9A-Fa-f]{6})$/.exec(hex);
  const v = parseInt(m ? m[1] : DEFAULT_INK.slice(1), 16);
  return `rgba(${(v >> 16) & 255}, ${(v >> 8) & 255}, ${v & 255}, ${alpha})`;
}
