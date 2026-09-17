// Search over the document's text, the count label, and match cycling —
// per docs/reference/klausmate-viewer-parity.md, "Find bar". Pure on
// purpose (no React, no DOM) so tests/find_test.mjs runs it under node:test.

/** One page's text, concatenated in text-layer order. */
export interface PageText {
  page: number;
  text: string;
}

/** A hit, as an offset range into that page's text. */
export interface Match {
  page: number;
  start: number;
  end: number;
}

/**
 * Case-folded text plus a map back to the original string.
 *
 * Lowercasing is not length-preserving — "İ".toLowerCase() is two UTF-16
 * units, "SS".toLowerCase() stays two but other locales differ — so folding
 * a page and then reporting folded offsets would select the wrong characters
 * in the rendered text layer. `offsets[i]` is the original index that folded
 * unit `i` came from, with a final sentinel entry so a match ending at the
 * very end of the text still maps.
 */
function fold(text: string): { folded: string; offsets: number[] } {
  let folded = "";
  const offsets: number[] = [];
  for (let i = 0; i < text.length; ) {
    const char = String.fromCodePoint(text.codePointAt(i) as number);
    const lower = char.toLowerCase();
    for (let unit = 0; unit < lower.length; unit++) {
      offsets.push(i);
    }
    folded += lower;
    i += char.length;
  }
  offsets.push(text.length);
  return { folded, offsets };
}

/**
 * Case-insensitive, non-overlapping matches in page order, reported as
 * offsets into the *original* page text. A blank query matches nothing — an
 * empty find bar is not a search for everything.
 */
export function findMatches(pages: PageText[], query: string): Match[] {
  const needle = fold(query.trim()).folded;
  if (!needle) {
    return [];
  }
  const matches: Match[] = [];
  for (const { page, text } of pages) {
    const { folded, offsets } = fold(text);
    let at = folded.indexOf(needle);
    while (at !== -1) {
      const end = at + needle.length;
      matches.push({ page, start: offsets[at], end: offsets[end] });
      at = folded.indexOf(needle, end);
    }
  }
  return matches;
}

/**
 * The count label, verbatim from klausmate: nothing for an empty query,
 * "0 matches" for a miss, "{i+1} of {count}" once a match is current, and
 * "{count} matches" while a search has hits but none is selected yet.
 */
export function countLabel(query: string, count: number, index: number): string {
  if (!query.trim()) {
    return "";
  }
  if (count === 0) {
    return "0 matches";
  }
  if (index < 0) {
    return `${count} matches`;
  }
  return `${index + 1} of ${count}`;
}

/**
 * Next (step +1) or previous (step -1) match index, wrapping at both ends.
 * With nothing selected yet, forward starts at the first match and backward
 * at the last. -1 means "no current match".
 */
export function cycleIndex(index: number, count: number, step: number): number {
  if (count === 0) {
    return -1;
  }
  if (index < 0) {
    return step >= 0 ? 0 : count - 1;
  }
  return (((index + step) % count) + count) % count;
}
