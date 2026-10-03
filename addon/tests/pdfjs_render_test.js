// Behavioural test for the PDF reader's page render bookkeeping
// (klaus_note/web/pdfjs_viewer.html): the REAL renderPage, teardownPage,
// touchPage, onIntersect, relayout, teardown and the off-screen renders
// (renderThumb, copyPageImage, renderRegionCanvas), extracted from the
// page and run against a fake DOM and a fake pdf.js document.
//
//  - #23 a panel-resize relayout re-renders the pages in the render zone
//    (IntersectionObserver reports transitions only, so nothing else will);
//  - #32 a torn-down page and a finished off-screen render release their
//    pdf.js page caches (PDFPageProxy.cleanup());
//  - #33 a render that outlives its document touches neither the next
//    document's render state nor its claims.
//
// Run by tests/test_pdfjs_viewer.py when `node` is present (reported as
// skipped, never as a pass, when it is not). Exit 1 on failure.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "klaus_note", "web");
const SRC = fs.readFileSync(path.join(WEB, "pdfjs_viewer.html"), "utf8");
const PURE = fs.readFileSync(path.join(WEB, "pdfjs_pure.js"), "utf8");

function fn(name) {
  const m = new RegExp("\\n(?:async )?function " + name + "\\([\\s\\S]*?\\n}\\n").exec(SRC);
  if (!m) throw new Error("function " + name + " not found in the page");
  return m[0];
}

function el(tag) {
  const n = {
    tag, className: "", children: [], parentNode: null, dataset: {},
    style: {},
    get textContent() { return ""; },
    set textContent(v) {   // "" empties the node, as the DOM does
      for (const c of n.children) c.parentNode = null;
      n.children = [];
    },
    appendChild(c) {
      if (c.parentNode) c.parentNode.removeChild(c);
      c.parentNode = n; n.children.push(c); return c;
    },
    insertBefore(c) { return n.appendChild(c); },
    removeChild(c) {
      const i = n.children.indexOf(c);
      if (i < 0) throw new Error("not a child");
      n.children.splice(i, 1); c.parentNode = null; return c;
    },
    querySelector(sel) {
      const [t, cls] = sel.startsWith(".") ? [null, sel.slice(1)] : sel.split(".");
      return n.children.find((c) => (!t || c.tag === t)
        && (!cls || c.className.split(" ").includes(cls))) || null;
    },
    querySelectorAll() { return []; },
    getContext() { return { drawImage() {} }; },
    toDataURL() { return "data:image/png;base64,AAAA"; },
    addEventListener() {},
  };
  return n;
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}
const flush = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r)); };

/* A pdf.js document: getPage hands out ONE proxy per page (pdf.js caches
   them), render()/text-layer promises can be held open by the test. */
function makeDoc(numPages) {
  const pages = new Map();
  const doc = {
    numPages, holdRender: new Map(),
    getPage(num) {
      if (!pages.has(num)) {
        pages.set(num, {
          num, cleanups: 0,
          getViewport: ({ scale }) => ({ width: 600 * scale, height: 800 * scale, scale }),
          render: () => {
            const h = doc.holdRender.get(num);
            return { promise: h instanceof Error ? Promise.reject(h) : h || Promise.resolve() };
          },
          getTextContent: () => Promise.resolve({ items: [] }),
          cleanup() { this.cleanups++; return true; },
        });
      }
      return Promise.resolve(pages.get(num));
    },
    page: (num) => pages.get(num),
  };
  return doc;
}

function makePage(numPages) {
  const els = {};
  const getById = (id) => (els[id] = els[id] || el("div"));
  const thumbs = {};
  const posted = [];
  const ctx = {
    console, Math, String, parseInt, parseFloat, Number, Set, Map, JSON, Promise,
    performance: { now: () => 0 },
    document: {
      createElement: (t) => el(t),
      getElementById: getById,
      querySelector: (sel) => {
        const m = /^\.thumb\[data-page="(\d+)"\]$/.exec(sel);
        return m ? thumbs[m[1]] || null : null;
      },
    },
    window: { devicePixelRatio: 1 },
    pdfjsLib: { AnnotationMode: { DISABLE: 0 }, textHold: null },
    posted, thumbs, refreshed: [],
  };
  ctx.pdfjsLib.renderTextLayer = () => ({ promise: ctx.pdfjsLib.textHold || Promise.resolve() });
  vm.createContext(ctx);
  const doc = makeDoc(numPages);
  const pageDivs = [];
  for (let i = 1; i <= numPages; i++) {
    const d = getById("pages").appendChild(el("div"));
    d.className = "page"; d.dataset.page = String(i);
    pageDivs.push(d);
  }
  ctx.state = {
    doc, scale: 1, t0: null, pageDivs, observer: null,
    rendered: new Map(), lru: new Set(), inZone: new Set(),
    find: { query: "", matches: [], index: -1 },
    annots: [], annotsPrev: null, pendingRepaint: new Set(), pageTexts: null,
    persistMarquee: null, textEdit: null, textDrag: null,
    transport: null, task: null, currentPage: 0,
  };
  const code = PURE.replace(/if \(typeof module[\s\S]*$/, "") +
    "function post(s) { posted.push(s); }\n" +
    "function postB64() {}\n" +
    "function refreshPage(num) { refreshed.push(num); }\n" +
    "function renderAnnotLayers() {}\n" +
    "function highlightCurrentMatchIfVisible() {}\n" +
    "function applyScaleFactor() {}\n" +
    "function positionTextEdit() {}\n" +
    ["onIntersect", "touchPage", "renderPage", "teardownPage", "releaseOffscreen", "teardown",
     "relayout", "renderThumb", "copyPageImage", "renderRegionCanvas"]
      .map(fn).join("");
  vm.runInContext(code, ctx);
  return ctx;
}

const run = (ctx, js) => vm.runInContext(js, ctx);
const canvases = (div) => div.children.filter((c) => c.tag === "canvas").length;
const enter = (ctx, nums) => run(ctx, "onIntersect([" + nums.map(
  (n) => "{ target: state.pageDivs[" + (n - 1) + "], isIntersecting: true }").join(",") + "])");

const tests = [];
const check = (name, f) => tests.push([name, f]);

/* ---- #23 ---------------------------------------------------------- */
check("#23 after a panel-resize relayout every page in the render zone is drawn again", async () => {
  const p = makePage(6);
  enter(p, [1, 2, 3]);
  await flush();
  assert.deepStrictEqual([1, 2, 3].map((n) => canvases(p.state.pageDivs[n - 1])), [1, 1, 1]);
  p.state.scale = 0.8;            // the ResizeObserver's refit
  run(p, "relayout()");           // no new IntersectionObserver entry follows
  await flush();
  assert.deepStrictEqual([1, 2, 3].map((n) => canvases(p.state.pageDivs[n - 1])), [1, 1, 1],
    "in-zone pages stay blank after the relayout");
  assert.deepStrictEqual([...p.state.rendered.keys()].sort(), [1, 2, 3]);
  assert.ok([1, 2, 3].every((n) => p.state.rendered.get(n).canvas));
});

check("#23 a relayout during a first render does not render the page twice", async () => {
  const p = makePage(3);
  const hold = deferred();
  p.state.doc.holdRender.set(2, hold.promise);
  enter(p, [1, 2]);
  await flush();                  // page 2's render is in flight
  p.state.scale = 0.8;
  run(p, "relayout()");
  await flush();
  hold.resolve();
  await flush();
  assert.strictEqual(canvases(p.state.pageDivs[1]), 1, "two canvases in one page");
  assert.ok(p.state.rendered.get(2).canvas);
  assert.deepStrictEqual(p.refreshed, [2], "the stale-scale render is refreshed crisp");
});

/* ---- #32 ---------------------------------------------------------- */
check("#32 tearing an out-of-zone page down releases its pdf.js caches", async () => {
  const p = makePage(3);
  enter(p, [1]);
  await flush();
  run(p, "state.inZone.delete(1); teardownPage(1, state.pageDivs[0])");
  assert.strictEqual(p.state.doc.page(1).cleanups, 1);
  assert.strictEqual(canvases(p.state.pageDivs[0]), 0);
});

check("#32 LRU eviction releases every evicted page", async () => {
  const p = makePage(20);
  for (let n = 1; n <= 14; n++) { enter(p, [n]); await flush(); }
  // 14 rendered, none in zone any more: the 2 least recent go.
  run(p, "onIntersect([" + Array.from({ length: 14 }, (_, i) =>
    "{ target: state.pageDivs[" + i + "], isIntersecting: false }").join(",") + "])");
  assert.deepStrictEqual([1, 2].map((n) => p.state.doc.page(n).cleanups), [1, 1]);
  assert.strictEqual(p.state.doc.page(3).cleanups, 0);
});

check("#32 a relayout does not drop the caches of pages it redraws at once", async () => {
  const p = makePage(3);
  enter(p, [1]);
  await flush();
  run(p, "state.scale = 0.8; relayout()");
  await flush();
  assert.strictEqual(p.state.doc.page(1).cleanups, 0);
});

check("#32 a thumbnail render releases its page unless the main view shows it", async () => {
  const p = makePage(3);
  for (const n of [1, 2]) p.thumbs[n] = el("div");
  enter(p, [1]);
  await flush();
  await run(p, "renderThumb(1)");
  await run(p, "renderThumb(2)");
  assert.strictEqual(p.state.doc.page(1).cleanups, 0, "the rendered page was cleaned");
  assert.strictEqual(p.state.doc.page(2).cleanups, 1);
});

check("#32 page and region copies release their page unless the main view shows it", async () => {
  const p = makePage(3);
  enter(p, [1]);
  await flush();
  await run(p, "copyPageImage(1)");             // page 2, 0-based
  await run(p, "renderRegionCanvas(2, 0, 0, 10, 10)");  // page 3
  await run(p, "copyPageImage(0)");             // page 1, rendered
  assert.deepStrictEqual([1, 2, 3].map((n) => p.state.doc.page(n).cleanups), [0, 1, 1]);
});

/* ---- #33 ---------------------------------------------------------- */
check("#33 a render finishing after a document switch leaves the new document alone", async () => {
  const p = makePage(3);
  const oldDiv = p.state.pageDivs[1];
  const text = deferred();                      // old page 2 stuck in its text layer
  p.pdfjsLib.textHold = text.promise;
  enter(p, [2]);
  await flush();
  await run(p, "teardown()");
  // The new document's placeholders.
  const docB = makeDoc(3);
  p.state.doc = docB;
  for (let i = 1; i <= 3; i++) {
    const d = p.document.getElementById("pages").appendChild(el("div"));
    d.dataset.page = String(i); p.state.pageDivs.push(d);
  }
  p.pdfjsLib.textHold = null;
  text.resolve();
  await flush();
  assert.strictEqual(p.state.rendered.has(2), false, "the old render claimed page 2 of the new document");
  assert.strictEqual(p.state.lru.size, 0);
  assert.ok(oldDiv.parentNode === null);
  enter(p, [2]);
  await flush();
  assert.strictEqual(canvases(p.state.pageDivs[1]), 1, "page 2 of the new document stays blank");
});

check("#33 a failed render of a superseded document keeps the new document's claim", async () => {
  const p = makePage(3);
  const hold = deferred();
  p.state.doc.holdRender.set(2, hold.promise);
  enter(p, [2]);
  await flush();
  await run(p, "teardown()");
  p.state.doc = makeDoc(3);
  run(p, "state.rendered.set(2, {}); state.lru.add(2)");   // the new document's claim
  hold.reject(new Error("Transport destroyed"));
  await flush();
  assert.strictEqual(p.state.rendered.has(2), true, "the new claim was dropped");
  assert.strictEqual(p.state.lru.has(2), true);
  assert.ok(!p.posted.some((s) => s.startsWith("log:render")), "a superseded failure is not logged");
});

check("normal rendering is unchanged: a page renders, is listed in the LRU, logs a failure", async () => {
  const p = makePage(3);
  enter(p, [1]);
  await flush();
  assert.strictEqual(canvases(p.state.pageDivs[0]), 1);
  assert.ok(p.state.lru.has(1));
  p.state.doc.holdRender.set(2, new Error("bad page"));
  enter(p, [2]);
  await flush();
  assert.strictEqual(p.state.rendered.has(2), false);
  assert.ok(p.posted.includes("log:render 2 failed: bad page"));
});

(async () => {
  const failures = [];
  for (const [name, f] of tests) {
    try { await f(); console.log("  ok  " + name); }
    catch (e) { console.log(" FAIL " + name + "  " + e.message); failures.push(name); }
  }
  console.log("\n" + (tests.length - failures.length) + " passed, " + failures.length + " failed");
  process.exit(failures.length ? 1 : 0);
})();
