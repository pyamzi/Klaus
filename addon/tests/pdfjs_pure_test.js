// PDF reader 2/5: the pure helpers behind the render cache, the
// per-page mark redraw and the incremental find (klausmate/web/pdfjs_pure.js).
// Run by tests/test_pdfjs_pure.py when `node` is present. Exit 1 on failure.
"use strict";
const assert = require("assert");
const path = require("path");
const { KEEP_RENDERED, evictable, changedPages, findOrder } =
  require(path.join(__dirname, "..", "klausmate", "web", "pdfjs_pure.js"));

const failures = [];
function check(name, fn) {
  try { fn(); console.log("  ok  " + name); }
  catch (e) { console.log(" FAIL " + name + "  " + e.message); failures.push(name); }
}
const sorted = (s) => [...s].sort((a, b) => a - b);

check("KEEP_RENDERED is 12", () => assert.strictEqual(KEEP_RENDERED, 12));

check("nothing evicted at or under the cap", () => {
  assert.deepStrictEqual(evictable([1, 2, 3, 4], new Set([4]), 3), []);
  assert.deepStrictEqual(evictable([1, 2, 3], new Set(), 3), []);
  assert.deepStrictEqual(evictable([], new Set(), 0), []);
});
check("over the cap: the least recently visible out-of-zone pages go first", () => {
  assert.deepStrictEqual(evictable([7, 3, 9, 1, 2], new Set([2]), 2), [7, 3]);
});
check("zone pages are never evicted, even with keep 0", () => {
  assert.deepStrictEqual(evictable([5, 1, 6, 2], new Set([5, 6]), 0), [1, 2]);
  assert.deepStrictEqual(evictable([5, 6], new Set([5, 6]), 0), []);
});

const hl = (id, page, extra) => Object.assign(
  { id, page, kind: "highlight", color: "#fadc50", rects: [[1, 2, 3, 4]] }, extra);

check("first records: their pages, 1-based", () => {
  assert.deepStrictEqual(sorted(changedPages([], [hl("a", 0), hl("b", 4)])), [1, 5]);
});
check("unchanged records change nothing", () => {
  assert.strictEqual(changedPages([hl("a", 0)], [hl("a", 0)]).size, 0);
});
check("added and removed records mark their pages", () => {
  assert.deepStrictEqual(sorted(changedPages([hl("a", 0)], [hl("a", 0), hl("b", 2)])), [3]);
  assert.deepStrictEqual(sorted(changedPages([hl("a", 0), hl("b", 2)], [hl("b", 2)])), [1]);
});
check("changed rects or content mark the page", () => {
  assert.deepStrictEqual(sorted(changedPages([hl("a", 1)], [hl("a", 1, { rects: [[9, 9, 9, 9]] })])), [2]);
  assert.deepStrictEqual(sorted(changedPages([hl("a", 1)], [hl("a", 1, { note: "x" })])), [2]);
  assert.deepStrictEqual(sorted(changedPages([hl("a", 1)], [hl("a", 1, { color: "#000000" })])), [2]);
});
check("a moved highlight marks both its old and new page", () => {
  assert.deepStrictEqual(sorted(changedPages([hl("a", 1)], [hl("a", 6)])), [2, 7]);
});

check("findOrder([5,6], 8) is [5,6,1,2,3,4,7,8]", () => {
  assert.deepStrictEqual(findOrder([5, 6], 8), [5, 6, 1, 2, 3, 4, 7, 8]);
});
check("findOrder keeps visible order, drops duplicates and out-of-range pages", () => {
  assert.deepStrictEqual(findOrder([3, 2, 3, 0, 9], 4), [3, 2, 1, 4]);
  assert.deepStrictEqual(findOrder([], 3), [1, 2, 3]);
  assert.deepStrictEqual(findOrder([1], 0), []);
});

if (failures.length) { console.log(failures.length + " failed"); process.exit(1); }
