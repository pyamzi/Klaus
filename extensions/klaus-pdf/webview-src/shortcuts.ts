// Keyboard table, zoom ladder and page parsing for the editor, per
// docs/reference/klausmate-viewer-parity.md. Pure on purpose — no React and
// no DOM imports — so tests/shortcuts_test.mjs can run it under node:test.

export const ZOOM_STEP = 1.25;
export const ZOOM_MIN = 0.25;
export const ZOOM_MAX = 5;

export function clampZoom(scale: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, scale));
}

export function zoomIn(scale: number): number {
  return clampZoom(scale * ZOOM_STEP);
}

export function zoomOut(scale: number): number {
  return clampZoom(scale / ZOOM_STEP);
}

export type Action =
  | "zoom-in"
  | "zoom-out"
  | "zoom-fit"
  | "select-page"
  | "go-to-page"
  | "find"
  | "find-next"
  | "find-prev"
  | "highlight"
  | "page-next"
  | "page-prev"
  | "page-first"
  | "page-last";

/** The fields of a KeyboardEvent this module reads. */
export interface KeyLike {
  key: string;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
}

/** The fields of an event target this module reads. */
export interface TargetLike {
  tagName?: string;
  isContentEditable?: boolean;
}

/**
 * True when keystrokes belong to the thing being typed in (the notes
 * textarea, the page field) rather than to the slide.
 */
export function isTypingTarget(target: TargetLike | null | undefined): boolean {
  if (!target) {
    return false;
  }
  const tag = (target.tagName ?? "").toUpperCase();
  return tag === "TEXTAREA" || tag === "INPUT" || target.isContentEditable === true;
}

/**
 * Map a keystroke to an editor action, or null when the key is not ours.
 * Cmd and Ctrl are interchangeable.
 */
export function matchShortcut(event: KeyLike): Action | null {
  const mod = Boolean(event.metaKey || event.ctrlKey);
  const alt = Boolean(event.altKey);
  const shift = Boolean(event.shiftKey);

  if (mod && shift) {
    switch (event.key.toLowerCase()) {
      case "g":
        return "find-prev";
      // klausmate binds both Cmd+Shift+H and Cmd+Shift+A to highlight.
      case "h":
      case "a":
        return "highlight";
      default:
        return null;
    }
  }
  if (mod && alt) {
    return event.key.toLowerCase() === "g" ? "go-to-page" : null;
  }
  if (mod) {
    switch (event.key) {
      case "=":
      case "+":
        return "zoom-in";
      case "-":
        return "zoom-out";
      case "0":
        return "zoom-fit";
      case "a":
      case "A":
        return "select-page";
      case "f":
      case "F":
        return "find";
      case "g":
      case "G":
        return "find-next";
      default:
        return null;
    }
  }
  if (alt || shift) {
    return null;
  }
  switch (event.key) {
    case "ArrowRight":
    case "ArrowDown":
    case "PageDown":
      return "page-next";
    case "ArrowLeft":
    case "ArrowUp":
    case "PageUp":
      return "page-prev";
    case "Home":
      return "page-first";
    case "End":
      return "page-last";
    default:
      return null;
  }
}

/** A 1-based page number from user input, or null when it is not one. */
export function parsePage(raw: string, pageCount: number): number | null {
  const n = Number(raw.trim());
  if (!Number.isInteger(n) || n < 1 || n > pageCount) {
    return null;
  }
  return n;
}
