// PDF reader 2/5: the pure helpers behind the render cache, the
// per-page mark redraw and the incremental find (klausmate/web/pdfjs_pure.js).
// Run by tests/test_pdfjs_pure.py when `node` is present. Exit 1 on failure.
"use strict";
const assert = require("assert");
const path = require("path");
const { KEEP_RENDERED, evictable, changedPages, findOrder,
        FIND_BUDGET_MS, shouldYield, insertMatch, seedFor, cardSpot } =
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

check("find yields only after a text extraction or a spent time budget", () => {
  assert.strictEqual(FIND_BUDGET_MS, 8);
  assert.strictEqual(shouldYield(0, 0), false);
  assert.strictEqual(shouldYield(0, 7.9), false);
  assert.strictEqual(shouldYield(0, 8), true);
  assert.strictEqual(shouldYield(1, 0), true);
});

const m = (page0, start) => ({ page0, start });
const keys = (list) => list.map((x) => x.page0 + ":" + x.start);
check("insertMatch keeps document order (page, then start)", () => {
  const list = [];
  for (const x of [m(4, 0), m(5, 3), m(0, 7), m(4, 9), m(0, 2), m(2, 1)]) insertMatch(list, x, -1);
  assert.deepStrictEqual(keys(list), ["0:2", "0:7", "2:1", "4:0", "4:9", "5:3"]);
});
check("insertMatch keeps the current match current", () => {
  const list = [m(4, 0), m(5, 3)];
  assert.strictEqual(insertMatch(list, m(1, 0), 0), 1);   // before current: index moves
  assert.strictEqual(list[1].page0, 4);
  assert.strictEqual(insertMatch(list, m(9, 0), 1), 1);   // after current: unchanged
  assert.strictEqual(insertMatch(list, m(4, 5), 1), 1);   // same page, later offset: unchanged
  assert.strictEqual(insertMatch(list, m(3, 0), 1), 2);   // earlier page: index moves again
  assert.deepStrictEqual(keys(list), ["1:0", "3:0", "4:0", "4:5", "5:3", "9:0"]);
  assert.strictEqual(insertMatch([], m(0, 0), -1), -1);   // no current match yet
});

// Hand-drawn reader: a mark's wobble comes from its id, and a note card's
// default spot sits beside its highlight, inside the page.
check("seedFor is stable per id and differs between ids", () => {
  assert.strictEqual(seedFor("abc"), seedFor("abc"));
  assert.notStrictEqual(seedFor("abc"), seedFor("abd"));
  const hex = "3f2c5db56cc93c5a6873b1361d730c16";
  assert.strictEqual(seedFor(hex), seedFor(hex));
});
check("seedFor is a positive 32-bit integer, never 0 (rough.js reads 0 as random)", () => {
  for (const id of ["", "x", "abc", "0", "3f2c5db56cc93c5a6873b1361d730c16"]) {
    const s = seedFor(id);
    assert.ok(Number.isInteger(s) && s > 0 && s <= 0xffffffff, id + " -> " + s);
  }
});
check("seedFor spreads: 200 ids give 200 seeds", () => {
  const seen = new Set();
  for (let i = 0; i < 200; i++) seen.add(seedFor("mark-" + i));
  assert.strictEqual(seen.size, 200);
});
const two = {rects: [[100, 50, 80, 12], [100, 64, 40, 12]]};
check("cardSpot: 8 pt right of the highlight's union, top-aligned", () => {
  assert.deepStrictEqual(cardSpot(two, 600, 800, 120, 40), {x: 188, y: 50});
});
check("cardSpot: a saved card offset is from the union's top-right", () => {
  assert.deepStrictEqual(cardSpot(Object.assign({card: [10, 5]}, two), 600, 800, 120, 40), {x: 190, y: 55});
});
check("cardSpot: clamped inside the page", () => {
  assert.deepStrictEqual(cardSpot({rects: [[550, 790, 40, 12]]}, 600, 800, 120, 40), {x: 480, y: 760});
  assert.deepStrictEqual(cardSpot({rects: [[0, 0, 10, 10]], card: [-500, -500]}, 600, 800, 120, 40), {x: 0, y: 0});
});
check("cardSpot: a card bigger than the page pins to the top-left", () => {
  assert.deepStrictEqual(cardSpot(two, 100, 100, 300, 300), {x: 0, y: 0});
});

if (failures.length) { console.log(failures.length + " failed"); process.exit(1); }
