/* Klausmate — editor field-focus tracking + image-crop trigger.
 *
 * Ghost-text autocomplete, Cmd+K Ask, and Browse natural-language search
 * were removed — Klaus is embeddings-only now. This file just tracks which
 * field the user last focused/clicked (used for PDF page-insert targeting)
 * and opens the crop dialog on an image double-click.
 */
(function () {
  if (window.klausmate && window.klausmate.__installed) return;

  // ---- DOM helpers --------------------------------------------------------

  function deepActiveElement() {
    let el = document.activeElement;
    while (el && el.shadowRoot && el.shadowRoot.activeElement) {
      el = el.shadowRoot.activeElement;
    }
    return el;
  }

  function isEditableField(el) {
    if (!el) return false;
    return !!el.isContentEditable;
  }

  // ---- Re-entry guard (see the check at top of this IIFE) ----------------

  window.klausmate = {
    __installed: true,
  };

  // ---- Event wiring -------------------------------------------------------

  function fieldNameForEditable(el) {
    if (!el) return "";
    let n = el;
    for (let i = 0; i < 16 && n; i++) {
      if (n.nodeType !== 1) {
        n = n.parentElement || (n.getRootNode && n.getRootNode().host) || null;
        continue;
      }
      if (n.matches && n.matches(".field")) {
        const label = n.querySelector(".fname");
        if (label) {
          return (label.innerText || label.textContent || "").trim();
        }
      }
      if (n.matches && n.matches(".editor-field")) {
        const label = n.querySelector(".fname, .field-name");
        if (label) {
          return (label.innerText || label.textContent || "").trim();
        }
        if (n.dataset && n.dataset.field) {
          return String(n.dataset.field).trim();
        }
      }
      if (n.dataset && n.dataset.field) {
        return String(n.dataset.field).trim();
      }
      n = n.parentElement || (n.getRootNode && n.getRootNode().host) || null;
    }
    return "";
  }

  let lastSentField = null;

  function notifyFieldFocus(el) {
    const name = fieldNameForEditable(el);
    // mousedown and focusin both fire for an ordinary click into a field —
    // skip the second round trip when the target field hasn't changed.
    if (!name || name === lastSentField) return;
    lastSentField = name;
    try {
      const payload = btoa(
        unescape(encodeURIComponent(JSON.stringify({ field: name })))
      );
      pycmd("klausmate:focus:" + payload);
    } catch (e) { /* non-fatal */ }
  }

  document.addEventListener(
    "mousedown",
    function (ev) {
      const t = ev.target;
      if (!t || !t.closest) return;
      const field = t.closest(".field, .editor-field");
      if (!field) return;
      const editable = field.querySelector(
        "[contenteditable='true'], [contenteditable='']"
      );
      if (editable) notifyFieldFocus(editable);
    },
    true
  );

  document.addEventListener("focusin", function () {
    const el = deepActiveElement();
    const next = isEditableField(el) ? el : null;
    if (next) notifyFieldFocus(next);
  }, true);

  // Double-click on an image inside a note field opens the crop dialog.
  // composedPath() pierces the rich-text input's shadow DOM; requiring a
  // contenteditable ancestor keeps toolbar icons and the IO mask editor out.
  document.addEventListener("dblclick", function (e) {
    if (window.klausmateConfig && window.klausmateConfig.image_crop_enabled === false) return;
    const path = (e.composedPath && e.composedPath()) || [];
    let img = null;
    let inEditable = false;
    for (let i = 0; i < path.length; i++) {
      const n = path[i];
      if (!n || typeof n.tagName !== "string") continue;
      const tag = n.tagName.toUpperCase();
      if (tag === "ANKI-MATHJAX") return; // dblclick opens the MathJax editor — don't hijack
      if (!img && tag === "IMG") img = n;
      if (n.isContentEditable) inEditable = true;
    }
    if (!img || !inEditable) return;
    const src = img.getAttribute("src") || "";
    if (!src || src.indexOf("data:") === 0) return;
    // The live webview holds the percent-encoded relative filename resolved
    // against the local media server base; URL.pathname + decodeURIComponent
    // recovers the real (decoded) filename, spaces/unicode included.
    let fname = "";
    try {
      const u = new URL(src, document.baseURI);
      fname = decodeURIComponent(u.pathname.replace(/^\//, ""));
    } catch (err) {
      try { fname = decodeURIComponent(src); } catch (e2) { fname = src; }
    }
    if (!fname) return;
    e.preventDefault();
    try {
      const payload = btoa(unescape(encodeURIComponent(JSON.stringify({ fname: fname }))));
      pycmd("klausmate:crop:" + payload);
    } catch (err) { /* non-fatal */ }
  }, true);
})();

// K-056: the "Library..." toolbar button is a raw-HTML node inside the
// notetype button group; switching note types rebuilds that group and
// drops the node with it. The Python side exposes
// window.__klausmateMountLibraryButton (idempotent — bails if the button
// exists); this observer only notices the disappearance and re-mounts.
(function () {
  var pending = null;
  function check() {
    pending = null;
    var mount = window.__klausmateMountLibraryButton;
    if (mount && !document.getElementById("klausmate-library-btn")) mount(0);
  }
  new MutationObserver(function () {
    if (!pending) pending = setTimeout(check, 200);
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
