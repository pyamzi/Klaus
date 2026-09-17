// Gate for KB-016. Runs the editor's pure shortcut/zoom/page module directly
// under node:test — Node strips the TypeScript types, so no build step and no
// browser. `node --test tests/shortcuts_test.mjs`
import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  ZOOM_MAX,
  ZOOM_MIN,
  ZOOM_STEP,
  clampZoom,
  isTypingTarget,
  matchShortcut,
  parsePage,
  zoomIn,
  zoomOut,
} from "../extensions/klaus-pdf/webview-src/shortcuts.ts";

test("zoom ladder is klausmate's: x1.25 steps, clamped 0.25-5", () => {
  assert.deepEqual(
    {
      step: ZOOM_STEP,
      min: ZOOM_MIN,
      max: ZOOM_MAX,
      inFrom1: zoomIn(1),
      outFrom1: zoomOut(1),
      roundTrip: zoomOut(zoomIn(1)),
      clampedHigh: zoomIn(ZOOM_MAX),
      clampedLow: zoomOut(ZOOM_MIN),
      overshootHigh: clampZoom(99),
      overshootLow: clampZoom(0.01),
    },
    {
      step: 1.25,
      min: 0.25,
      max: 5,
      inFrom1: 1.25,
      outFrom1: 0.8,
      roundTrip: 1,
      clampedHigh: 5,
      clampedLow: 0.25,
      overshootHigh: 5,
      overshootLow: 0.25,
    },
  );
});

test("shortcut table maps every combo, under Cmd and under Ctrl alike", () => {
  const actions = (mod) =>
    [
      { key: "=", [mod]: true },
      { key: "+", [mod]: true },
      { key: "-", [mod]: true },
      { key: "0", [mod]: true },
      { key: "a", [mod]: true },
      { key: "A", [mod]: true },
      { key: "g", [mod]: true, altKey: true },
      { key: "G", [mod]: true, altKey: true },
      { key: "PageDown" },
      { key: "ArrowRight" },
      { key: "ArrowDown" },
      { key: "PageUp" },
      { key: "ArrowLeft" },
      { key: "ArrowUp" },
      { key: "Home" },
      { key: "End" },
    ].map(matchShortcut);

  const expected = [
    "zoom-in",
    "zoom-in",
    "zoom-out",
    "zoom-fit",
    "select-page",
    "select-page",
    "go-to-page",
    "go-to-page",
    "page-next",
    "page-next",
    "page-next",
    "page-prev",
    "page-prev",
    "page-prev",
    "page-first",
    "page-last",
  ];

  assert.deepEqual(
    { meta: actions("metaKey"), ctrl: actions("ctrlKey") },
    { meta: expected, ctrl: expected },
  );
});

test("keys that are not ours yield no action", () => {
  assert.deepEqual(
    [
      matchShortcut({ key: "a" }),
      matchShortcut({ key: "=" }),
      matchShortcut({ key: "0" }),
      matchShortcut({ key: "x", metaKey: true }),
      // Reserved: Cmd+Shift+H highlights (KB-003), Cmd+Shift+G finds (KB-014).
      matchShortcut({ key: "A", metaKey: true, shiftKey: true }),
      matchShortcut({ key: "G", metaKey: true, shiftKey: true }),
      matchShortcut({ key: "g", metaKey: true }),
      matchShortcut({ key: "ArrowRight", shiftKey: true }),
      matchShortcut({ key: "Home", altKey: true }),
    ],
    [null, null, null, null, null, null, null, null, null],
  );
});

test("typing targets keep their keystrokes", () => {
  assert.deepEqual(
    [
      isTypingTarget({ tagName: "TEXTAREA" }),
      isTypingTarget({ tagName: "input" }),
      isTypingTarget({ isContentEditable: true }),
      isTypingTarget({ tagName: "DIV" }),
      isTypingTarget({ tagName: "BUTTON", isContentEditable: false }),
      isTypingTarget(null),
      isTypingTarget(undefined),
    ],
    [true, true, true, false, false, false, false],
  );
});

test("page parsing accepts 1..n and refuses everything else", () => {
  assert.deepEqual(
    [
      parsePage("1", 10),
      parsePage("10", 10),
      parsePage(" 4 ", 10),
      parsePage("", 10),
      parsePage("abc", 10),
      parsePage("0", 10),
      parsePage("11", 10),
      parsePage("-3", 10),
      parsePage("1.5", 10),
    ],
    [1, 10, 4, null, null, null, null, null, null],
  );
});
