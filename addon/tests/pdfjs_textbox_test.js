// Behavioural test for the PDF reader's in-place text box editor
// (klaus_note/web/pdfjs_viewer.html): the REAL openTextEdit,
// sizeTextEdit, positionTextEdit, commitTextEdit, textBoxFor and
// measureTextBox, extracted from the page and run against a fake DOM.
// A source pin cannot show what the commit payload carries or what --k
// ends up as; this does.
//
// Run by tests/test_pdfjs_pure.py when `node` is present (reported as
// skipped, never as a pass, when it is not). Exit 1 on failure.
//
// The fake layout models what the page relies on, measured in Blink
// (see .superpowers/sdd/2026-09-30-pdf-reader/textbox-fix-report.md):
// glyphs advance a fixed 0.5 em, a line is 1.15 em, a box wraps at its
// width, `width: max-content` is capped by the max-width (480px, or the
// inline one measureTextBox sets for a note card's margin), and a
// single trailing "\n" adds no line (a contenteditable's Enter inserts
// "\n\n", the second being the caret's line).
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(
  path.join(__dirname, "..", "klaus_note", "web", "pdfjs_viewer.html"), "utf8");

function fn(name) {
  const m = new RegExp("\\nfunction " + name + "\\([\\s\\S]*?\\n}\\n").exec(SRC);
  if (!m) throw new Error("function " + name + " not found in the page");
  return m[0];
}
function line(re) {
  const m = re.exec(SRC);
  if (!m) throw new Error("declaration not found: " + re);
  return m[0] + "\n";
}

const ADV = 0.5, LH = 1.15, MAX_W = 480;
function lines(text) {
  return String(text).replace(/\n$/, "").split("\n");
}
function wrapped(text, size, width) {
  let n = 0;
  for (const l of lines(text)) {
    const w = l.replace(/​/g, "").length * ADV * size;
    n += Math.max(1, Math.ceil(w / width - 1e-9));
  }
  return n;
}
function layout(node) {
  if (node.id !== "textMeasure") return { width: 0, height: 0 };
  const size = parseFloat(node.style.fontSize);
  const text = node.textContent;
  let width;
  if (node.style.width === "") {
    const natural = Math.max(...lines(text).map(
      (l) => l.replace(/​/g, "").length * ADV * size));
    width = Math.min(natural, parseFloat(node.style.maxWidth) || MAX_W);
  } else {
    width = parseFloat(node.style.width);
  }
  return { width, height: wrapped(text, size, Math.max(width, 1e-6)) * LH * size };
}

function el(tag) {
  const n = {
    tag, id: "", className: "", title: "", spellcheck: true, children: [],
    parentNode: null, isConnected: false, listeners: {}, _text: "",
    contentEditable: "inherit",
    // A CSSStyleDeclaration: unset properties read as "", not undefined.
    style: new Proxy({
      props: {},
      setProperty(k, v) { this.props[k] = String(v); },
    }, { get: (o, k) => (k in o ? o[k] : "") }),
    appendChild(c) {
      if (c.parentNode) c.parentNode.removeChild(c);
      c.parentNode = n; n.children.push(c);
      const mark = (x, on) => { x.isConnected = on; x.children.forEach((y) => mark(y, on)); };
      mark(c, n.isConnected);
      return c;
    },
    removeChild(c) {
      const i = n.children.indexOf(c);
      if (i >= 0) n.children.splice(i, 1);
      c.parentNode = null; c.isConnected = false;
      return c;
    },
    addEventListener(t, f) { (n.listeners[t] = n.listeners[t] || []).push(f); },
    fire(t) { (n.listeners[t] || []).forEach((f) => f({})); },
    focus() {},
    getBoundingClientRect() { return layout(n); },
    get textContent() { return n._text; },
    set textContent(v) { n._text = String(v); },
    get innerText() { return n._text; },
    get isContentEditable() {
      return n.contentEditable === "true" || n.contentEditable === "plaintext-only";
    },
  };
  return n;
}

function makePage() {
  const root = el("div");
  root.id = "root";
  root.isConnected = true;
  const page = root.appendChild(el("div"));
  const posted = [];
  const ctx = {
    console, Math, String, parseFloat, Number, Set, Map, JSON,
    document: {
      createElement: (t) => el(t),
      getElementById: (id) => (id === "root" ? root : null),
      createRange: () => ({ selectNodeContents() {}, collapse() {} }),
    },
    window: { getSelection: () => ({ removeAllRanges() {}, addRange() {} }) },
    state: {
      pageDivs: [page], scale: 1, textEdit: null, textDrag: null, tsize: 12,
      pendingRepaint: new Set(), annots: [],
      rendered: new Map([[1, { ptW: 600, ptH: 800 }]]),
    },
    posted,
  };
  ctx.window.document = ctx.document;
  vm.createContext(ctx);
  const code =
    line(/const TEXT_BOX_MAX_W = [^;]+;/) +
    line(/const TEXT_BOX_MAX_H = [^;]+;/) +
    line(/const TEXT_SIZE_DEFAULT = [^;]+;/) +
    line(/const MAX_TEXT_CHARS = [^;]+;/) +
    line(/let textMeasurer = [^;]+;/) +
    line(/const CARD_PAD = [^;]+;/) +
    "function postB64(kind, obj) { posted.push([kind, obj]); }\n" +
    "function post() {}\n" +
    "function repaintAnnotPage() {}\n" +
    "function syncAnnobarMode() {}\n" +
    "function currentTextInk() { return '#000000'; }\n" +
    "function currentInk() { return '#ffd400'; }\n" +
    "function hexToRgba(h, a) { return 'ink(' + h + ',' + a + ')'; }\n" +
    "function startTextDrag() {}\n" +
    ["sanitizeEditText", "measureTextBox", "textBoxFor", "openTextEdit",
     "sizeTextEdit", "positionTextEdit", "closeTextEdit", "commitTextEdit",
     "pagePts", "clampCard"]
      .map(fn).join("");
  vm.runInContext(code, ctx);
  return ctx;
}

// Typing, as the browser delivers it: the text lands, then "input".
function type(ctx, text) {
  ctx.state.textEdit.body.textContent = text;
  ctx.state.textEdit.body.fire("input");
}

const failures = [];
function check(name, f) {
  try { f(); console.log("  ok  " + name); }
  catch (e) { console.log(" FAIL " + name + "  " + e.message); failures.push(name); }
}
const px = (v) => parseFloat(v);
// Values built inside the vm context have that realm's prototypes.
const plain = (v) => JSON.parse(JSON.stringify(v));

check("a new box sizes LIVE from measurement: 11 glyphs at 0.5 em + 1 pt, one 1.15 em line", () => {
  const p = makePage();
  vm.runInContext("openTextEdit(0, 10, 20, null)", p);
  type(p, "Hello world");
  const st = p.state.textEdit.el.style;
  assert.strictEqual(px(st.width), Math.ceil(11 * 6 + 1));     // 67
  assert.strictEqual(px(st.minHeight), Math.ceil(13.8));       // 14
});

check("a trailing Enter grows the editor by exactly the caret's line, and the commit drops it", () => {
  const p = makePage();
  vm.runInContext("openTextEdit(0, 10, 20, null)", p);
  type(p, "Hello world\n\n");                 // Blink's Enter at the end
  assert.strictEqual(px(p.state.textEdit.el.style.minHeight), Math.ceil(2 * 13.8));
  vm.runInContext("commitTextEdit()", p);
  assert.strictEqual(p.posted.length, 1);
  const [kind, body] = p.posted[0];
  assert.strictEqual(kind, "text-add");
  assert.strictEqual(body.text, "Hello world");
  assert.strictEqual(body.w, 67);
  assert.strictEqual(body.h, 14);
});

check("the text-add payload carries the MEASURED w/h with page, anchor, ink and size", () => {
  const p = makePage();
  p.state.pageDivs[1] = p.state.pageDivs[0];
  vm.runInContext("openTextEdit(1, 33, 44, null)", p);
  type(p, "First line\nsecond, longer line\nthird");
  const live = p.state.textEdit.el.style;
  vm.runInContext("commitTextEdit()", p);
  const body = p.posted[0][1];
  assert.deepStrictEqual(
    [body.w, body.h], [Math.ceil(19 * 6 + 1), Math.ceil(3 * 13.8)]);
  assert.deepStrictEqual([px(live.width), px(live.minHeight)], [body.w, body.h],
    "the committed box is the box the editor showed");
  assert.strictEqual(body.size, 12);
  assert.strictEqual(body.color, "#000000");
  assert.strictEqual("rows" in body, false);
});

check("a paragraph past the 480 pt cap wraps: width 480, height of its lines at 480", () => {
  const p = makePage();
  vm.runInContext("openTextEdit(0, 0, 0, null)", p);
  type(p, "x".repeat(200));                    // 1200 pt of glyphs at 12 pt
  vm.runInContext("commitTextEdit()", p);
  const body = p.posted[0][1];
  assert.strictEqual(body.w, 480);
  assert.strictEqual(body.h, Math.ceil(Math.ceil(1200 / 480) * 13.8));
});

check("a note card measures inside its margin: maxW caps the width and the wrap, and the next plain measure is back at 480", () => {
  const p = makePage();
  // 948 pt of glyphs: two lines at 480, three at 468 — the wrap must follow maxW.
  const [w, h] = vm.runInContext('measureTextBox("x".repeat(158), 12, 468)', p);
  assert.strictEqual(w, 468);
  assert.strictEqual(h, Math.ceil(3 * 13.8));
  const [w2] = vm.runInContext('measureTextBox("x".repeat(200), 12)', p);
  assert.strictEqual(w2, 480);
});

check("a note card measures under its own height cap, and the next plain measure is back at 720", () => {
  const p = makePage();
  const [, h] = vm.runInContext('measureTextBox("a\\n".repeat(400) + "a", 12, 468, 708)', p);
  assert.strictEqual(h, 708);
  const [, h2] = vm.runInContext('measureTextBox("a\\n".repeat(400) + "a", 12)', p);
  assert.strictEqual(h2, 720);
});

check("an absurd text is capped at 720 pt tall", () => {
  const p = makePage();
  vm.runInContext("openTextEdit(0, 0, 0, null)", p);
  type(p, "a\n".repeat(400) + "a");
  vm.runInContext("commitTextEdit()", p);
  assert.strictEqual(p.posted[0][1].h, 720);
});

check("an empty new box mints nothing", () => {
  const p = makePage();
  vm.runInContext("openTextEdit(0, 0, 0, null)", p);
  type(p, "  \n ");
  vm.runInContext("commitTextEdit()", p);
  assert.deepStrictEqual(p.posted, []);
});

const OLD = { id: "r1", kind: "text", page: 0, text: "Hello", size: 12,
              color: "#000000", rects: [[5, 6, 99, 22.2]] };

check("re-opening an old record shows its STORED box, and an untouched commit sends it back", () => {
  const p = makePage();
  p.state.rec = OLD;
  vm.runInContext("openTextEdit(0, 5, 6, state.rec)", p);
  const st = p.state.textEdit.el.style;
  assert.deepStrictEqual([px(st.width), px(st.minHeight)], [99, 22.2]);
  vm.runInContext("commitTextEdit()", p);
  const [kind, body] = p.posted[0];
  assert.strictEqual(kind, "text-update");
  assert.deepStrictEqual([body.id, body.w, body.h, body.size], ["r1", 99, 22.2, 12]);
});

check("editing the text re-measures the kept box", () => {
  const p = makePage();
  p.state.rec = OLD;
  vm.runInContext("openTextEdit(0, 5, 6, state.rec)", p);
  type(p, "Hello there");
  vm.runInContext("commitTextEdit()", p);
  assert.deepStrictEqual([p.posted[0][1].w, p.posted[0][1].h], [67, 14]);
});

check("changing the SIZE re-measures the kept box", () => {
  const p = makePage();
  p.state.rec = OLD;
  vm.runInContext("openTextEdit(0, 5, 6, state.rec)", p);
  vm.runInContext("state.textEdit.size = 24; sizeTextEdit();", p);
  vm.runInContext("commitTextEdit()", p);
  const body = p.posted[0][1];
  assert.deepStrictEqual([body.size, body.w, body.h],
    [24, Math.ceil(5 * 12 + 1), Math.ceil(1.15 * 24)]);
});

check("typing the text back to the original restores the kept box", () => {
  const p = makePage();
  p.state.rec = OLD;
  vm.runInContext("openTextEdit(0, 5, 6, state.rec)", p);
  type(p, "Hello!");
  type(p, "Hello");
  const st = p.state.textEdit.el.style;
  assert.deepStrictEqual([px(st.width), px(st.minHeight)], [99, 22.2]);
});

check("a record with NO stored size opens at the 12 pt default, the size it is drawn and stored at — not the stepper's current size", () => {
  const p = makePage();
  p.state.tsize = 18;
  p.state.rec = { id: "a1", kind: "text", page: 0, text: "Preview note",
                  rects: [[1, 2, 80, 20]], origin: "external" };
  vm.runInContext("openTextEdit(0, 1, 2, state.rec)", p);
  assert.strictEqual(p.state.textEdit.size, 12);
  assert.strictEqual(p.state.textEdit.body.style.fontSize, "12px");
  vm.runInContext("commitTextEdit()", p);
  const body = p.posted[0][1];
  assert.deepStrictEqual([body.size, body.w, body.h], [12, 80, 20],
    "untouched: the stored box and the size Python treats it as");
});

for (const s of [0.25, 0.5, 1, 1.37, 3, 4]) {
  check("at zoom " + s + ": --k = 1/scale (grip, ring and halo keep their 100% size), the box scale()s", () => {
    const p = makePage();
    p.state.scale = s;
    vm.runInContext("openTextEdit(0, 10, 20, null)", p);
    const st = p.state.textEdit.el.style;
    assert.strictEqual(Number(st.props["--k"]), 1 / s);
    assert.strictEqual(st.transform, "scale(" + s + ")");
    assert.strictEqual(st.left, 10 * s + "px");
    assert.strictEqual(st.top, 20 * s + "px");
  });
}

check("a zoom change while open re-lands --k for the new scale", () => {
  const p = makePage();
  vm.runInContext("openTextEdit(0, 10, 20, null)", p);
  vm.runInContext("state.scale = 2.5; positionTextEdit();", p);
  assert.strictEqual(Number(p.state.textEdit.el.style.props["--k"]), 1 / 2.5);
});

// ---- hand-drawn reader 7: the card variant of the same editor ----
// A note's rects[0] is the whole card, CARD_PAD (6 pt) a side included:
// "Hi" at 12 pt measures 13 x 14 inside the margin, so the card is 25 x 26.
const NOTE = { id: "n1", kind: "note", page: 0, text: "Hi", size: 12,
               color: "#7fc6f2", rects: [[40, 50, 25, 26]] };
const HL = { id: "h1", page: 0, color: "#ffd400", note: "See p. 4",
             rects: [[10, 10, 200, 14]] };

check("a Note-tool card: type, commit -> ONE note-add with the box INCLUDING CARD_PAD, the highlight ink, size 12", () => {
  const p = makePage();
  vm.runInContext('openTextEdit(0, 10, 20, null, "note")', p);
  const st = p.state.textEdit.el.style;
  assert.strictEqual(st.padding, "6px", "the margin, in points under the scale()");
  assert.strictEqual(st.background, "ink(#ffd400,0.85)");
  type(p, "Hi");
  vm.runInContext("commitTextEdit()", p);
  assert.deepStrictEqual(plain(p.posted), [["note-add", {
    page: 0, x: 10, y: 20, text: "Hi", color: "#ffd400", size: 12, w: 25, h: 26 }]]);
});

check("Review Focus 3: a NEW note left empty or whitespace posts nothing", () => {
  for (const t of ["", "   \n  "]) {
    const p = makePage();
    vm.runInContext('openTextEdit(0, 10, 20, null, "note")', p);
    type(p, t);
    vm.runInContext("commitTextEdit()", p);
    assert.deepStrictEqual(plain(p.posted), [], JSON.stringify(t));
  }
});

check("an EXISTING note emptied posts note-remove", () => {
  const p = makePage();
  p.state.rec = NOTE;
  vm.runInContext('openTextEdit(0, 40, 50, state.rec, "note")', p);
  type(p, "  ");
  vm.runInContext("commitTextEdit()", p);
  assert.deepStrictEqual(plain(p.posted), [["note-remove", { id: "n1" }]]);
});

check("an existing note untouched: its stored card box comes back as-is (no 12 pt growth), via note-update", () => {
  const p = makePage();
  p.state.rec = NOTE;
  vm.runInContext('openTextEdit(0, 40, 50, state.rec, "note")', p);
  const st = p.state.textEdit.el.style;
  assert.deepStrictEqual([px(st.width), px(st.minHeight)], [13, 14], "content box = card minus margin");
  vm.runInContext("commitTextEdit()", p);
  assert.deepStrictEqual(plain(p.posted), [["note-update", {
    id: "n1", x: 40, y: 50, text: "Hi", color: "#7fc6f2", size: 12, w: 25, h: 26 }]]);
});

check("a note placed at the page's corner is clamped inside it on commit (cardSpot's bounds)", () => {
  const p = makePage();
  vm.runInContext('openTextEdit(0, 590, 795, null, "note")', p);
  type(p, "Hi");
  vm.runInContext("commitTextEdit()", p);
  const b = p.posted[0][1];
  assert.deepStrictEqual([b.x, b.y, b.w, b.h], [600 - 25, 800 - 26, 25, 26]);
});

check("a highlight card edits rec.note, measures inside the margin (never the highlight's rect), commits note-text", () => {
  const p = makePage();
  p.state.rec = HL;
  vm.runInContext('openTextEdit(0, 218, 10, state.rec, "hl")', p);
  assert.strictEqual(p.state.textEdit.body.textContent, "See p. 4");
  assert.strictEqual(p.state.textEdit.kept, null);
  assert.strictEqual(px(p.state.textEdit.el.style.width), Math.ceil(8 * 6 + 1));
  type(p, "See p. 5");
  vm.runInContext("commitTextEdit()", p);
  assert.deepStrictEqual(plain(p.posted), [["note-text", { id: "h1", text: "See p. 5" }]]);
});

check("Review Focus 3: a highlight card emptied posts note-text \"\"; left unchanged it posts nothing", () => {
  const p = makePage();
  p.state.rec = HL;
  vm.runInContext('openTextEdit(0, 218, 10, state.rec, "hl")', p);
  type(p, " \n ");
  vm.runInContext("commitTextEdit()", p);
  assert.deepStrictEqual(plain(p.posted), [["note-text", { id: "h1", text: "" }]]);
  const q = makePage();
  q.state.rec = HL;
  vm.runInContext('openTextEdit(0, 218, 10, state.rec, "hl")', q);
  vm.runInContext("commitTextEdit()", q);
  assert.deepStrictEqual(plain(q.posted), []);
});

check("a highlight card's editor has no grip (a move would be dropped); a note's editor keeps it", () => {
  const p = makePage();
  p.state.rec = HL;
  vm.runInContext('openTextEdit(0, 218, 10, state.rec, "hl")', p);
  assert.deepStrictEqual(p.state.textEdit.el.children.map((c) => c.className), ["editBody"]);
  vm.runInContext("closeTextEdit()", p);
  vm.runInContext('openTextEdit(0, 10, 20, null, "note")', p);
  assert.deepStrictEqual(p.state.textEdit.el.children.map((c) => c.className), ["editGrip", "editBody"]);
});

check("clampCard keeps a card inside the page: 0..ptW-w, 0..ptH-h", () => {
  const p = makePage();
  assert.deepStrictEqual(plain(vm.runInContext("clampCard(0, -5, 900, 100, 50)", p)), [0, 750]);
  assert.deepStrictEqual(plain(vm.runInContext("clampCard(0, 550, -1, 100, 50)", p)), [500, 0]);
  assert.deepStrictEqual(plain(vm.runInContext("clampCard(0, 30, 40, 100, 50)", p)), [30, 40]);
});

if (failures.length) {
  console.log("\n" + failures.length + " failed");
  process.exit(1);
}
console.log("\nall passed");
