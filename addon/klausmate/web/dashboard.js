/* Klaus dashboard — Control-Center-style widget editing for Anki's
 * deck-browser page. Injected by klausmate/dashboard.py as a body
 * <script src>, AFTER background.panel_js in body order (that weld must
 * finish while `center > table` still matches, before the table is
 * wrapped here). The page is fully rebuilt by stdHtml on every deck
 * refresh, so this runs fresh each time and must be idempotent.
 *
 * Contract with Python: window.klausDashState carries {order, edit,
 * removable, labels, hidden}; every mutation is reported over
 * pycmd("klausmate:dash:<b64 json>") and VALIDATED there — nothing this
 * file sends is trusted. Any failure inside boot() leaves Anki's stock
 * layout untouched.
 *
 * Interaction rules enforced here (see dashboard.py's docstring):
 * - Edit mode overlays every widget with a shield so deck clicks,
 *   gears, shift-select, Anki's jQuery deck-row drag and the heatmap's
 *   day clicks are unreachable while jiggling (iOS semantics).
 * - Dragging is pointer-events only: HTML5 DnD is dead on this screen
 *   (MainWebView.dragEnterEvent swallows non-file drags).
 * - Widgets never carry class "deck"/"top-level-drag-row", so Anki's
 *   own jQuery-UI bindings never see them.
 */
(function () {
  "use strict";

  var editing = false;
  var dragState = null;
  var removable = [];
  var labels = {};
  var hidden = [];
  var hiddenForeign = [];
  var savedOrder = [];

  /* --- bridge ------------------------------------------------------ */

  // Manual base64: the payload is compact ASCII JSON, and spelling the
  // encoder out keeps the node test harness btoa-free.
  var B64 =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  function b64(str) {
    var out = "";
    for (var i = 0; i < str.length; i += 3) {
      var a = str.charCodeAt(i);
      var b = i + 1 < str.length ? str.charCodeAt(i + 1) : NaN;
      var c = i + 2 < str.length ? str.charCodeAt(i + 2) : NaN;
      out += B64[a >> 2];
      out += B64[((a & 3) << 4) | (isNaN(b) ? 0 : b >> 4)];
      out += isNaN(b) ? "=" : B64[((b & 15) << 2) | (isNaN(c) ? 0 : c >> 6)];
      out += isNaN(c) ? "=" : B64[c & 63];
    }
    return out;
  }

  function send(obj) {
    try {
      pycmd("klausmate:dash:" + b64(JSON.stringify(obj)));
    } catch (e) {}
  }

  /* --- widgets ----------------------------------------------------- */

  // Widgets in DISPLAY order: CSS `order` on the <center> flex column,
  // DOM order breaking ties. Order is never changed by moving nodes — a
  // moved custom element re-runs connectedCallback (AMBOSS re-renders).
  function widgets() {
    var found = document.querySelectorAll(".klaus-widget");
    var out = [];
    for (var i = 0; i < found.length; i++) out.push({ w: found[i], i: i });
    out.sort(function (a, b) {
      return (Number(a.w.style.order) || 0) - (Number(b.w.style.order) || 0) || a.i - b.i;
    });
    return out.map(function (e) { return e.w; });
  }

  function widgetById(id) {
    var ws = widgets();
    for (var i = 0; i < ws.length; i++)
      if (ws[i].getAttribute("data-w") === id) return ws[i];
    return null;
  }

  function currentOrder() {
    var ids = [];
    var ws = widgets();
    for (var i = 0; i < ws.length; i++) ids.push(ws[i].getAttribute("data-w"));
    return ids;
  }

  function deckTable() {
    var tables = document.querySelectorAll("center > table");
    for (var i = 0; i < tables.length; i++)
      if (tables[i].querySelector("tr.deck")) return tables[i];
    return null;
  }

  function makeWrapper(id) {
    var w = document.createElement("div");
    w.className = "klaus-widget";
    w.setAttribute("data-w", id);
    return w;
  }

  // Wrap the page's known sections into widgets. Shape-detected, not
  // mode-flagged: in theme mode background.panel_js never ran, so the
  // studied-today line is still a table SIBLING and must travel inside
  // the decks widget (only the table's own <br> — never a
  // querySelector("br"), foreign stats content may hold its own).
  function wrap() {
    // Already-wrapped FIRST: once the table lives inside the wrapper,
    // `center > table` no longer matches, so checking deckTable()
    // before this guard would misreport an already-wrapped page as
    // "nothing to do" and a re-boot would skip order/edit re-apply.
    if (widgetById("decks")) return true;
    var table = deckTable();
    if (!table) return false; // overview/congrats shape — leave alone
    var center = table.parentNode;
    var br = table.nextElementSibling;
    var w = makeWrapper("decks");
    center.insertBefore(w, table);
    w.appendChild(table);
    var studied = document.getElementById("studiedToday");
    if (studied && !studied.closest("table")) {
      if (br && br.tagName === "BR") w.appendChild(br);
      w.appendChild(studied);
    }
    var hm = document.querySelector(".klaus-hm");
    if (hm && !hm.closest(".klaus-widget")) {
      var wh = makeWrapper("heatmap");
      hm.parentNode.insertBefore(wh, hm);
      wh.appendChild(hm);
    }
    return true;
  }

  // Other add-ons' blocks beside the deck list (AMBOSS's Qbank card, an
  // AnkiHub banner, …) arrive already wrapped: dashboard.wrap_foreign
  // writes <div class="klaus-widget" data-w="x:…"> around each in the
  // HTML, before the page parses, so the page never has to move them.
  // Here they only become removable, and a removed one is offered by ＋.
  function label(id) {
    if (labels[id]) return labels[id];
    var words = String(id).replace(/^x:\.?/, "").split(/[-_.:#\s]+/).filter(function (w) {
      return w && !/^(widget|wrapper|component|container|root|\d+)$/i.test(w);
    });
    return words.length
      ? words.map(function (w) { return w.charAt(0).toUpperCase() + w.slice(1); }).join(" ")
      : "Add-on";
  }

  function adopt() {
    var ws = widgets();
    for (var i = 0; i < ws.length; i++) {
      var id = ws[i].getAttribute("data-w") || "";
      if (id.indexOf("x:") !== 0) continue;
      if (removable.indexOf(id) < 0) removable.push(id);
      if (hiddenForeign.indexOf(id) >= 0) {
        ws[i].style.display = "none";
        var listed = false;
        for (var k = 0; k < hidden.length; k++) if (hidden[k].id === id) listed = true;
        if (!listed) hidden.push({ id: id, label: label(id) });
      }
    }
  }

  // The saved widgets take the display slots the saved ones hold, in
  // the saved order; a widget with no saved place keeps its own slot.
  // Written as CSS order only (see widgets()).
  function applyOrder(order) {
    var seq = widgets();
    var saved = [];
    for (var i = 0; i < order.length; i++) {
      var w = widgetById(order[i]);
      if (w && saved.indexOf(w) < 0) saved.push(w);
    }
    var n = 0;
    for (var j = 0; j < seq.length; j++) if (saved.indexOf(seq[j]) >= 0) seq[j] = saved[n++];
    for (var k = 0; k < seq.length; k++) seq[k].style.order = String(k + 1);
  }

  /* --- menus ------------------------------------------------------- */

  function hideMenus() {
    var menus = document.querySelectorAll(".klaus-dash-menu");
    for (var i = 0; i < menus.length; i++)
      menus[i].parentNode.removeChild(menus[i]);
  }

  function menuItem(label, onPick) {
    var mi = document.createElement("div");
    mi.className = "mi";
    mi.textContent = label;
    mi.addEventListener("click", function (ev) {
      ev.stopPropagation();
      hideMenus();
      onPick();
    });
    return mi;
  }

  // pdfjs_viewer's #ctxmenu geometry: fixed, clamped into the viewport.
  function showMenuAt(menu, x, y) {
    document.body.appendChild(menu);
    menu.style.display = "block";
    var w = menu.offsetWidth || 160;
    var h = menu.offsetHeight || 34;
    menu.style.left = Math.max(4, Math.min(x, window.innerWidth - w - 4)) + "px";
    menu.style.top = Math.max(4, Math.min(y, window.innerHeight - h - 4)) + "px";
  }

  /* --- edit mode --------------------------------------------------- */

  function addBadge(w, id) {
    var del = document.createElement("button");
    del.className = "klaus-w-remove";
    del.textContent = "−"; // minus sign, the iOS delete badge
    del.setAttribute("title", "Remove " + label(id));
    del.addEventListener("click", function (ev) {
      ev.stopPropagation();
      // Hide locally and record it as hidden — no rebuild, no scroll
      // jump; the next natural refresh renders without it. ＋ can offer
      // it back immediately because labels shipped in the boot state.
      w.style.display = "none";
      hidden.push({ id: id, label: label(id) });
      send({ action: "remove", id: id });
      buildBar();
    });
    w.appendChild(del);
  }

  function buildBar() {
    removeBar();
    var bar = document.createElement("div");
    bar.className = "klaus-dash-bar";
    if (hidden.length) {
      var plus = document.createElement("button");
      plus.className = "klaus-dash-chip";
      plus.id = "klaus-dash-add";
      plus.textContent = "＋"; // ＋
      plus.setAttribute("title", "Add a widget");
      plus.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var m = document.createElement("div");
        m.className = "klaus-dash-menu";
        m.id = "klaus-dash-addmenu";
        for (var i = 0; i < hidden.length; i++)
          (function (entry) {
            m.appendChild(
              menuItem(entry.label, function () {
                // Python writes the widget's bool and refreshes; the
                // rebuilt page boots with edit:true (the _EDIT flag)
                // and re-enters edit mode with the widget present.
                send({ action: "add", id: entry.id });
              })
            );
          })(hidden[i]);
        hideMenus();
        showMenuAt(m, (window.innerWidth || 0) - 200, 52);
      });
      bar.appendChild(plus);
    }
    var done = document.createElement("button");
    done.className = "klaus-dash-chip";
    done.id = "klaus-dash-done";
    done.textContent = "Done";
    done.addEventListener("click", function (ev) {
      ev.stopPropagation();
      exitEdit();
      send({ action: "edit-off" });
    });
    bar.appendChild(done);
    document.body.appendChild(bar);
  }

  function removeBar() {
    var bars = document.querySelectorAll(".klaus-dash-bar");
    for (var i = 0; i < bars.length; i++)
      bars[i].parentNode.removeChild(bars[i]);
  }

  function enterEdit() {
    if (editing) return;
    editing = true;
    document.body.classList.add("klaus-dash-editing");
    var ws = widgets();
    for (var i = 0; i < ws.length; i++) dress(ws[i]);
    buildBar();
  }

  // Edit-mode chrome for one widget: the drag shield, and ⊖ if removable.
  function dress(w) {
    var shield = document.createElement("div");
    shield.className = "klaus-w-shield";
    w.appendChild(shield);
    bindDrag(shield, w);
    var id = w.getAttribute("data-w");
    if (removable.indexOf(id) >= 0) addBadge(w, id);
  }

  function exitEdit() {
    if (!editing) return;
    editing = false;
    document.body.classList.remove("klaus-dash-editing");
    var strip = document.querySelectorAll(".klaus-w-shield");
    for (var i = 0; i < strip.length; i++)
      strip[i].parentNode.removeChild(strip[i]);
    var badges = document.querySelectorAll(".klaus-w-remove");
    for (var j = 0; j < badges.length; j++)
      badges[j].parentNode.removeChild(badges[j]);
    removeBar();
    hideMenus();
  }

  /* --- drag to reorder --------------------------------------------- */

  function bindDrag(shield, w) {
    shield.addEventListener("pointerdown", function (ev) {
      if (ev.isPrimary === false) return;
      if (ev.button !== undefined && ev.button !== 0) return;
      dragState = {
        w: w,
        y0: ev.clientY,
        moved: false,
        startOrder: currentOrder(),
      };
      try {
        shield.setPointerCapture(ev.pointerId);
      } catch (e) {}
      ev.preventDefault();
    });
    shield.addEventListener("pointermove", function (ev) {
      if (!dragState || dragState.w !== w) return;
      var dy = ev.clientY - dragState.y0;
      if (!dragState.moved) {
        if (dy > -5 && dy < 5) return; // 5px lift threshold
        dragState.moved = true;
        w.classList.add("klaus-w-drag");
      }
      w.style.transform = "translateY(" + dy + "px) scale(1.02)";
      // Midpoint swap against the neighbouring widget. The moving node
      // is its own placeholder; after the DOM move, rebase y0 by the
      // layout shift (offsetTop ignores transforms) so the panel under
      // the pointer doesn't jump.
      var ws = widgets();
      var i = ws.indexOf ? ws.indexOf(w) : indexOfNode(ws, w);
      var rect = w.getBoundingClientRect();
      var neighbour = null;
      if (dy < 0 && i > 0) {
        var prev = ws[i - 1].getBoundingClientRect();
        if (rect.top < prev.top + prev.height / 2) {
          neighbour = ws[i - 1];
        }
      } else if (dy > 0 && i < ws.length - 1) {
        var next = ws[i + 1].getBoundingClientRect();
        if (rect.bottom > next.top + next.height / 2) {
          neighbour = ws[i + 1];
        }
      }
      if (neighbour) {
        // Swap CSS order, never the DOM (see widgets()).
        var oldTop = w.offsetTop;
        var o = w.style.order;
        w.style.order = neighbour.style.order;
        neighbour.style.order = o;
        dragState.y0 += w.offsetTop - oldTop;
        w.style.transform =
          "translateY(" + (ev.clientY - dragState.y0) + "px) scale(1.02)";
      }
    });
    var finish = function () {
      if (!dragState || dragState.w !== w) return;
      var moved = dragState.moved;
      var startOrder = dragState.startOrder;
      dragState = null;
      w.classList.remove("klaus-w-drag");
      w.style.transform = "";
      if (!moved) return;
      var order = currentOrder();
      if (order.join(",") !== startOrder.join(","))
        send({ action: "order", order: order });
    };
    shield.addEventListener("pointerup", finish);
    shield.addEventListener("pointercancel", finish);
  }

  function indexOfNode(list, node) {
    for (var i = 0; i < list.length; i++) if (list[i] === node) return i;
    return -1;
  }

  function abortDrag() {
    if (!dragState) return;
    var st = dragState;
    dragState = null;
    st.w.classList.remove("klaus-w-drag");
    st.w.style.transform = "";
    // Back to the order the drag started from.
    applyOrder(st.startOrder);
  }

  /* --- global listeners -------------------------------------------- */

  function insideChrome(target) {
    if (!target || !target.closest) return false;
    return !!(
      target.closest(".klaus-widget") ||
      target.closest(".klaus-dash-bar") ||
      target.closest(".klaus-dash-menu")
    );
  }

  function bindGlobal() {
    document.addEventListener("contextmenu", function (ev) {
      if (dragState) {
        ev.preventDefault();
        return;
      }
      var w = ev.target && ev.target.closest
        ? ev.target.closest(".klaus-widget")
        : null;
      if (!w) return; // off-widget: Anki's default (which shows nothing)
      ev.preventDefault();
      hideMenus();
      if (editing) return; // already jiggling — the bar has the controls
      var m = document.createElement("div");
      m.className = "klaus-dash-menu";
      m.appendChild(
        menuItem("Edit Widgets…", function () {
          enterEdit();
          send({ action: "edit-on" });
        })
      );
      showMenuAt(m, ev.clientX, ev.clientY);
    });
    document.addEventListener("click", function (ev) {
      hideMenus();
      // Click on empty page space exits edit mode, like tapping the
      // wallpaper on iOS. Chrome clicks stopPropagation, so they never
      // reach here.
      if (editing && !insideChrome(ev.target)) {
        exitEdit();
        send({ action: "edit-off" });
      }
    });
    document.addEventListener("scroll", hideMenus, true);
    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "Escape") return;
      if (dragState) {
        abortDrag();
        ev.preventDefault();
        return;
      }
      if (editing) {
        exitEdit();
        send({ action: "edit-off" });
        ev.preventDefault();
      } else {
        hideMenus();
      }
    });
  }

  /* --- boot -------------------------------------------------------- */

  function boot() {
    var state = window.klausDashState;
    if (!state) return;
    removable = state.removable || [];
    labels = state.labels || {};
    hidden = (state.hidden || []).slice();
    hiddenForeign = state.hiddenForeign || [];
    savedOrder = state.order || [];
    if (!wrap()) return;
    var col = widgetById("decks").parentNode;
    if (col.classList) col.classList.add("klaus-dash-col");
    adopt();
    applyOrder(savedOrder);
    if (!window.klausDashBound) {
      // Real Anki never re-runs this script in one document (every
      // refresh is a fresh page), but the guard keeps a double eval —
      // the node harness does one on purpose — from doubling the
      // document-level listeners.
      window.klausDashBound = true;
      bindGlobal();
    }
    if (state.edit) enterEdit();
  }

  window.klausDash = {
    wrap: wrap,
    label: label,
    applyOrder: applyOrder,
    enterEdit: enterEdit,
    exitEdit: exitEdit,
    send: send,
    boot: boot,
  };

  try {
    boot();
  } catch (e) {
    // Any failure must leave Anki's stock layout standing.
  }
})();
