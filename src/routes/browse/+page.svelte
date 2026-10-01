<script lang="ts">
  // The browser (Anki's Qt aqt/browser, rebuilt): search, a Cards/Notes table backed
  // by the backend's browser rows, a sidebar, Anki's own editor for the selected row,
  // and a card preview. Everything goes through /_anki, nothing through the shell.
  import {
    allBrowserColumns,
    browserRowForId,
    buildSearchString,
    cardsOfNote,
    getCard,
    getConfigBool,
    getConfigJson,
    getNote,
    searchCards,
    searchNotes,
    setActiveBrowserColumns,
    setConfigBool,
    setConfigJson,
  } from "@generated/backend";
  import { ConfigKey_Bool } from "@generated/anki/config_pb";
  import {
    BrowserColumns_Sorting as Sorting,
    BrowserRow_Color as Color,
    type BrowserColumns_Column,
    type BrowserRow,
    SearchNode,
  } from "@generated/anki/search_pb";
  import type { PlainMessage } from "@bufbuild/protobuf";
  import type { RenderCardResponse } from "@generated/klaus_pb";
  import { onMount } from "svelte";
  import { cardBodyClass, cardFrameSrc, night, postToCard, renderCard } from "$lib/card";
  import Sidebar from "./Sidebar.svelte";

  const ROW_HEIGHT = 28;
  // anki/browser.py BrowserConfig / BrowserDefaults
  const config = (notes: boolean) =>
    notes
      ? { cols: "activeNoteCols", sort: "noteSortType", back: "browserNoteSortBackwards", defaults: ["noteFld", "note", "template", "noteTags"] }
      : { cols: "activeCols", sort: "sortType", back: "sortBackwards", defaults: ["noteFld", "template", "cardDue", "deck"] };

  let columns: BrowserColumns_Column[] = $state([]);
  let active: string[] = $state([]);
  let notesMode = $state(false);
  let sortColumn = $state("noteFld");
  let sortBackwards = $state(false);
  let search = $state("deck:current");
  let ids: bigint[] = $state.raw([]);
  let selected: bigint | undefined = $state();

  // Rows are fetched only for what's on screen, as Anki's table model does.
  let rows = new Map<bigint, BrowserRow>();
  let fetching = new Set<bigint>();
  let rowsVersion = $state(0);
  let scrollTop = $state(0);
  let viewHeight = $state(600);
  let tableBox: HTMLDivElement;
  // Clamped: a scroll offset from a longer, earlier result set must not leave the window past the end.
  const first = $derived(Math.max(0, Math.min(ids.length, Math.floor(scrollTop / ROW_HEIGHT) - 10)));
  const last = $derived(Math.min(ids.length, Math.ceil((scrollTop + viewHeight) / ROW_HEIGHT) + 10));
  const visible = $derived(ids.slice(first, last));

  async function getJson<T>(key: string, fallback: T): Promise<T> {
    const json = await getConfigJson({ val: key });
    return JSON.parse(new TextDecoder().decode(json.json)) ?? fallback;
  }
  function setJson(key: string, value: unknown) {
    return setConfigJson({ key, valueJson: new TextEncoder().encode(JSON.stringify(value)), undoable: false });
  }

  async function loadMode() {
    notesMode = (await getConfigBool({ key: ConfigKey_Bool.BROWSER_TABLE_SHOW_NOTES_MODE })).val;
    const keys = config(notesMode);
    active = await getJson(keys.cols, keys.defaults);
    sortColumn = await getJson(keys.sort, "noteFld");
    sortBackwards = await getJson(keys.back, false);
    await setActiveBrowserColumns({ vals: active });
    clearRows();
  }

  function clearRows() {
    rows = new Map();
    fetching = new Set();
    rowsVersion++;
  }

  function sortingOf(column: BrowserColumns_Column | undefined): Sorting {
    if (!column) return Sorting.NONE;
    return notesMode ? column.sortingNotes : column.sortingCards;
  }

  // Only the latest search may apply its results: an earlier one (other query, sort
  // or mode) can finish last, and its ids could be cards where notes are expected.
  let searchSeq = 0;

  async function runSearch(text = search) {
    const seq = ++searchSeq;
    try {
      // Normalised the way Anki shows it, and validated before searching.
      const normalized = (await buildSearchString({ filter: { case: "parsableText", value: text } })).val;
      search = normalized;
      const column = columns.find((c) => c.key === sortColumn);
      const order =
        sortingOf(column) === Sorting.NONE
          ? { value: { case: "none" as const, value: {} } }
          : { value: { case: "builtin" as const, value: { column: sortColumn, reverse: sortBackwards } } };
      const found = await (notesMode ? searchNotes : searchCards)({ search: normalized, order });
      if (seq !== searchSeq) return;
      ids = found.ids;
      clearRows();
      if (selected === undefined || !ids.includes(selected)) select(ids[0]);
      scrollToSelected(true);
    } catch {
      // Invalid search: the bridge's error was shown.
    }
  }

  $effect(() => {
    void rowsVersion;
    for (const id of visible) {
      if (rows.has(id) || fetching.has(id)) continue;
      fetching.add(id);
      const batch = rows;
      browserRowForId({ val: id }, { alertOnError: false })
        .then((row) => {
          if (batch !== rows) return; // columns or search changed meanwhile
          rows.set(id, row);
          rowsVersion++;
        })
        .catch(() => {});
    }
  });

  function rowFor(id: bigint): BrowserRow | undefined {
    void rowsVersion;
    return rows.get(id);
  }

  function columnLabel(column: BrowserColumns_Column) {
    return notesMode ? column.notesModeLabel : column.cardsModeLabel;
  }

  async function sortBy(column: BrowserColumns_Column) {
    const sorting = sortingOf(column);
    if (sorting === Sorting.NONE) return;
    if (column.key === sortColumn) sortBackwards = !sortBackwards;
    else [sortColumn, sortBackwards] = [column.key, sorting === Sorting.DESCENDING];
    const keys = config(notesMode);
    await Promise.all([setJson(keys.sort, sortColumn), setJson(keys.back, sortBackwards)]);
    await runSearch();
  }

  async function toggleColumn(key: string) {
    active = active.includes(key) ? active.filter((k) => k !== key) : [...active, key];
    await setJson(config(notesMode).cols, active);
    await setActiveBrowserColumns({ vals: active });
    clearRows();
  }

  async function toggleMode() {
    const was = selected;
    await setConfigBool({ key: ConfigKey_Bool.BROWSER_TABLE_SHOW_NOTES_MODE, value: !notesMode, undoable: false });
    await loadMode();
    // Keep the same note selected across modes.
    if (was !== undefined) {
      selected = notesMode ? (await getCard({ cid: was })).noteId : (await cardsOfNote({ nid: was })).cids[0];
    }
    await runSearch();
  }

  // Side editor: Anki's editor page in browser mode, loaded with the selected note
  // the way aqt/editor.py's load_note does. It saves through updateNotes itself.
  let editorFrame: HTMLIFrameElement;
  let editorReady: Promise<void>;
  let markEditorReady: () => void;
  const editorSrc = `/editor/?mode=browser${night ? "#night" : ""}`;

  async function noteIdOf(id: bigint): Promise<bigint> {
    return notesMode ? id : (await getCard({ cid: id })).noteId;
  }
  async function cardIdOf(id: bigint): Promise<bigint> {
    return notesMode ? (await cardsOfNote({ nid: id })).cids[0] : id;
  }

  async function select(id: bigint | undefined) {
    selected = id;
    if (id === undefined) return;
    const nid = await noteIdOf(id);
    const note = await getNote({ nid });
    await editorReady;
    if (selected !== id) return;
    const editor = editorFrame.contentWindow as any;
    // As Anki's browser (editor.call_after_note_saved): save the current note's
    // pending edits before loading another, or they'd be lost.
    await editor.saveNow?.();
    if (selected !== id) return;
    editor.require("anki/ui").loaded.then(() =>
      editor.loadNote({
        nid: Number(nid),
        notetypeId: Number(note.notetypeId),
        focusTo: null,
        originalNoteId: null,
        reviewerCardId: null,
        deckId: null,
        initial: true,
      }),
    );
    if (previewOpen) showPreview();
  }

  function move(delta: number) {
    if (!ids.length) return;
    const index = selected === undefined ? -1 : ids.indexOf(selected);
    const next = Math.min(ids.length - 1, Math.max(0, index + delta));
    select(ids[next]);
    scrollToSelected(false);
  }

  /** Keeps the selected row in view; after a new search, otherwise starts at the top. */
  function scrollToSelected(newResults: boolean) {
    const index = selected === undefined ? -1 : ids.indexOf(selected);
    if (index < 0) {
      if (newResults) tableBox.scrollTop = scrollTop = 0;
      return;
    }
    const top = index * ROW_HEIGHT;
    // The header row sits above the first data row.
    if (top < tableBox.scrollTop) tableBox.scrollTop = top;
    else if (top + 2 * ROW_HEIGHT > tableBox.scrollTop + viewHeight) tableBox.scrollTop = top + 2 * ROW_HEIGHT - viewHeight;
    scrollTop = tableBox.scrollTop;
  }

  function onTableKey(event: KeyboardEvent) {
    if (event.key === "ArrowDown") move(1);
    else if (event.key === "ArrowUp") move(-1);
    else return;
    event.preventDefault();
  }

  // Preview (Anki's previewer): the selected card in the sandboxed card frame.
  let previewDialog: HTMLDialogElement;
  let previewFrame: HTMLIFrameElement;
  let previewReady: Promise<void>;
  let previewOpen = $state(false);
  let previewSide: "question" | "answer" = $state("question");
  let preview: { rendered: RenderCardResponse; bodyClass: string } | undefined;

  async function showPreview() {
    const id = selected;
    if (id === undefined) return;
    const cid = await cardIdOf(id);
    const [card, rendered] = await Promise.all([getCard({ cid }), renderCard(cid)]);
    // Previous/Next may have moved on while this rendered.
    if (id !== selected || !previewOpen) return;
    preview = { rendered, bodyClass: cardBodyClass(card.templateIdx) };
    previewSide = "question";
    await previewReady;
    postToCard(previewFrame, { show: "question", html: rendered.question, answer: rendered.answer, bodyClass: preview.bodyClass });
  }
  function flipPreview() {
    if (!preview) return;
    previewSide = previewSide === "question" ? "answer" : "question";
    const html = previewSide === "question" ? preview.rendered.question : preview.rendered.answer;
    postToCard(previewFrame, { show: previewSide, html, bodyClass: preview.bodyClass });
  }
  function openPreview() {
    if (selected === undefined) return;
    previewOpen = true;
    previewDialog.showModal();
    showPreview();
  }

  const colorClass: Partial<Record<Color, string>> = {
    [Color.MARKED]: "marked",
    [Color.SUSPENDED]: "suspended",
    [Color.BURIED]: "buried",
    [Color.FLAG_RED]: "flag-red",
    [Color.FLAG_ORANGE]: "flag-orange",
    [Color.FLAG_GREEN]: "flag-green",
    [Color.FLAG_BLUE]: "flag-blue",
    [Color.FLAG_PINK]: "flag-pink",
    [Color.FLAG_TURQUOISE]: "flag-turquoise",
    [Color.FLAG_PURPLE]: "flag-purple",
  };

  async function sidebarSearch(node: PlainMessage<SearchNode>) {
    const text = (await buildSearchString(node)).val;
    await runSearch(text);
  }

  onMount(() => {
    editorReady = new Promise((resolve) => (markEditorReady = resolve));
    previewReady = new Promise((resolve) => previewFrame.addEventListener("load", () => resolve(), { once: true }));
    const onMessage = (event: MessageEvent) => {
      if (event.source === editorFrame.contentWindow && typeof event.data?.klausEditor === "string") {
        const cmd: string = event.data.klausEditor;
        if (cmd === "editorReady") markEditorReady();
        else if (cmd === "preview") openPreview();
        // The editor saved: refetch the visible rows (the note's sibling cards
        // changed too), as Anki's table redraws after the op.
        else if (cmd === "noteUpdated") clearRows();
      } else if (event.source === previewFrame?.contentWindow && event.data?.klaus) {
        const { key, cmd } = event.data;
        if (key === " " || key === "Enter" || cmd === "ans") flipPreview();
      }
    };
    const onKeydown = (event: KeyboardEvent) => {
      const mod = event.ctrlKey || event.metaKey;
      if (mod && event.shiftKey && event.key.toLowerCase() === "p") {
        event.preventDefault();
        openPreview();
      } else if (event.key === "Escape" && !document.querySelector("dialog[open]")) {
        location.href = "/";
      }
    };
    addEventListener("message", onMessage);
    addEventListener("keydown", onKeydown);
    (async () => {
      columns = (await allBrowserColumns({})).columns;
      await loadMode();
      await runSearch();
    })();
    return () => {
      removeEventListener("message", onMessage);
      removeEventListener("keydown", onKeydown);
    };
  });
</script>

<div class="browser">
  <header>
    <a href="/" class="back">← Decks</a>
    <form
      class="search"
      onsubmit={(e) => {
        e.preventDefault();
        runSearch();
      }}
    >
      <input type="search" bind:value={search} aria-label="Search" spellcheck="false" />
    </form>
    <button onclick={toggleMode} aria-pressed={notesMode} title="Switch between cards and notes"
      >{notesMode ? "Notes" : "Cards"}</button
    >
    <details class="columns">
      <summary>Columns</summary>
      <div class="menu">
        {#each columns as column (column.key)}
          <label
            ><input type="checkbox" checked={active.includes(column.key)} onchange={() => toggleColumn(column.key)} />
            {columnLabel(column)}</label
          >
        {/each}
      </div>
    </details>
    <button onclick={openPreview} disabled={selected === undefined} title="Preview (Ctrl+Shift+P)">Preview</button>
    <span class="count" aria-live="polite">{ids.length} {notesMode ? "notes" : "cards"}</span>
  </header>

  <Sidebar onsearch={sidebarSearch} current={search} />

  <div
    class="table"
    bind:this={tableBox}
    bind:clientHeight={viewHeight}
    onscroll={() => (scrollTop = tableBox.scrollTop)}
  >
    <!-- Only the visible rows exist, so each carries its absolute aria-rowindex
         (the header is row 1) and the grid states the full count. -->
    <table role="grid" tabindex="0" aria-label="Search results" aria-rowcount={ids.length + 1} onkeydown={onTableKey}>
      <thead>
        <tr aria-rowindex={1}>
          {#each active as key (key)}
            {@const column = columns.find((c) => c.key === key)}
            <th
              title={column ? (notesMode ? column.notesModeTooltip : column.cardsModeTooltip) : key}
              aria-sort={key === sortColumn ? (sortBackwards ? "descending" : "ascending") : "none"}
            >
              <button onclick={() => column && sortBy(column)} disabled={sortingOf(column) === Sorting.NONE}>
                {column ? columnLabel(column) : key}{key === sortColumn ? (sortBackwards ? " ▼" : " ▲") : ""}
              </button>
            </th>
          {/each}
        </tr>
      </thead>
      <tbody>
        <tr style:height="{first * ROW_HEIGHT}px" aria-hidden="true"></tr>
        {#each visible as id, i (id)}
          {@const row = rowFor(id)}
          <tr
            aria-rowindex={first + i + 2}
            class={row ? colorClass[row.color] : undefined}
            class:selected={id === selected}
            aria-selected={id === selected}
            onclick={() => select(id)}
          >
            {#each active as key, i (key)}
              <td dir={row?.cells[i]?.isRtl ? "rtl" : undefined}>{row?.cells[i]?.text ?? ""}</td>
            {/each}
          </tr>
        {/each}
        <tr style:height="{(ids.length - last) * ROW_HEIGHT}px" aria-hidden="true"></tr>
      </tbody>
    </table>
  </div>

  <iframe class="editor" bind:this={editorFrame} src={editorSrc} title="Editor"></iframe>
</div>

<dialog
  bind:this={previewDialog}
  class="preview"
  aria-label="Preview"
  onclose={() => {
    previewOpen = false;
    preview = undefined;
  }}
>
  <iframe bind:this={previewFrame} src={cardFrameSrc} sandbox="allow-scripts" title="Card preview"></iframe>
  <footer>
    <button onclick={() => move(-1)}>Previous</button>
    <button onclick={flipPreview}>{previewSide === "question" ? "Show Answer" : "Show Question"}</button>
    <button onclick={() => move(1)}>Next</button>
    <button onclick={() => previewDialog.close()}>Close</button>
  </footer>
</dialog>

<style>
  :global(body) {
    margin: 0;
    font-family: system-ui, sans-serif;
    color: CanvasText;
    background: Canvas;
    color-scheme: light dark;
  }
  .browser {
    display: grid;
    grid-template: auto 1fr / 14rem minmax(0, 1fr) minmax(20rem, 28rem);
    height: 100vh;
  }
  header {
    grid-column: 1 / -1;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid color-mix(in srgb, CanvasText 15%, transparent);
  }
  .back { color: inherit; white-space: nowrap; }
  .search { flex: 1; display: flex; }
  .search input { flex: 1; padding: 0.3rem 0.5rem; font: inherit; }
  .count { opacity: 0.7; font-size: 0.85rem; white-space: nowrap; }
  .columns { position: relative; }
  .columns summary { cursor: pointer; list-style: none; padding: 0.2rem 0.5rem; border: 1px solid color-mix(in srgb, CanvasText 25%, transparent); border-radius: 4px; }
  .columns .menu {
    position: absolute;
    right: 0;
    z-index: 2;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    max-height: 60vh;
    overflow: auto;
    padding: 0.5rem 0.75rem;
    background: Canvas;
    border: 1px solid color-mix(in srgb, CanvasText 20%, transparent);
    border-radius: 6px;
    white-space: nowrap;
  }
  :global(.browser > nav) { border-right: 1px solid color-mix(in srgb, CanvasText 15%, transparent); }
  .table { overflow: auto; }
  table:focus-visible { outline: 2px solid Highlight; outline-offset: -2px; }
  table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 0.9rem; }
  thead th { position: sticky; top: 0; z-index: 1; background: Canvas; border-bottom: 1px solid color-mix(in srgb, CanvasText 20%, transparent); }
  th button { width: 100%; padding: 0.3rem 0.5rem; border: 0; background: none; color: inherit; font: inherit; font-weight: 600; text-align: left; cursor: pointer; }
  th button:disabled { cursor: default; }
  tbody tr:not([aria-hidden]) { height: 28px; cursor: default; }
  td { padding: 0 0.5rem; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  tr.selected { background: Highlight; color: HighlightText; }
  /* Anki's row colours (aqt/browser/table: backend_color_to_aqt_color). */
  .marked { background: light-dark(#e9d5ff, #4c1d95); }
  .suspended { background: light-dark(#fef08a, #713f12); }
  .buried { background: light-dark(#e5e7eb, #374151); }
  .flag-red { background: light-dark(#fecaca, #7f1d1d); }
  .flag-orange { background: light-dark(#fed7aa, #7c2d12); }
  .flag-green { background: light-dark(#bbf7d0, #14532d); }
  .flag-blue { background: light-dark(#bfdbfe, #1e3a8a); }
  .flag-pink { background: light-dark(#fbcfe8, #831843); }
  .flag-turquoise { background: light-dark(#99f6e4, #134e4a); }
  .flag-purple { background: light-dark(#ddd6fe, #4c1d95); }
  .editor { width: 100%; height: 100%; border: 0; border-left: 1px solid color-mix(in srgb, CanvasText 15%, transparent); }
  .preview { width: min(48rem, 90vw); height: min(40rem, 85vh); padding: 0; border: 1px solid color-mix(in srgb, CanvasText 20%, transparent); border-radius: 8px; background: Canvas; color: inherit; }
  .preview[open] { display: flex; flex-direction: column; }
  .preview iframe { flex: 1; width: 100%; border: 0; }
  .preview footer { display: flex; justify-content: center; gap: 0.5rem; padding: 0.5rem; border-top: 1px solid color-mix(in srgb, CanvasText 15%, transparent); }
</style>
