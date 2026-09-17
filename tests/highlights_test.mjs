// Gate for KB-003. Runs the pure highlight-geometry module under node:test —
// Node strips the TypeScript types, so no build step and no browser.
// `node --test tests/highlights_test.mjs`
import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  DEFAULT_INK,
  HIGHLIGHT_ALPHA,
  HIGHLIGHT_INKS,
  rgba,
  selectionRects,
} from "../extensions/klaus-pdf/webview-src/highlights.ts";

const page = { left: 100, top: 50, right: 700, bottom: 850 };

test("klausmate's five inks, yellow first and default", () => {
  assert.deepEqual(HIGHLIGHT_INKS, ["#FADC50", "#8AE08C", "#7FC6F2", "#F79AC8", "#F7B267"]);
  assert.equal(DEFAULT_INK, "#FADC50");
  assert.equal(HIGHLIGHT_ALPHA, 110 / 255);
});

test("selection rects map to scale-1 page coordinates", () => {
  const rects = selectionRects(
    [{ left: 150, top: 100, right: 350, bottom: 124 }],
    page,
    2,
  );
  assert.deepEqual(rects, [[25, 25, 100, 12]]);
});

test("rects clip to the page and drop what falls outside", () => {
  const rects = selectionRects(
    [
      { left: 0, top: 100, right: 160, bottom: 124 },   // spills left: clipped
      { left: 800, top: 100, right: 900, bottom: 124 }, // fully outside: dropped
    ],
    page,
    1,
  );
  assert.deepEqual(rects, [[0, 50, 60, 24]]);
});

test("slivers and duplicates are dropped", () => {
  const line = { left: 150, top: 100, right: 350, bottom: 124 };
  const rects = selectionRects(
    [
      line,
      line, // nested spans double-report the same client rect
      { left: 150, top: 100, right: 151, bottom: 124 }, // sub-2px sliver
      { left: 150, top: 100, right: 350, bottom: 100.5 }, // collapsed height
    ],
    page,
    1,
  );
  assert.equal(rects.length, 1);
});

test("degenerate scale yields nothing rather than Infinity", () => {
  assert.deepEqual(selectionRects([{ left: 150, top: 100, right: 350, bottom: 124 }], page, 0), []);
});

test("rgba paints an ink at the klausmate alpha", () => {
  assert.equal(rgba("#FADC50", 110 / 255), `rgba(250, 220, 80, ${110 / 255})`);
  // Bad hex falls back to the default ink instead of an invalid color string.
  assert.equal(rgba("nope", 0.5), "rgba(250, 220, 80, 0.5)");
});
