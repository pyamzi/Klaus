// Gate for KB-014. The find bar's search, labels and cycling are pure, so
// they run here with no browser: `node --test tests/find_test.mjs`
import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  countLabel,
  cycleIndex,
  findMatches,
} from "../extensions/klaus-pdf/webview-src/find.ts";

// "the" hits twice on page 1 (one capitalised) and twice on page 2 — the
// first of those inside "Another", because a find bar matches substrings,
// not words. Page 3 pins non-overlapping behaviour.
const PAGES = [
  { page: 1, text: "The cat sat on the mat" },
  { page: 2, text: "Another page, the end" },
  { page: 3, text: "aaaaa" },
];

test("search is case-insensitive and reports per-page offsets", () => {
  assert.deepEqual(findMatches(PAGES, "the"), [
    { page: 1, start: 0, end: 3 },
    { page: 1, start: 15, end: 18 },
    { page: 2, start: 3, end: 6 },
    { page: 2, start: 14, end: 17 },
  ]);
});

test("matches do not overlap, and a miss is empty", () => {
  assert.deepEqual(
    {
      overlapping: findMatches(PAGES, "aa"),
      miss: findMatches(PAGES, "zebra"),
      blank: findMatches(PAGES, "   "),
      empty: findMatches(PAGES, ""),
    },
    {
      // "aaaaa" yields two hits, not four: the scan resumes past each match.
      overlapping: [
        { page: 3, start: 0, end: 2 },
        { page: 3, start: 2, end: 4 },
      ],
      miss: [],
      blank: [],
      empty: [],
    },
  );
});

test("offsets point into the original text, not the folded one", () => {
  // "İ" (U+0130) lowercases to TWO UTF-16 units, so a naive fold-then-report
  // would push every later offset out by one and select the wrong characters
  // in the text layer. Both hits here must still land on "ok".
  const pages = [{ page: 1, text: "İstanbul ok İzmir ok" }];
  const found = findMatches(pages, "OK");
  assert.deepEqual(
    {
      found,
      slices: found.map((m) => pages[0].text.slice(m.start, m.end)),
      dotted: findMatches(pages, "i̇zmir").map((m) =>
        pages[0].text.slice(m.start, m.end),
      ),
    },
    {
      found: [
        { page: 1, start: 9, end: 11 },
        { page: 1, start: 18, end: 20 },
      ],
      slices: ["ok", "ok"],
      dotted: ["İzmir"],
    },
  );
});

test("count label has klausmate's four forms, verbatim", () => {
  assert.deepEqual(
    {
      noQuery: countLabel("", 0, -1),
      blankQuery: countLabel("  ", 3, 1),
      noMatches: countLabel("zebra", 0, -1),
      notYetCurrent: countLabel("the", 3, -1),
      current: countLabel("the", 3, 0),
      lastCurrent: countLabel("the", 3, 2),
      single: countLabel("the", 1, 0),
    },
    {
      noQuery: "",
      blankQuery: "",
      noMatches: "0 matches",
      notYetCurrent: "3 matches",
      current: "1 of 3",
      lastCurrent: "3 of 3",
      single: "1 of 1",
    },
  );
});

test("cycling wraps at both ends and starts from either side", () => {
  assert.deepEqual(
    {
      firstForward: cycleIndex(-1, 3, 1),
      firstBackward: cycleIndex(-1, 3, -1),
      next: cycleIndex(0, 3, 1),
      wrapForward: cycleIndex(2, 3, 1),
      prev: cycleIndex(2, 3, -1),
      wrapBackward: cycleIndex(0, 3, -1),
      singleForward: cycleIndex(0, 1, 1),
      singleBackward: cycleIndex(0, 1, -1),
      noMatches: cycleIndex(-1, 0, 1),
    },
    {
      firstForward: 0,
      firstBackward: 2,
      next: 1,
      wrapForward: 0,
      prev: 1,
      wrapBackward: 2,
      singleForward: 0,
      singleBackward: 0,
      noMatches: -1,
    },
  );
});
