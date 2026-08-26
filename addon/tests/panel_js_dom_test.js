// Behavioural test for background.panel_js() — the one piece of Klaus
// that manipulates Anki's DOM, where a source pin proves nothing.
//
// Run by tests/test_background.py when `node` is present (and honestly
// reported as skipped when it is not). Usage:
//     node tests/panel_js_dom_test.js <file containing the script body>
//
// The fake DOM models exactly the shape Anki renders, verified in
// aqt/deckbrowser.pyc:
//     <center><table>…<tr class=deck>…</table><br><div id=studiedToday>
"use strict";
const fs = require("fs");

const match = (n, sel) => {
  if (sel === "table") return n.tag === "table";
  if (sel === "br") return n.tag === "br";
  if (sel === "tr.deck") return n.tag === "tr" && n.className.includes("deck");
  if (sel === "center > table")
    return n.tag === "table" && n.parentNode && n.parentNode.tag === "center";
  throw new Error("unmodelled selector: " + sel);
};

function el(tag, cls, id) {
  const node = {
    tag, className: cls || "", id: id || "", children: [], parentNode: null,
    rows: [], colSpan: 1,
    appendChild(c) {
      if (c.parentNode) c.parentNode.drop(c);
      c.parentNode = node; node.children.push(c); return c;
    },
    drop(c) { const i = node.children.indexOf(c); if (i >= 0) node.children.splice(i, 1); },
    remove() { if (node.parentNode) node.parentNode.drop(node); node.parentNode = null; },
    insertRow() {
      const r = el("tr");
      r.insertCell = () => r.appendChild(el("td"));
      node.rows.push(r); node.appendChild(r); return r;
    },
    all() { return node.children.flatMap((c) => [c, ...c.all()]); },
    querySelector(sel) { return node.all().find((n) => match(n, sel)) || null; },
    querySelectorAll(sel) { return node.all().filter((n) => match(n, sel)); },
    closest(sel) { let n = node; while (n) { if (match(n, sel)) return n; n = n.parentNode; } return null; },
  };
  return node;
}

/** @param opts {{deckList?: boolean, stats?: boolean}} */
function build(opts) {
  const body = el("body");
  const center = body.appendChild(el("center"));
  const table = center.appendChild(el("table"));
  const row = table.insertRow();
  row.className = opts.deckList === false ? "" : "deck";
  center.appendChild(el("br"));
  const stats = opts.stats === false
    ? null : center.appendChild(el("div", "", "studiedToday"));
  global.document = {
    getElementById: (id) => body.all().find((n) => n.id === id) || null,
    querySelectorAll: (sel) => body.querySelectorAll(sel),
    createElement: (t) => el(t),
  };
  return { body, center, table, stats };
}

const src = fs.readFileSync(process.argv[2], "utf8");
const results = [];
const ok = (name, cond, detail) => results.push([name, !!cond, detail || ""]);

// 1. The deck browser: the line lands inside the table.
let d = build({});
eval(src);
ok("moved into the deck table", d.stats.closest("table") === d.table);
ok("the <br> Anki puts between them is gone", !d.center.querySelector("br"));
const last = d.table.rows[d.table.rows.length - 1];
ok("tagged tr.klaus-studied so the CSS can style it",
   last.className === "klaus-studied");
ok("spans the whole row without hardcoding Anki's column count",
   last.children[0].colSpan >= 9);

// 2. Re-render safety: Anki rebuilds this page through stdHtml, so the
//    script runs again on the same document if the node was kept.
const before = d.table.rows.length;
eval(src);
ok("idempotent — a second run adds no duplicate row",
   d.table.rows.length === before, `rows=${d.table.rows.length}`);

// 3. The overview: a <center> with a table, but no deck rows. Must not
//    be touched (its own panel was tuned separately).
d = build({ deckList: false });
eval(src);
ok("a table with no tr.deck is left alone (the overview)",
   d.stats.closest("table") === null && d.table.rows.length === 1);

// 4. Nothing to move: must not throw.
d = build({ stats: false });
let threw = false;
try { eval(src); } catch (e) { threw = true; }
ok("no studied-today line present is a silent no-op", !threw);

let failed = 0;
for (const [name, pass, detail] of results) {
  if (!pass) failed++;
  console.log(`${pass ? "  ok  " : " FAIL "}${name} ${detail}`);
}
console.log(`${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
