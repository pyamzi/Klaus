/* PDF reader 2/5: pure helpers for web/pdfjs_viewer.html — no DOM, so
   tests/pdfjs_pure_test.js runs them under node. A plain script: the
   page loads it before its main script and uses these as globals. */
"use strict";

/* Rendered pages kept outside the observer's zone before the oldest
   are torn down. */
const KEEP_RENDERED = 12;

/* Pages to tear down, least recently visible first. renderedLru lists
   rendered pages oldest first; a page in inZone is never returned, and
   `keep` out-of-zone pages (the newest) survive. */
function evictable(renderedLru, inZone, keep) {
  const out = renderedLru.filter((n) => !inZone.has(n));
  return out.slice(0, Math.max(0, out.length - keep));
}

/* 1-based pages whose marks differ between two record lists. Records
   carry a 0-based `page`, so each result is page + 1. Records match by
   id; an added, removed or changed record (rects or any content) marks
   its page, and a record that moved marks both pages. */
function changedPages(prev, next) {
  const before = new Map(prev.map((r) => [r.id, r]));
  const pages = new Set();
  for (const r of next) {
    const old = before.get(r.id);
    before.delete(r.id);
    if (old && JSON.stringify(old) === JSON.stringify(r)) continue;
    pages.add((r.page | 0) + 1);
    if (old) pages.add((old.page | 0) + 1);
  }
  for (const old of before.values()) pages.add((old.page | 0) + 1);
  return pages;
}

/* The order find walks pages in: the visible ones first (as given,
   de-duplicated, only 1..count), then the rest ascending. */
function findOrder(visible, count) {
  const first = [...new Set(visible)].filter((n) => n >= 1 && n <= count);
  const seen = new Set(first);
  for (let n = 1; n <= count; n++) if (!seen.has(n)) first.push(n);
  return first;
}

if (typeof module !== "undefined") {
  module.exports = { KEEP_RENDERED, evictable, changedPages, findOrder };
}
