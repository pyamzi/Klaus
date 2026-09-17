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
 * Case-insensitive, non-overlapping matches in page order. A blank query
 * matches nothing — an empty find bar is not a search for everything.
 */
export function findMatches(pages: PageText[], query: string): Match[] {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return [];
  }
  const matches: Match[] = [];
  for (const { page, text } of pages) {
    const haystack = text.toLowerCase();
    let at = haystack.indexOf(needle);
    while (at !== -1) {
      matches.push({ page, start: at, end: at + needle.length });
      at = haystack.indexOf(needle, at + needle.length);
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
