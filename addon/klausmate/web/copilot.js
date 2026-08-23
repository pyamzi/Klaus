/* Klausmate — Copilot-style ghost autocomplete for Anki editor fields.
 *
 * Strategy:
 *   1. Track the deepest active contenteditable (shadow-DOM aware).
 *   2. After debounce, request a completion when the caret is at the field end.
 *   3. Show grey italic ghost text inline at the caret (non-editable span).
 *   4. Tab accepts via insertText; Esc dismisses; typing schedules a fresh request.
 *   5. Cmd+K opens the ASK popover for free-form field edits.
 */
(function () {
  if (window.klausmate && window.klausmate.__installed) return;

  const CONFIG = Object.assign(
    {
      ask_hotkey: "Cmd+K",
      cycle_forward_hotkey: "Cmd+Shift+]",
      cycle_backward_hotkey: "Cmd+Shift+[",
      debounce_ms: 400,
      min_chars_before_trigger: 1,
      paste_cooldown_ms: 800,
      dismissal_cooldown_ms: 600,
      accept_cooldown_ms: 200,
    },
    window.klausmateConfig || {}
  );

  const state = {
    requestId: 0,
    lastShownId: -1,
    suggestion: "",
    suggestionSource: null,
    activeEl: null,
    hintEl: null,
    debounceTimer: null,
    suppressInputHide: false,
    insertingGhost: false,
    ghostShownAt: 0,
    isComposing: false,
    cooldowns: {
      lastPasteAt: 0,
      lastDismissAt: 0,
      lastDismissLen: 0,
      lastAcceptAt: 0,
    },
    // ASK popover
    askId: 0,
    askEl: null,
    askInput: null,
    askHint: null,
    askTargetEl: null,
    typingTimer: null,
    // Cycle-through-candidates state. `candidates` is the rolling list of
    // distinct completions shown for the current trigger; `candidateIndex`
    // is the one currently visible. Reset on every fresh auto-trigger.
    candidates: [],
    candidateIndex: 0,
    cycleField: null,           // the field these candidates belong to
    cycleFieldText: "",         // the field text at the time of the trigger
    variantRequestId: 0,
  };

  const ASK_HOTKEY = parseHotkey(CONFIG.ask_hotkey);
  const CYCLE_FORWARD_HOTKEY = parseHotkey(CONFIG.cycle_forward_hotkey);
  const CYCLE_BACKWARD_HOTKEY = parseHotkey(CONFIG.cycle_backward_hotkey);

  // ---- Hotkey parsing -----------------------------------------------------

  function parseHotkey(spec) {
    if (!spec) return null;
    const parts = String(spec).split("+").map(function (p) { return p.trim().toLowerCase(); });
    if (parts.length === 0) return null;
    const key = parts[parts.length - 1];
    return {
      ctrl: parts.includes("ctrl") || parts.includes("control"),
      shift: parts.includes("shift"),
      alt: parts.includes("alt") || parts.includes("option"),
      meta: parts.includes("cmd") || parts.includes("meta") || parts.includes("command"),
      key: key === "space" ? " " : key,
    };
  }

  function matchesHotkey(e, h) {
    if (!h) return false;
    if (!!e.ctrlKey !== h.ctrl) return false;
    if (!!e.shiftKey !== h.shift) return false;
    if (!!e.altKey !== h.alt) return false;
    if (!!e.metaKey !== h.meta) return false;
    const k = (e.key || "").toLowerCase();
    return k === h.key;
  }

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

  function getSelectionInElement(el) {
    let sel = null;
    const root = el.getRootNode();
    if (root && typeof root.getSelection === "function") {
      sel = root.getSelection();
    }
    if (!sel) sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return null;
    return sel;
  }

  function getCaretRect(sel) {
    const range = sel.getRangeAt(0).cloneRange();
    range.collapse(true);
    let rect = range.getBoundingClientRect();
    if (!rect || (rect.width === 0 && rect.height === 0 && rect.top === 0)) {
      const marker = document.createElement("span");
      marker.textContent = "​";
      range.insertNode(marker);
      rect = marker.getBoundingClientRect();
      marker.parentNode.removeChild(marker);
      sel.removeAllRanges();
      sel.addRange(range);
    }
    return rect;
  }

  function normalizeFieldText(t) {
    return (t || "").replace(/\u00a0/g, " ");
  }

  function getFieldText(el) {
    if (!el) return "";
    try {
      const clone = el.cloneNode(true);
      removeGhostSpansFrom(clone);
      return clone.innerText || clone.textContent || "";
    } catch (e) {
      return el.innerText || el.textContent || "";
    }
  }

  function fieldMatchesSnapshot(el, snapshot) {
    if (snapshot === undefined || snapshot === null) return true;
    return normalizeFieldText(getFieldText(el)) === normalizeFieldText(snapshot);
  }

  // #region agent log
  function dbgLog(location, message, data, hypothesisId) {
    const payload = {
      sessionId: "16d0b4",
      location: location,
      message: message,
      data: data || {},
      hypothesisId: hypothesisId || "?",
      timestamp: Date.now(),
      runId: "midword-fix-v2",
    };
    try {
      fetch(
        "http://127.0.0.1:7295/ingest/208e56a5-65d7-4cd6-a8e3-cd978cfaf998",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Debug-Session-Id": "16d0b4",
          },
          body: JSON.stringify(payload),
        }
      ).catch(function () {});
    } catch (e) { /* non-fatal */ }
    try {
      const b64 = btoa(
        unescape(encodeURIComponent(JSON.stringify(payload)))
      );
      pycmd("klausmate:dbg:" + b64);
    } catch (e2) { /* non-fatal */ }
  }
  // #endregion

  function canShowCompletion() {
    if (!state.activeEl || !isEditableField(state.activeEl)) return false;
    if (state.cycleField !== state.activeEl) return false;
    if (!fieldMatchesSnapshot(state.activeEl, state.cycleFieldText)) {
      return false;
    }
    if (!shouldTrigger(state.activeEl)) return false;
    return true;
  }

  // ---- Ghost text (inline span at caret) ----------------------------------

  const GHOST_ATTR = "data-klausmate-ghost";

  function ensureHintEl() {
    if (!state.hintEl) {
      state.hintEl = document.createElement("span");
      state.hintEl.className = "klausmate-hint";
      document.body.appendChild(state.hintEl);
    }
  }

  function removeGhostSpansFrom(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll("[" + GHOST_ATTR + "]").forEach(function (n) {
      if (n.parentNode) n.parentNode.removeChild(n);
    });
  }

  function cancelDebounce() {
    if (state.debounceTimer) {
      clearTimeout(state.debounceTimer);
      state.debounceTimer = null;
    }
  }

  function applyGhostInlineStyles(el) {
    const dark = window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches;
    el.style.color = dark
      ? "rgba(180, 180, 180, 0.65)"
      : "rgba(140, 140, 140, 0.85)";
    el.style.fontStyle = "italic";
    el.style.fontFamily = "inherit";
    el.style.fontSize = "inherit";
    el.style.fontWeight = "normal";
    el.style.whiteSpace = "pre-wrap";
    el.style.wordBreak = "break-word";
    el.style.background = "transparent";
    el.style.pointerEvents = "none";
    el.style.userSelect = "none";
  }

  function fieldContainerOf(el) {
    // Walk up from the editable to the nearest visible field container so
    // the hint can anchor outside the editable's text flow.
    if (!el) return null;
    let n = el;
    for (let i = 0; i < 6 && n; i++) {
      if (n.matches && n.matches(".editor-field, .editing-area, .editor-field-container")) {
        return n;
      }
      n = n.parentElement;
    }
    return el;
  }

  /** Bordered field chrome for Ask popover width (prefer .editor-field). */
  function getFieldChromeRect(editable) {
    if (!editable) return null;
    let n = editable;
    let chrome = null;
    for (let i = 0; i < 12 && n; i++) {
      if (n.nodeType === 1 && n.matches) {
        if (n.matches(".editor-field")) {
          chrome = n;
          break;
        }
        if (!chrome && n.matches(".editor-field-container")) {
          chrome = n;
        }
      }
      if (n.parentElement) {
        n = n.parentElement;
      } else if (n.getRootNode && n.getRootNode().host) {
        n = n.getRootNode().host;
      } else {
        break;
      }
    }
    const target = chrome || fieldContainerOf(editable) || editable;
    return target.getBoundingClientRect();
  }

  function applyFieldTypography(editable, targets) {
    if (!editable || !targets || !targets.length) return;
    try {
      const cs = window.getComputedStyle(editable);
      targets.forEach(function (el) {
        if (!el) return;
        el.style.fontFamily = cs.fontFamily;
        el.style.fontSize = cs.fontSize;
        el.style.lineHeight = cs.lineHeight;
        el.style.color = cs.color;
      });
    } catch (e) { /* non-fatal */ }
  }

  function placeHintNearField(field) {
    if (!field) return;
    ensureHintEl();
    const rect = field.getBoundingClientRect();
    state.hintEl.style.lineHeight = "16px";
    state.hintEl.style.height = "16px";
    state.hintEl.style.display = "block";
    // Anchor at the field's bottom-right, just below the box, never overlapping.
    state.hintEl.style.left = (rect.right - state.hintEl.offsetWidth) + "px";
    state.hintEl.style.top = (rect.bottom + 4) + "px";
  }

  function repositionHint() {
    if (!state.suggestion || !state.activeEl) return;
    const field = fieldContainerOf(state.activeEl);
    if (field) placeHintNearField(field);
  }

  function showGhost(text, source, mode) {
    if (!text || !state.activeEl || !isEditableField(state.activeEl)) return;
    if (mode !== "thinking" && !canShowCompletion()) return;

    const sel = getSelectionInElement(state.activeEl);
    if (!sel || sel.rangeCount === 0) return;

    removeGhostSpansFrom(state.activeEl);

    const range = sel.getRangeAt(0).cloneRange();
    range.collapse(true);

    const span = document.createElement("span");
    span.className = "klausmate-ghost";
    span.setAttribute(GHOST_ATTR, "1");
    span.setAttribute("contenteditable", "false");
    applyGhostInlineStyles(span);
    span.textContent = text;

    state.suggestion = text;
    state.suggestionSource = source || null;
    state.ghostShownAt = Date.now();
    state.insertingGhost = true;

    try {
      state.suppressInputHide = true;
      range.insertNode(span);
    } catch (e) {
      state.suppressInputHide = false;
      state.insertingGhost = false;
      state.suggestion = "";
      state.suggestionSource = null;
      return;
    }

    const before = document.createRange();
    before.setStartBefore(span);
    before.collapse(true);
    sel.removeAllRanges();
    sel.addRange(before);

    setTimeout(function () {
      state.suppressInputHide = false;
      state.insertingGhost = false;
    }, 0);

    if (mode === "thinking") {
      if (state.hintEl) state.hintEl.style.display = "none";
      return;
    }

    ensureHintEl();
    let hint = "Tab to accept";
    if (state.candidates.length > 1) {
      hint += " · " + (state.candidateIndex + 1) + " of " + state.candidates.length;
    }
    state.hintEl.textContent = hint;
    state.hintEl.style.display = "block";
    placeHintNearField(fieldContainerOf(state.activeEl));
  }

  function hideGhost() {
    state.suggestion = "";
    state.suggestionSource = null;
    if (state.activeEl) removeGhostSpansFrom(state.activeEl);
    removeGhostSpansFrom(document);
    if (state.hintEl) state.hintEl.style.display = "none";
  }

  function dismissGhost() {
    state.cooldowns.lastDismissAt = Date.now();
    state.cooldowns.lastDismissLen = state.activeEl
      ? getFieldText(state.activeEl).length
      : 0;
    hideGhost();
  }

  function acceptGhost() {
    if (!state.suggestion || !state.activeEl) return false;
    const text = state.suggestion;
    const span = state.activeEl.querySelector("[" + GHOST_ATTR + "]");
    if (span && span.parentNode) span.parentNode.removeChild(span);
    state.suggestion = "";
    state.suggestionSource = null;
    if (state.hintEl) state.hintEl.style.display = "none";
    try {
      state.activeEl.focus();
      document.execCommand("insertText", false, text);
    } catch (e) {
      const sel = getSelectionInElement(state.activeEl);
      if (!sel || sel.rangeCount === 0) return false;
      const range = sel.getRangeAt(0);
      range.deleteContents();
      range.insertNode(document.createTextNode(text));
      range.collapse(false);
      sel.removeAllRanges();
      sel.addRange(range);
      state.activeEl.dispatchEvent(new InputEvent("input", { bubbles: true }));
    }
    state.cooldowns.lastAcceptAt = Date.now();
    return true;
  }

  function caretAtEndIgnoringGhost(el, sel) {
    if (!sel || sel.rangeCount === 0) return true;
    const r = sel.getRangeAt(0);
    if (!r.collapsed) return false;
    try {
      const after = document.createRange();
      after.selectNodeContents(el);
      after.setStart(r.endContainer, r.endOffset);
      const frag = after.cloneContents();
      const ghosts = frag.querySelectorAll
        ? frag.querySelectorAll("[" + GHOST_ATTR + "]")
        : [];
      ghosts.forEach(function (g) {
        if (g.parentNode) g.parentNode.removeChild(g);
      });
      return (frag.textContent || "").length === 0;
    } catch (e) {
      return true;
    }
  }

  // ---- Auto-trigger gates -------------------------------------------------

  function caretAtEnd(el, sel) {
    if (!sel || sel.rangeCount === 0) return true;
    const r = sel.getRangeAt(0);
    if (!r.collapsed) return false;
    // Compare caret position against end of the field by extending a range
    // from the caret to the end and checking if any text follows.
    const after = document.createRange();
    after.selectNodeContents(el);
    after.setStart(r.endContainer, r.endOffset);
    return after.toString().length === 0;
  }

  function atWordBoundary(el, sel) {
    if (!sel || sel.rangeCount === 0) return true;
    const r = sel.getRangeAt(0);
    const before = document.createRange();
    before.selectNodeContents(el);
    before.setEnd(r.endContainer, r.endOffset);
    const left = before.toString();
    if (!left.length) return true;
    return /\s/.test(left[left.length - 1]);
  }

  function shouldTrigger(field) {
    if (!field || !isEditableField(field)) return false;
    // Master switch — settings panel sets autocomplete_enabled = false to
    // turn ghost text off entirely while leaving the rest of Klaus intact.
    if (CONFIG.autocomplete_enabled === false) return false;
    if (state.isComposing) return false;
    if (askIsOpen()) return false;
    const text = getFieldText(field);
    const trimmed = text.trim();
    if (trimmed.length === 0) return false;
    if (trimmed.length < (CONFIG.min_chars_before_trigger | 0)) return false;
    const sel = getSelectionInElement(field);
    if (!sel) return false;
    if (sel.toString && sel.toString().length > 0) return false;
    if (!caretAtEnd(field, sel)) return false;
    if (!atWordBoundary(field, sel)) return false;
    const now = Date.now();
    if (now - state.cooldowns.lastPasteAt < CONFIG.paste_cooldown_ms) return false;
    if (now - state.cooldowns.lastAcceptAt < CONFIG.accept_cooldown_ms) return false;
    if (now - state.cooldowns.lastDismissAt < CONFIG.dismissal_cooldown_ms) {
      if (Math.abs(text.length - state.cooldowns.lastDismissLen) <= 5) {
        return false;
      }
    }
    return true;
  }

  function scheduleCompletion() {
    if (state.debounceTimer) {
      clearTimeout(state.debounceTimer);
      state.debounceTimer = null;
    }
    const field = state.activeEl;
    if (!shouldTrigger(field)) return;
    state.debounceTimer = setTimeout(function () {
      state.debounceTimer = null;
      if (!shouldTrigger(state.activeEl)) return;
      requestCompletion();
    }, CONFIG.debounce_ms | 0);
  }

  // ---- Completion request -------------------------------------------------
  //
  // Auto-fired by `scheduleCompletion` once `shouldTrigger` passes. Each call
  // bumps `state.requestId`, so a later request always wins over an earlier
  // in-flight response (stale-check in onCompletion).

  function requestCompletion(opts) {
    // opts = { avoid: [string], variant: bool }
    // Without opts, this is a fresh trigger (input/idle) — reset candidates.
    if (!state.activeEl || !isEditableField(state.activeEl)) return;
    // Adopt the currently-focused editable as the target even if focus
    // changed since the last input event (the user may have just clicked
    // into a different field).
    const live = deepActiveElement();
    if (isEditableField(live)) state.activeEl = live;

    const text = normalizeFieldText(getFieldText(state.activeEl));
    const isVariant = !!(opts && opts.variant);
    hideGhost();
    cancelDebounce();
    if (!isVariant) {
      if (!shouldTrigger(state.activeEl)) return;
      // Fresh trigger — start a new candidate stream tied to THIS field
      // and field-text snapshot. Future cycle-forward presses will append.
      state.candidates = [];
      state.candidateIndex = 0;
      state.cycleField = state.activeEl;
      state.cycleFieldText = text;
    } else if (!fieldMatchesSnapshot(state.activeEl, state.cycleFieldText)) {
      return;
    }
    const payloadObj = { text: text };
    if (isVariant) {
      state.variantRequestId += 1;
      payloadObj.id = state.variantRequestId;
      payloadObj.variant = true;
      if (opts.avoid && opts.avoid.length) {
        payloadObj.avoid = opts.avoid;
      }
    } else {
      state.requestId += 1;
      payloadObj.id = state.requestId;
    }
    const id = payloadObj.id;
    const payload = btoa(unescape(encodeURIComponent(JSON.stringify(payloadObj))));
    try {
      pycmd("klausmate:complete:" + payload);
    } catch (e) {
      hideGhost();
    }
  }

  function cycleSuggestion(direction) {
    // direction = +1 (next) or -1 (previous)
    if (!state.activeEl || !isEditableField(state.activeEl)) return;
    // If the active field changed since the candidates were generated, or
    // the user has typed enough to invalidate them, ignore the press.
    if (
      state.cycleField !== state.activeEl ||
      getFieldText(state.activeEl) !== state.cycleFieldText
    ) {
      return;
    }
    if (state.candidates.length === 0) return;

    if (direction > 0) {
      if (state.candidateIndex < state.candidates.length - 1) {
        state.candidateIndex += 1;
        renderCurrentCandidate();
      } else {
        // At the end — fetch a fresh variant that avoids what's already
        // been shown. A "thinking…" ghost gives immediate feedback.
        const avoid = state.candidates.map(function (c) { return c.text; });
        requestCompletion({ variant: true, avoid: avoid });
      }
    } else {
      if (state.candidateIndex > 0) {
        state.candidateIndex -= 1;
        renderCurrentCandidate();
      }
      // Already at the first — silent no-op (no wrap).
    }
  }

  function renderCurrentCandidate() {
    const c = state.candidates[state.candidateIndex];
    if (!c) return;
    if (!canShowCompletion()) {
      hideGhost();
      return;
    }
    state.suggestion = c.text;
    state.suggestionSource = c.source;
    showGhost(c.text, c.source);
  }

  // ---- Cmd+K inline ask --------------------------------------------------

  function ensureAskEl() {
    if (state.askEl) return;
    const wrap = document.createElement("div");
    wrap.className = "klausmate-ask";
    const icon = document.createElement("span");
    icon.className = "klausmate-ask__icon";
    icon.textContent = "Ask";
    const input = document.createElement("input");
    input.type = "text";
    input.className = "klausmate-ask__input";
    input.placeholder = "Ask Klaus to write";
    input.autocomplete = "off";
    input.spellcheck = false;
    const hint = document.createElement("span");
    hint.className = "klausmate-ask__hint";
    hint.textContent = "↵ run · Esc cancel";
    wrap.appendChild(icon);
    wrap.appendChild(input);
    wrap.appendChild(hint);
    document.body.appendChild(wrap);
    state.askEl = wrap;
    state.askInput = input;
    state.askHint = hint;

    input.addEventListener("keydown", function (e) {
      // Prevent the document-level keydown handler from re-interpreting these.
      if (e.key === "Enter") {
        e.preventDefault();
        e.stopPropagation();
        submitAsk();
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        closeAsk();
        return;
      }
      // Don't let Tab leak out of the popover.
      if (e.key === "Tab") {
        e.preventDefault();
        e.stopPropagation();
      }
    }, true);
  }

  function openAsk() {
    const el = deepActiveElement();
    if (!isEditableField(el)) return;
    state.activeEl = el;
    state.askTargetEl = el;
    hideGhost();
    cancelTyping();
    ensureAskEl();

    // Bottom-attached layout: render the popover as a panel glued to the
    // bottom of the focused field, matching its width — looks like the
    // field grew a tail. fieldContainerOf is shadow-DOM safe.
    state.askEl.style.display = "flex";
    state.askInput.value = "";
    state.askHint.textContent = "↵ run · Esc cancel";
    repositionAsk();
    setTimeout(function () { state.askInput.focus(); }, 0);
  }

  function repositionAsk() {
    if (!state.askEl || state.askEl.style.display === "none") return;
    const anchor = state.askTargetEl || state.activeEl;
    if (!anchor) return;
    const rect = getFieldChromeRect(anchor);
    if (!rect) return;
    state.askEl.style.left = rect.left + "px";
    state.askEl.style.top = rect.bottom + "px";
    state.askEl.style.width = rect.width + "px";
    state.askEl.style.minWidth = "0";
    state.askEl.style.maxWidth = "none";
    applyFieldTypography(anchor, [state.askEl, state.askInput]);
    try {
      const cs = window.getComputedStyle(anchor);
      const bg = cs.backgroundColor;
      if (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") {
        state.askEl.style.backgroundColor = bg;
      }
    } catch (e) { /* non-fatal */ }
  }

  function closeAsk() {
    if (!state.askEl) return;
    state.askEl.style.display = "none";
    if (state.askTargetEl) {
      try { state.askTargetEl.focus(); } catch (e) {}
    }
  }

  function submitAsk() {
    const text = (state.askInput.value || "").trim();
    if (!text) return;
    state.askId += 1;
    const id = state.askId;
    state.askHint.textContent = "thinking…";
    const fieldText = state.askTargetEl ? getFieldText(state.askTargetEl) : "";
    const payload = btoa(unescape(encodeURIComponent(
      JSON.stringify({ id: id, prompt: text, text: fieldText })
    )));
    try {
      pycmd("klausmate:ask:" + payload);
    } catch (e) {}
  }

  function cancelTyping() {
    if (state.typingTimer) {
      clearInterval(state.typingTimer);
      state.typingTimer = null;
    }
  }

  function typeInto(el, text, replaceField) {
    cancelTyping();
    if (!text || !el) return;
    try { el.focus(); } catch (e) {}
    if (replaceField) {
      try {
        document.execCommand("selectAll", false, null);
        document.execCommand("insertText", false, text);
      } catch (e) {
        el.textContent = text;
        el.dispatchEvent(new InputEvent("input", { bubbles: true }));
      }
      return;
    }
    let i = 0;
    const charDelayMs = 12;
    state.typingTimer = setInterval(function () {
      if (i >= text.length) {
        cancelTyping();
        return;
      }
      // Insert in small bursts so very long outputs don't take forever.
      const burst = text.slice(i, i + 2);
      i += burst.length;
      try {
        document.execCommand("insertText", false, burst);
      } catch (e) {
        cancelTyping();
      }
    }, charDelayMs);
  }

  // ---- Public API for Python callback ------------------------------------

  function stripAllGhosts() {
    removeGhostSpansFrom(document);
    hideGhost();
  }

  window.klausmate = {
    __installed: true,
    stripAllGhosts: stripAllGhosts,
    onCompletion: function (data) {
      if (!data) return;
      if (data.variant) {
        if (data.id !== state.variantRequestId) {
          return;
        }
        if (!canShowCompletion()) {
          hideGhost();
          return;
        }
        if (
          data.field_text !== undefined &&
          !fieldMatchesSnapshot(state.activeEl, data.field_text)
        ) {
          hideGhost();
          return;
        }
      } else {
        if (data.id !== state.requestId) {
          // #region agent log
          dbgLog(
            "onCompletion",
            "stale request id",
            { got: data.id, want: state.requestId },
            "A"
          );
          // #endregion
          return;
        }
        if (!canShowCompletion()) {
          // #region agent log
          dbgLog(
            "onCompletion",
            "stale field snapshot",
            {
              tail: (getFieldText(state.activeEl) || "").slice(-40),
              snap: (state.cycleFieldText || "").slice(-40),
              resp: (data.field_text || "").slice(-40),
            },
            "B"
          );
          // #endregion
          hideGhost();
          return;
        }
        if (
          data.field_text !== undefined &&
          !fieldMatchesSnapshot(state.activeEl, data.field_text)
        ) {
          // #region agent log
          dbgLog(
            "onCompletion",
            "response field_text mismatch",
            {
              tail: (getFieldText(state.activeEl) || "").slice(-40),
              resp: (data.field_text || "").slice(-40),
            },
            "C"
          );
          // #endregion
          hideGhost();
          return;
        }
      }
      if (!shouldTrigger(state.activeEl)) {
        hideGhost();
        return;
      }
      state.lastShownId = data.id;
      const completion = (data.completion || "").trim();
      if (!completion) {
        // Variant request that came back empty — stay on the current
        // candidate rather than blanking the ghost mid-cycle.
        if (data.variant && state.candidates.length > 0) {
          renderCurrentCandidate();
        } else {
          hideGhost();
        }
        return;
      }
      // Maintain the rolling candidate list for cycling. Variants append;
      // first-shot replaces.
      if (data.variant) {
        // Skip duplicate completions so cycling doesn't show the same text
        // twice in a row (e.g., if the model ignored the AVOID block).
        const duplicate = state.candidates.some(function (c) {
          return c.text === completion;
        });
        if (!duplicate) {
          state.candidates.push({ text: completion, source: data.source });
          state.candidateIndex = state.candidates.length - 1;
        } else if (state.candidates.length > 0) {
          // Stay on the most recently shown one.
          state.candidateIndex = state.candidates.length - 1;
        }
      } else {
        state.candidates = [{ text: completion, source: data.source }];
        state.candidateIndex = 0;
      }
      renderCurrentCandidate();
    },
    onAskResult: function (data) {
      if (!data) return;
      if (data.id !== state.askId) return; // stale
      closeAsk();
      const text = (data.text || "").trim();
      if (!text) return;
      typeInto(state.askTargetEl, text);
    },
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

  function notifyFieldFocus(el) {
    const name = fieldNameForEditable(el);
    if (!name) return;
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
    // If focus moved to a *different* editable field, wipe any ghost left
    // behind in the previous field — otherwise the ghost would persist in a
    // field the user is no longer editing.
    if (state.activeEl && state.activeEl !== next) {
      removeGhostSpansFrom(state.activeEl);
      hideGhost();
    }
    if (next) {
      state.activeEl = next;
      notifyFieldFocus(next);
    } else {
      state.activeEl = null;
      hideGhost();
    }
  }, true);

  document.addEventListener("focusout", function () {
    // The field is losing focus — drop the ghost immediately. Anki commits
    // the field's HTML on blur, so any leftover ghost span would otherwise
    // get saved into the card. If focus moves to another editable field,
    // focusin will set state.activeEl again and a fresh suggestion will be
    // scheduled normally.
    stripAllGhosts();
    setTimeout(function () {
      const el = deepActiveElement();
      if (!isEditableField(el)) {
        state.activeEl = null;
      }
    }, 0);
  }, true);

  document.addEventListener("input", function () {
    const el = deepActiveElement();
    if (!isEditableField(el)) return;
    state.activeEl = el;
    if (state.suppressInputHide) return;
    hideGhost();
    if (!shouldTrigger(el)) {
      state.requestId += 1;
      cancelDebounce();
      return;
    }
    scheduleCompletion();
  }, true);

  document.addEventListener("selectionchange", function () {
    if (!state.activeEl) return;
    if (state.insertingGhost) return;
    if (Date.now() - state.ghostShownAt < 200) return;
    if (!state.suggestion && !(state.activeEl.querySelector &&
        state.activeEl.querySelector("[" + GHOST_ATTR + "]"))) {
      return;
    }
    const sel = getSelectionInElement(state.activeEl);
    if (!sel) return;
    if (sel.toString && sel.toString().length > 0) {
      hideGhost();
      return;
    }
    if (!caretAtEndIgnoringGhost(state.activeEl, sel)) {
      hideGhost();
    }
  });

  document.addEventListener("compositionstart", function () {
    state.isComposing = true;
    if (state.debounceTimer) {
      clearTimeout(state.debounceTimer);
      state.debounceTimer = null;
    }
  }, true);

  document.addEventListener("compositionend", function () {
    state.isComposing = false;
    scheduleCompletion();
  }, true);

  document.addEventListener("paste", function () {
    state.cooldowns.lastPasteAt = Date.now();
  }, true);

  function askIsOpen() {
    return state.askEl && state.askEl.style.display !== "none";
  }

  document.addEventListener("keydown", function (e) {
    // Esc dismisses the ASK popover. Handled here at capture-phase on
    // document so Anki's Qt-level shortcut (which closes the Add window
    // on Esc) doesn't steal it first.
    if (e.key === "Escape" && askIsOpen()) {
      closeAsk();
      e.preventDefault();
      e.stopImmediatePropagation();
      return;
    }

    // ASK popover hotkey (default Cmd+K). Settings panel can disable
    // this without affecting autocomplete by setting ask_enabled = false.
    if (CONFIG.ask_enabled !== false && matchesHotkey(e, ASK_HOTKEY)) {
      const el = deepActiveElement();
      if (isEditableField(el)) {
        e.preventDefault();
        e.stopPropagation();
        openAsk();
        return;
      }
    }

    // Cycle suggestions: Cmd+Shift+] next / Cmd+Shift+[ previous. Only
    // active when there's at least one candidate from the current trigger.
    if (matchesHotkey(e, CYCLE_FORWARD_HOTKEY)) {
      if (state.candidates.length > 0) {
        e.preventDefault();
        e.stopPropagation();
        cycleSuggestion(+1);
        return;
      }
    }
    if (matchesHotkey(e, CYCLE_BACKWARD_HOTKEY)) {
      if (state.candidates.length > 0) {
        e.preventDefault();
        e.stopPropagation();
        cycleSuggestion(-1);
        return;
      }
    }

    // Stop an in-flight typing animation with Esc.
    if (e.key === "Escape" && state.typingTimer) {
      cancelTyping();
      e.preventDefault();
      e.stopPropagation();
      return;
    }

    // Instant dismiss: any typing key hides ghost before input fires.
    if (state.suggestion && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const k = e.key || "";
      if (k.length === 1 && k !== "Tab") {
        hideGhost();
        cancelDebounce();
        state.requestId += 1;
      }
    }
    if (!e.ctrlKey && !e.metaKey && !e.altKey) {
      const k = e.key || "";
      if (k.length === 1 && k !== "Tab" && state.activeEl) {
        const sel = getSelectionInElement(state.activeEl);
        if (sel && !atWordBoundary(state.activeEl, sel)) {
          state.requestId += 1;
          cancelDebounce();
        }
      }
    }

    if (e.key === "Tab" && state.suggestion) {
      if (acceptGhost()) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }

    if (e.key === "Escape" && state.suggestion) {
      dismissGhost();
      e.preventDefault();
      e.stopPropagation();
      return;
    }

    if (
      state.suggestion &&
      (e.key === "ArrowLeft" ||
        e.key === "ArrowRight" ||
        e.key === "ArrowUp" ||
        e.key === "ArrowDown" ||
        e.key === "Enter")
    ) {
      hideGhost();
    }
  }, true);

  let _layoutTickQueued = false;
  function _scheduleLayoutTick() {
    if (_layoutTickQueued) return;
    _layoutTickQueued = true;
    requestAnimationFrame(function () {
      _layoutTickQueued = false;
      repositionHint();
      repositionAsk();
      const fields = findFieldContainers();
      for (let i = 0; i < fields.length; i++) {
        const f = fields[i];
        if (f.__klausmate_btn) anchorToFieldIcons(f, f.__klausmate_btn);
      }
    });
  }
  window.addEventListener("scroll", _scheduleLayoutTick, true);
  window.addEventListener("resize", _scheduleLayoutTick, true);

  // Click outside the ASK popover dismisses it. We don't preventDefault —
  // the click should still land where the user aimed; closing is enough.
  document.addEventListener("mousedown", function (e) {
    if (!askIsOpen()) return;
    const path = (e.composedPath && e.composedPath()) || [];
    for (let i = 0; i < path.length; i++) {
      if (path[i] === state.askEl) return; // inside popover
    }
    closeAsk();
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
