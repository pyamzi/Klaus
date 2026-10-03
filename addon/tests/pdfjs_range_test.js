// Behavioural test for the pdf.js page's range feed (PDF reader 2/5):
// the page's OWN feed code (b64Bytes, askRange, KlausRange — cut out of
// klaus_note/web/pdfjs_viewer.html, not copied) driven against the
// vendored pdf.js, with `pycmd` faked the way Python answers
// (pdf_source.range_reply, MAX_RANGE clamp).
//
// Run by tests/test_pdfjs_range.py when `node` is present (honestly
// reported as skipped when it is not). Usage:
//     node tests/pdfjs_range_test.js <pdfjs_viewer.html> <pdfjs dir> <pdf>
"use strict";
const fs = require("fs");
const path = require("path");
const [html, pdfPath] = [process.argv[2], process.argv[4]];
const pdfjsDir = path.resolve(process.argv[3]);

const pdfjsLib = require(pdfjsDir + "/pdf.min.js");
pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsDir + "/pdf.worker.min.js";
globalThis.pdfjsLib = pdfjsLib;

const page = fs.readFileSync(html, "utf8");
const feed = "/* ==== feed" + page.split("/* ==== feed")[1].split("window.klausPdfOpen")[0];
const file = fs.readFileSync(pdfPath);
const MAX = 1048576;

let posts = [], calls = [], mode = "ok";
globalThis.post = (m) => posts.push(m);
globalThis.pycmd = (cmd, cb) => {
  const [, , gen, b, e] = cmd.split(":");
  calls.push([+b, +e]);
  let reply;
  if (mode === "stale") reply = { stale: true };   // the file changed under the page
  else {
    const beg = Math.min(+b, file.length);
    const end = Math.max(beg, Math.min(+e, file.length, beg + MAX));
    reply = { b64: file.subarray(beg, end).toString("base64") };
  }
  setTimeout(() => cb(JSON.parse(JSON.stringify(reply))), 0);
};
const { KlausRange, b64Bytes } = new Function(feed + "\nreturn { KlausRange, b64Bytes };")();

const failures = [];
function check(name, ok, detail) {
  console.log((ok ? "  ok  " : " FAIL ") + name + (ok ? "" : "  " + (detail || "")));
  if (!ok) failures.push(name);
}

function open() {
  const first = b64Bytes(file.subarray(0, 262144).toString("base64"));
  const transport = new KlausRange(1, file.length, first);
  const asked = [];
  const orig = transport.requestDataRange.bind(transport);
  transport.requestDataRange = (b, e) => { asked.push(e - b); return orig(b, e); };
  const task = pdfjsLib.getDocument({
    range: transport, disableAutoFetch: true, disableStream: true,
    rangeChunkSize: 262144, verbosity: 0,
  });
  return { transport, task, asked };
}

(async () => {
  const { transport, task, asked } = open();
  const doc = await task.promise;
  check("the document opens through the range transport", doc.numPages === 12);
  const p1 = await doc.getPage(1);
  const text = (await p1.getTextContent()).items.map((i) => i.str).join("");
  check("page 1's text arrives", text === "Page 1", text);
  const ops = await (await doc.getPage(3)).getOperatorList();
  check("page 3's 1.6 MB content stream arrives whole", ops.fnArray.length > 100000,
        String(ops.fnArray.length));
  check("pdf.js asked for one range wider than a bridge call",
        asked.some((n) => n > MAX), JSON.stringify(asked));
  check("...and no bridge call exceeded MAX_RANGE",
        calls.every(([b, e]) => e - b <= MAX), JSON.stringify(calls));
  check("the first 256 KB was never asked for again",
        calls.every(([b]) => b >= 262144), JSON.stringify(calls));
  await task.destroy();
  check("destroy aborts the transport", transport.aborted === true);

  mode = "stale"; posts = []; calls = [];
  const s = open();
  s.task.promise.catch(() => {});
  for (let i = 0; i < 200 && !posts.includes("stale:1"); i++) {
    await new Promise((r) => setTimeout(r, 10));
  }
  check("a stale reply posts stale:<gen>", posts.includes("stale:1"), JSON.stringify(posts));
  check("...and aborts the transport", s.transport.aborted === true);
  const n = calls.length;
  await new Promise((r) => setTimeout(r, 100));
  check("...and stops asking", calls.length === n, n + " -> " + calls.length);
  await s.task.destroy();

  process.exit(failures.length ? 1 : 0);
})().catch((e) => { console.log(" FAIL harness: " + e.stack); process.exit(1); });
