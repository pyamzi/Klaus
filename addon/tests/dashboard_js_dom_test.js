// Behavioural test for klausmate/web/dashboard.js — the dashboard's
// entire DOM half (wrapping, ordering, Control-Center edit mode),
// where a source pin proves nothing.
//
// Run by tests/test_dashboard.py when `node` is present (and honestly
// reported as skipped when it is not). Usage:
//     node tests/dashboard_js_dom_test.js klausmate/web/dashboard.js
//
// The fake DOM models Anki's deck-browser shapes, verified against
// aqt/deckbrowser.pyc:
//   painted modes: <center><table><tr.deck>…<tr.klaus-studied
//                  [#studiedToday]></table><div.klaus-hm></center>
//   theme mode:    <center><table><tr.deck>…</table><br>
//                  <div id=studiedToday><div.klaus-hm></center>
// plus other add-ons' blocks, which Python (dashboard.wrap_foreign)
// already wrapped in the HTML. Custom elements count their connects:
// AMBOSS's re-renders on every one, so the page must never move them.
"use strict";
const fs = require("fs");

// ---- selector matcher: small on purpose, throws on anything the
// model does not understand — that throw IS the harness's tripwire:
// the script cannot silently query something unmodelled.
function matches(n, sel) {
  if (sel === "center > table")
    return n.tag === "table" && n.parentNode && n.parentNode.tag === "center";
  let m;
  if ((m = /^([a-z]+)\.([\w-]+)$/.exec(sel)))
    return n.tag === m[1] && hasClass(n, m[2]);
  if ((m = /^\.([\w-]+)$/.exec(sel))) return hasClass(n, m[1]);
  if (/^[a-z]+$/.test(sel)) return n.tag === sel;
  throw new Error("unmodelled selector: " + sel);
}
const hasClass = (n, c) => (n.className || "").split(/\s+/).includes(c);

// Every insertion (re)connects the subtree's custom elements, as in a
// browser: a move is a disconnect + connect.
function connected(c) {
  let root = c;
  while (root.parentNode) root = root.parentNode;
  if (root.tag !== "body" && root.tag !== "document") return; // detached: no connect
  for (const n of [c, ...c.all()]) if (n.tag.includes("-")) n.connects = (n.connects || 0) + 1;
}
// What dashboard.wrap_foreign writes around an add-on block.
function pw(id, child) {
  const w = el("div", "klaus-widget");
  w.setAttribute("data-w", id);
  w.appendChild(child);
  return w;
}
// style.order as a number (CSS order is how the page reorders).
const ord = (w) => Number(w.style.order || 0);

let SEQ = 0;
function el(tag, cls, id) {
  const node = {
    _seq: ++SEQ,
    tag,
    tagName: tag.toUpperCase(),
    className: cls || "",
    id: id || "",
    style: {},
    textContent: "",
    attrs: {},
    children: [],
    parentNode: null,
    _ls: {},
    setAttribute(k, v) { node.attrs[k] = String(v); },
    getAttribute(k) { return k in node.attrs ? node.attrs[k] : null; },
    appendChild(c) {
      if (c.parentNode) c.parentNode.removeChild(c);
      c.parentNode = node; node.children.push(c); connected(c); return c;
    },
    insertBefore(c, ref) {
      if (c.parentNode) c.parentNode.removeChild(c);
      c.parentNode = node;
      const i = ref ? node.children.indexOf(ref) : -1;
      if (i >= 0) node.children.splice(i, 0, c);
      else node.children.push(c);
      connected(c);
      return c;
    },
    removeChild(c) {
      const i = node.children.indexOf(c);
      if (i >= 0) node.children.splice(i, 1);
      c.parentNode = null; return c;
    },
    remove() { if (node.parentNode) node.parentNode.removeChild(node); },
    get nextElementSibling() {
      if (!node.parentNode) return null;
      const sib = node.parentNode.children;
      return sib[sib.indexOf(node) + 1] || null;
    },
    all() { return node.children.flatMap((c) => [c, ...c.all()]); },
    querySelector(sel) { return node.all().find((n) => matches(n, sel)) || null; },
    querySelectorAll(sel) { return node.all().filter((n) => matches(n, sel)); },
    closest(sel) {
      let n = node;
      while (n) { if (matches(n, sel)) return n; n = n.parentNode; }
      return null;
    },
    classList: {
      add(c) { if (!hasClass(node, c)) node.className = (node.className + " " + c).trim(); },
      remove(c) {
        node.className = node.className.split(/\s+/).filter((x) => x !== c).join(" ");
      },
      contains(c) { return hasClass(node, c); },
    },
    addEventListener(type, fn) { (node._ls[type] = node._ls[type] || []).push(fn); },
    getBoundingClientRect() { return { top: 0, bottom: 0, height: 0, left: 0, right: 0, width: 0 }; },
    offsetTop: 0,
  };
  return node;
}

// Two-level event model: the target's own listeners, then document's
// (all the script binds are one or the other).
function fire(target, type, extra) {
  const ev = Object.assign(
    {
      target,
      clientX: 10, clientY: 10,
      _stopped: false, _prevented: false,
      stopPropagation() { this._stopped = true; },
      preventDefault() { this._prevented = true; },
    },
    extra || {}
  );
  for (const fn of target._ls[type] || []) fn(ev);
  if (!ev._stopped && target !== DOC)
    for (const fn of DOC._ls[type] || []) fn(ev);
  return ev;
}

let DOC = null;
/** Build a deck-browser page.
 * opts: {theme: bool (studied line still a table sibling),
 *        heatmap: bool, foreign: bool, deckList: bool} */
function build(opts) {
  const body = el("body");
  const center = body.appendChild(el("center"));
  const table = center.appendChild(el("table"));
  const row = table.appendChild(el("tr", opts.deckList === false ? "" : "deck"));
  row.appendChild(el("td"));
  let studied;
  if (opts.theme) {
    center.appendChild(el("br"));
    studied = center.appendChild(el("div", "", "studiedToday"));
  } else {
    const srow = table.appendChild(el("tr", "klaus-studied"));
    studied = srow.appendChild(el("td")).appendChild(el("div", "", "studiedToday"));
  }
  let foreign = null, foreignBr = null, banner = null;
  if (opts.foreign) {
    // A banner ABOVE the table (addons do inject there) whose <br> is
    // the FIRST one in document order — so any grab that searches the
    // document instead of taking the table's own sibling takes this
    // one and fails the theme-trio case.
    banner = el("div", "foreign-banner");
    banner.appendChild(el("br"));
    center.insertBefore(pw("x:.foreign-banner", banner), table);
    foreign = el("div", "ankihub-thing");
    foreignBr = foreign.appendChild(el("br")); // a br the wrap must NOT take
    center.appendChild(pw("x:.ankihub-thing", foreign));
  }
  let hm = null;
  if (opts.heatmap !== false) hm = center.appendChild(el("div", "klaus-hm"));
  DOC = el("document");
  DOC.appendChild(body);
  global.document = {
    body,
    createElement: (t) => el(t),
    getElementById: (id) => body.all().find((n) => n.id === id) || null,
    querySelector: (sel) => body.querySelector(sel),
    querySelectorAll: (sel) => body.querySelectorAll(sel),
    addEventListener: (t, fn) => DOC.addEventListener(t, fn),
    _ls: DOC._ls,
  };
  // fire() consults DOC._ls; keep them the same object.
  DOC._ls = document._ls;
  global.window = { innerWidth: 1200, innerHeight: 900 };
  center.appendChild(el("script")); // never a widget
  global.pycmd = (msg) => SENT.push(msg);
  SENT.length = 0;
  return { body, center, table, studied, hm, foreign, foreignBr, banner };
}

const SENT = [];
const decoded = (i) => {
  const msg = SENT[i];
  if (!msg || !msg.startsWith("klausmate:dash:")) return null;
  return JSON.parse(Buffer.from(msg.slice("klausmate:dash:".length), "base64").toString("utf8"));
};

const src = fs.readFileSync(process.argv[2], "utf8");
const results = [];
const ok = (name, cond, detail) => results.push([name, !!cond, detail || ""]);
const boot = (state) => { window.klausDashState = state; eval(src); };
const widget = (id) =>
  document.querySelectorAll(".klaus-widget").find((w) => w.getAttribute("data-w") === id);

const STATE = {
  order: ["decks", "heatmap"], edit: false,
  removable: ["heatmap"], labels: { heatmap: "Review Heatmap" }, hidden: [],
};

// 1. Painted-mode page: both widgets wrapped, nothing else moved.
let d = build({});
boot(STATE);
ok("deck table lands inside the decks widget",
   d.table.closest(".klaus-widget") === widget("decks"));
ok("heatmap lands inside its own widget",
   d.hm.closest(".klaus-widget") === widget("heatmap"));
ok("wrappers live in <center>, order decks-then-heatmap",
   widget("decks").parentNode === d.center
   && ord(widget("decks")) < ord(widget("heatmap")));
ok("<center> becomes the flex column CSS order works in",
   hasClass(d.center, "klaus-dash-col"));
ok("wrappers never carry Anki's drag classes (deck / top-level-drag-row)",
   document.querySelectorAll(".klaus-widget").every(
     (w) => !hasClass(w, "deck") && !hasClass(w, "top-level-drag-row")));

// 2. Theme mode: the studied line is still a sibling — the trio
//    (table, its own <br>, #studiedToday) all travel into the widget.
d = build({ theme: true, foreign: true });
boot(STATE);
ok("theme mode: studied line travels INTO the decks widget",
   d.studied.closest(".klaus-widget") === widget("decks"));
ok("theme mode: only the table's own <br> moved — foreign <br>s stay "
   + "put, including one EARLIER in document order",
   d.foreignBr.parentNode === d.foreign
   && d.banner.querySelectorAll("br").length === 1
   && d.banner.closest(".klaus-widget") !== widget("decks")
   && widget("decks").querySelectorAll("br").length === 1);

// 3. Saved order applied: heatmap above decks.
d = build({});
boot(Object.assign({}, STATE, { order: ["heatmap", "decks"] }));
ok("saved order is applied — heatmap widget precedes decks",
   ord(widget("heatmap")) < ord(widget("decks")));

// 4. Other add-ons' blocks, pre-wrapped by Python: ordered with the
//    rest by CSS order, and NEVER moved — a custom element re-renders
//    on every connect (AMBOSS drew three cards when the page moved it).
d = build({ foreign: true });
const amb = el("amboss-component-wrapper", "", "amboss-qbank-widget");
d.center.appendChild(pw("x:amboss-qbank-widget", amb));
const before4 = d.center.children.slice();
boot(Object.assign({}, STATE, { order: ["x:amboss-qbank-widget", "heatmap", "decks"] }));
ok("an add-on's block is ordered with Klaus's widgets",
   ord(widget("x:amboss-qbank-widget")) < ord(widget("heatmap"))
   && ord(widget("heatmap")) < ord(widget("decks")), [ord(widget("x:amboss-qbank-widget")), ord(widget("heatmap"))]);
ok("...without moving it: connected once, and the add-on wrappers keep their DOM slots",
   amb.connects === 1
   && d.center.children.indexOf(widget("x:amboss-qbank-widget")) === before4.indexOf(widget("x:amboss-qbank-widget")),
   String(amb.connects));
ok("its insides are untouched", d.foreignBr.parentNode === d.foreign);
ok("each is named after its id",
   window.klausDash.label("x:amboss-qbank-widget") === "Amboss Qbank"
   && window.klausDash.label("x:.ankihub-thing") === "Ankihub Thing");

// 4a. Dragging it in edit mode swaps CSS order, never the DOM.
d = build({});
const amb2 = el("amboss-component-wrapper", "", "amboss-qbank-widget");
d.center.appendChild(pw("x:amboss-qbank-widget", amb2));
boot(Object.assign({}, STATE, { edit: true, order: ["decks", "heatmap", "x:amboss-qbank-widget"] }));
for (const id of ["decks", "heatmap", "x:amboss-qbank-widget"]) {
  const w = widget(id);
  w.getBoundingClientRect = () => {
    const m = /translateY\((-?[\d.]+)px\)/.exec(w.style.transform || "");
    const top = (ord(w) - 1) * 100 + (m ? Number(m[1]) : 0);
    return { top, bottom: top + 50, height: 50, left: 0, right: 0, width: 0 };
  };
}
const sh = widget("x:amboss-qbank-widget").querySelector(".klaus-w-shield");
fire(sh, "pointerdown", { clientY: 225, button: 0, pointerId: 1 });
fire(sh, "pointermove", { clientY: 145, pointerId: 1 });
fire(sh, "pointerup", { clientY: 145, pointerId: 1 });
ok("the drop reports the new order",
   JSON.stringify(decoded(SENT.length - 1)) === '{"action":"order","order":["decks","x:amboss-qbank-widget","heatmap"]}',
   JSON.stringify(decoded(SENT.length - 1)));
ok("...and the dragged block was never re-connected", amb2.connects === 1, String(amb2.connects));

// 4b. A hidden one stays hidden, and ＋ offers it back.
d = build({ foreign: true });
boot(Object.assign({}, STATE, { edit: true, hiddenForeign: ["x:.ankihub-thing"] }));
ok("a removed add-on block boots hidden",
   widget("x:.ankihub-thing").style.display === "none");
fire(document.querySelectorAll(".klaus-dash-bar")[0]
  .children.find((c) => c.id === "klaus-dash-add"), "click");
ok("...and ＋ names it", document.querySelectorAll(".klaus-dash-menu")[0]
  .children.some((c) => c.textContent === "Ankihub Thing"));
ok("its ⊖ is there in edit mode", widget("x:.foreign-banner").querySelectorAll(".klaus-w-remove").length === 1);

// 5. Idempotency: Anki rebuilds via stdHtml, but a double eval on one
//    document must not double-wrap.
d = build({});
boot(STATE);
boot(STATE);
ok("double eval wraps nothing twice",
   document.querySelectorAll(".klaus-widget").length === 2
   && widget("decks").querySelectorAll("table").length === 1);
ok("an already-wrapped page still reports wrap success, so a re-boot "
   + "re-applies order and edit state instead of silently degrading",
   window.klausDash.wrap() === true);

// 6. No deck rows (overview-shaped page): a complete no-op.
d = build({ deckList: false });
boot(STATE);
ok("a page with no tr.deck is left completely alone",
   document.querySelectorAll(".klaus-widget").length === 0);

// 7. Edit mode: shields on every widget, badge only on removables,
//    bar with Done, ＋ only when something is hidden.
d = build({});
boot(Object.assign({}, STATE, { edit: true }));
ok("edit boot: body carries the editing class",
   document.body.classList.contains("klaus-dash-editing"));
ok("every widget gets a shield; only the heatmap gets a delete badge",
   widget("decks").querySelectorAll(".klaus-w-shield").length === 1
   && widget("heatmap").querySelectorAll(".klaus-w-shield").length === 1
   && widget("decks").querySelectorAll(".klaus-w-remove").length === 0
   && widget("heatmap").querySelectorAll(".klaus-w-remove").length === 1);
const bar = document.querySelectorAll(".klaus-dash-bar")[0];
ok("the bar shows Done but no ＋ while nothing is hidden",
   bar && bar.children.some((c) => c.id === "klaus-dash-done")
   && !bar.children.some((c) => c.id === "klaus-dash-add"));

// 8. Badge click: widget hidden locally, remove sent, ＋ appears.
fire(widget("heatmap").querySelector(".klaus-w-remove"), "click");
ok("⊖ hides the widget locally and reports {remove, heatmap}",
   widget("heatmap").style.display === "none"
   && JSON.stringify(decoded(0)) === '{"action":"remove","id":"heatmap"}');
ok("…and the ＋ chip appears, since something is now hidden",
   document.querySelectorAll(".klaus-dash-bar")[0]
     .children.some((c) => c.id === "klaus-dash-add"));

// 9. ＋ menu lists the hidden widget; picking it sends {add}.
fire(document.querySelectorAll(".klaus-dash-bar")[0]
  .children.find((c) => c.id === "klaus-dash-add"), "click");
const addMenu = document.querySelectorAll(".klaus-dash-menu")[0];
ok("＋ opens a menu naming the hidden widget",
   addMenu && addMenu.children.some((c) => c.textContent === "Review Heatmap"));
fire(addMenu.children.find((c) => c.textContent === "Review Heatmap"), "click");
ok("picking it reports {add, heatmap}",
   JSON.stringify(decoded(1)) === '{"action":"add","id":"heatmap"}');

// 10. Done tears everything down and reports edit-off.
fire(document.querySelectorAll(".klaus-dash-bar")[0]
  .children.find((c) => c.id === "klaus-dash-done"), "click");
ok("Done removes the chrome and the editing class",
   !document.body.classList.contains("klaus-dash-editing")
   && document.querySelectorAll(".klaus-w-shield").length === 0
   && document.querySelectorAll(".klaus-w-remove").length === 0
   && document.querySelectorAll(".klaus-dash-bar").length === 0);
ok("…and reports {edit-off}",
   JSON.stringify(decoded(2)) === '{"action":"edit-off"}');

// 11. Right-click on a widget: in-page menu, native menu suppressed;
//     picking Edit enters edit mode and reports {edit-on}.
d = build({});
boot(STATE);
const evCtx = fire(d.table, "contextmenu", { clientX: 40, clientY: 40 });
ok("right-click on a widget is consumed (native menu suppressed)",
   evCtx._prevented);
const ctxMenu = document.querySelectorAll(".klaus-dash-menu")[0];
ok("…and opens the menu with Edit Widgets…",
   ctxMenu && ctxMenu.children.some((c) => c.textContent === "Edit Widgets…"));
fire(ctxMenu.children.find((c) => c.textContent === "Edit Widgets…"), "click");
ok("picking Edit enters edit mode and reports {edit-on}",
   document.body.classList.contains("klaus-dash-editing")
   && JSON.stringify(decoded(0)) === '{"action":"edit-on"}');

// 12. Esc exits edit mode.
fire(DOC, "keydown", { key: "Escape" });
ok("Esc exits edit mode and reports {edit-off}",
   !document.body.classList.contains("klaus-dash-editing")
   && JSON.stringify(decoded(1)) === '{"action":"edit-off"}');

// 13. Right-click OFF-widget falls through to Anki untouched.
d = build({});
boot(STATE);
const evOff = fire(document.body, "contextmenu", {});
ok("right-click outside the widgets is left to Anki",
   !evOff._prevented
   && document.querySelectorAll(".klaus-dash-menu").length === 0);

let failed = 0;
for (const [name, pass, detail] of results) {
  if (!pass) failed++;
  console.log(`${pass ? "  ok  " : " FAIL "}${name} ${detail}`);
}
console.log(`${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
