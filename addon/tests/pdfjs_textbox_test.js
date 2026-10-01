// Behavioural test for the PDF reader's in-place text box editor
// (klausmate/web/pdfjs_viewer.html): the REAL openTextEdit,
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
// width, `width: max-content` is capped by the 480px max-width, and a
// single trailing "\n" adds no line (a contenteditable's Enter inserts
// "\n\n", the second being the caret's line).
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(
  path.join(__dirname, "..", "klausmate", "web", "pdfjs_viewer.html"), "utf8");

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
    width = Math.min(natural, MAX_W);
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
    "function postB64(kind, obj) { posted.push([kind, obj]); }\n" +
    "function post() {}\n" +
    "function repaintAnnotPage() {}\n" +
    "function syncAnnobarMode() {}\n" +
    "function currentTextInk() { return '#000000'; }\n" +
    "function startTextDrag() {}\n" +
    ["sanitizeEditText", "measureTextBox", "textBoxFor", "openTextEdit",
     "sizeTextEdit", "positionTextEdit", "closeTextEdit", "commitTextEdit"]
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

if (failures.length) {
  console.log("\n" + failures.length + " failed");
  process.exit(1);
}
console.log("\nall passed");
