/* Klaus curation panel logic.
 *
 * Bridge:
 *   JS → Python:  pycmd("klaus:<action>:<b64 json>")
 *     actions: ready · search {prompt,pdf,deck,create} · reindex ·
 *              cancel · close · log {msg}
 *   Python → JS:  window.klausSearch.<fn>(...)
 *     init(state) · setIndexStatus(st) · setProgress(label, done, total) ·
 *     hideProgress() · searchDone(result) · showError(msg) · setBusy(on) ·
 *     focusInput()
 */
(function () {
  "use strict";

  var els = {};
  var busy = false;
  var indexed = false;

  function $(id) { return document.getElementById(id); }

  function b64(obj) {
    return btoa(unescape(encodeURIComponent(JSON.stringify(obj || {}))));
  }

  function send(action, obj) {
    try { pycmd("klaus:" + action + ":" + b64(obj)); } catch (e) { /* no bridge */ }
  }

  function setBusy(on) {
    busy = !!on;
    els.find.disabled = busy || !indexed;
    els.create.disabled = busy || !indexed;
    els.indexNow.disabled = busy;
    els.prompt.disabled = busy;
    els.pdf.disabled = busy;
    els.deck.disabled = busy;
    if (!busy) hideProgress();
  }

  function hideProgress() {
    els.progress.classList.add("hidden");
    els.fill.classList.remove("indeterminate");
    els.fill.style.width = "0%";
  }

  function setProgress(label, done, total) {
    els.progress.classList.remove("hidden");
    els.result.classList.add("hidden");
    els.plabel.textContent = label || "";
    if (total > 0) {
      els.fill.classList.remove("indeterminate");
      els.fill.style.width = Math.min(100, Math.round(done * 100 / total)) + "%";
    } else {
      els.fill.classList.add("indeterminate");
    }
  }

  function showResult(text, isError) {
    els.result.textContent = text;
    els.result.classList.toggle("error", !!isError);
    els.result.classList.remove("hidden");
  }

  function setIndexStatus(st) {
    indexed = !!(st && st.exists && st.count > 0);
    els.gate.classList.toggle("hidden", indexed);
    els.indexStatus.classList.toggle("hidden", !indexed);
    if (indexed) {
      var txt = st.count.toLocaleString() + " cards indexed";
      if (st.ago) txt += " · updated " + st.ago;
      els.istatusText.textContent = txt;
    }
    if (!busy) setBusy(false); // refresh button enablement
  }

  function fillSelect(sel, items, keepFirst) {
    while (sel.options.length > (keepFirst ? 1 : 0)) sel.remove(keepFirst ? 1 : 0);
    (items || []).forEach(function (it) {
      var o = document.createElement("option");
      o.value = it.value;
      o.textContent = it.label;
      sel.appendChild(o);
    });
  }

  function autoGrow() {
    els.prompt.style.height = "auto";
    els.prompt.style.height = Math.min(els.prompt.scrollHeight, 120) + "px";
  }

  function doSearch(createNow) {
    if (busy || !indexed) return;
    var prompt = els.prompt.value.trim();
    var pdf = els.pdf.value;
    if (!prompt && !pdf) {
      showResult("Type a topic or pick a lecture PDF first.", true);
      els.prompt.focus();
      return;
    }
    setBusy(true);
    setProgress(createNow ? "Curating your deck…" : "Finding matching cards…", 0, 0);
    send("search", {
      prompt: prompt,
      pdf: pdf,
      deck: els.deck.value,
      create: !!createNow,
    });
  }

  window.klausSearch = {
    init: function (state) {
      fillSelect(els.pdf, state.pdfs, true);
      fillSelect(els.deck, state.decks, true);
      setIndexStatus(state.indexStatus || {});
      setBusy(false);
    },
    setIndexStatus: setIndexStatus,
    setProgress: setProgress,
    hideProgress: hideProgress,
    setBusy: setBusy,
    searchDone: function (res) {
      setBusy(false);
      if (!res || !res.count) {
        showResult("No matching cards found — try a broader prompt or a different deck scope.", false);
        return;
      }
      if (res.previewed) {
        showResult(
          res.count.toLocaleString() + " matches tagged and opened in Browse. " +
          "Prune the list there, then Notes → Klaus: Create curated deck from selection…",
          false
        );
      } else {
        showResult(res.count.toLocaleString() + " matches found.", false);
      }
    },
    showError: function (msg) {
      setBusy(false);
      showResult(msg || "Something went wrong.", true);
    },
    focusInput: function () {
      try { els.prompt.focus(); } catch (e) { /* not rendered yet */ }
    },
    reset: function () {
      els.prompt.value = "";
      els.result.classList.add("hidden");
      setBusy(false);
    },
  };

  document.addEventListener("DOMContentLoaded", function () {
    els = {
      prompt: $("prompt"),
      pdf: $("pdf"),
      deck: $("deck"),
      find: $("find"),
      create: $("create"),
      cancel: $("cancel"),
      progress: $("progress"),
      fill: $("fill"),
      plabel: $("plabel"),
      result: $("result"),
      gate: $("gate"),
      indexNow: $("index-now"),
      indexStatus: $("index-status"),
      istatusText: $("istatus-text"),
      reindex: $("reindex"),
      closeBtn: $("close-btn"),
    };

    els.find.addEventListener("click", function () { doSearch(false); });
    els.create.addEventListener("click", function () { doSearch(true); });
    els.prompt.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        doSearch(false);
      }
    });
    els.prompt.addEventListener("input", autoGrow);
    els.cancel.addEventListener("click", function () {
      els.plabel.textContent = "Cancelling…";
      send("cancel");
    });
    els.indexNow.addEventListener("click", function () {
      if (busy) return;
      setBusy(true);
      setProgress("Starting the card index…", 0, 0);
      send("reindex");
    });
    els.reindex.addEventListener("click", function (ev) {
      ev.preventDefault();
      if (busy) return;
      setBusy(true);
      setProgress("Updating the card index…", 0, 0);
      send("reindex");
    });
    els.closeBtn.addEventListener("click", function () { send("close"); });

    send("ready");
  });
})();
