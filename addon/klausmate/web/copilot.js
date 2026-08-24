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

// K-056/K-063: the "Library..." toolbar button, mounted by plain DOM.
// The component-API route is a dead end in 26.8.1: the bundle's
// editorToolbar exports only AddonButtons (no Raw), and uiPromise /
// editorToolbar are page-lexical bindings invisible as window.*
// properties. So instead: find the native Fields... button, clone its
// className for native styling, and insert ours before it. Svelte
// rebuilds the toolbar on notetype switches and drops foreign nodes —
// the MutationObserver re-mounts (debounced; mount() bails when the
// button already exists, so re-entry is cheap and loop-free).
// Label-match is English-locale-bound; we log once when it never shows.
(function () {
  var BTN_ID = "klausmate-library-btn";
  var warned = false;

  function findFieldsButton() {
    var btns = document.querySelectorAll("button");
    for (var i = 0; i < btns.length; i++) {
      var t = (btns[i].textContent || "").trim();
      if (t === "Fields..." || t.indexOf("Fields") === 0) return btns[i];
    }
    return null;
  }

  function mount() {
    if (document.getElementById(BTN_ID)) return true;
    var fields = findFieldsButton();
    if (!fields || !fields.parentNode) return false;
    var btn = document.createElement("button");
    btn.id = BTN_ID;
    btn.type = "button";
    btn.className = fields.className;
    btn.textContent = "Library...";
    btn.title = "Choose a PDF from the Klaus Library";
    // NO listener on the node: Svelte re-renders can clone subtrees, and
    // cloneNode keeps the markup but drops addEventListener handlers —
    // a dead shell the remount observer can't distinguish from a live
    // button. The document-level capture listener below is the ONLY
    // click dispatch (a second mechanism would double-fire the toggle).
    fields.parentNode.insertBefore(btn, fields);
    console.log("[klausmate] Library button mounted");
    return true;
  }

  document.addEventListener("click", function (e) {
    var t = e.target;
    var hit = t && t.closest ? t.closest("#" + BTN_ID) : null;
    if (!hit) return;
    e.preventDefault();
    console.log("[klausmate] Library button clicked");
    try { pycmd("klausmate:library:e30="); } catch (err) { /* non-fatal */ }
  }, true);

  var tries = 0;
  var timer = setInterval(function () {
    tries += 1;
    if (mount() || tries > 75) {
      clearInterval(timer);
      if (tries > 75 && !warned) {
        warned = true;
        console.log("[klausmate] Library button: Fields... never appeared");
      }
    }
  }, 200);

  var pending = null;
  new MutationObserver(function () {
    if (pending) return;
    pending = setTimeout(function () {
      pending = null;
      mount();
    }, 200);
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
