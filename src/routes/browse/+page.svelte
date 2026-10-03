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
  import { cardBodyClass, cardFrameSrc, night, openCardLink, postToCard, renderCard } from "$lib/card";
  import Sidebar from "./Sidebar.svelte";
  import { IconArrowLeft as ArrowLeftIcon } from "@tabler/icons-svelte";
  import { IconColumns3 as Columns3Icon } from "@tabler/icons-svelte";
  import { IconEye as EyeIcon } from "@tabler/icons-svelte";
  import { Button } from "$lib/components/ui/button";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import { Input } from "$lib/components/ui/input";
  import * as Table from "$lib/components/ui/table";
  import * as ToggleGroup from "$lib/components/ui/toggle-group";

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
      if (seq !== searchSeq) return;
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
        // Fetched again the next time it scrolls into view.
        .catch(() => fetching.delete(id));
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

  // A second click while switching would run the sequence again on the new mode.
  let switching = false;
  async function toggleMode() {
    if (switching) return;
    switching = true;
    try {
      const was = selected;
      await setConfigBool({ key: ConfigKey_Bool.BROWSER_TABLE_SHOW_NOTES_MODE, value: !notesMode, undoable: false });
      await loadMode();
      // Keep the same note selected across modes.
      if (was !== undefined) {
        selected = notesMode ? (await getCard({ cid: was })).noteId : (await cardsOfNote({ nid: was })).cids[0];
      }
      await runSearch();
    } catch {
      // The bridge's error was shown.
    } finally {
      switching = false;
    }
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
    try {
      const nid = await noteIdOf(id);
      const note = await getNote({ nid });
      await editorReady;
      if (selected !== id) return;
      const editor = editorFrame.contentWindow as any;
      // As Anki's browser (editor.call_after_note_saved): save the current note's
      // pending edits before loading another, or they'd be lost.
      await editor.saveNow?.();
      if (selected !== id) return;
      editor
        .require("anki/ui")
        .loaded.then(() =>
          editor.loadNote({
            nid: Number(nid),
            notetypeId: Number(note.notetypeId),
            focusTo: null,
            originalNoteId: null,
            reviewerCardId: null,
            deckId: null,
            initial: true,
          }),
        )
        .catch(() => {});
      if (previewOpen) await showPreview();
    } catch {
      // The bridge's error was shown; the editor keeps the previous note.
    }
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
  // The dialog mounts the frame on open, so each opening waits for its load.
  let previewFrame: HTMLIFrameElement | undefined = $state();
  let previewReady: Promise<void> = Promise.resolve();
  let previewLoaded = () => {};
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
    if (!previewOpen) previewReady = new Promise((resolve) => (previewLoaded = resolve));
    previewOpen = true;
    showPreview();
  }

  // Anki's row colours, as theme tokens (src/app.css).
  const colorClass: Partial<Record<Color, string>> = {
    [Color.MARKED]: "bg-row-marked",
    [Color.SUSPENDED]: "bg-row-suspended",
    [Color.BURIED]: "bg-row-buried",
    [Color.FLAG_RED]: "bg-row-flag-red",
    [Color.FLAG_ORANGE]: "bg-row-flag-orange",
    [Color.FLAG_GREEN]: "bg-row-flag-green",
    [Color.FLAG_BLUE]: "bg-row-flag-blue",
    [Color.FLAG_PINK]: "bg-row-flag-pink",
    [Color.FLAG_TURQUOISE]: "bg-row-flag-turquoise",
    [Color.FLAG_PURPLE]: "bg-row-flag-purple",
  };

  /** Back to the decks, saving the editor's pending edits first (its save is debounced). */
  async function leave() {
    await (editorFrame?.contentWindow as any)?.saveNow?.();
    location.href = "/";
  }

  async function sidebarSearch(node: PlainMessage<SearchNode>) {
    const text = (await buildSearchString(node)).val;
    await runSearch(text);
  }

  onMount(() => {
    editorReady = new Promise((resolve) => (markEditorReady = resolve));
    const onMessage = (event: MessageEvent) => {
      if (event.source === editorFrame.contentWindow && typeof event.data?.klausEditor === "string") {
        const cmd: string = event.data.klausEditor;
        if (cmd === "editorReady") markEditorReady();
        else if (cmd === "preview") openPreview();
        // The editor saved: refetch the visible rows (the note's sibling cards
        // changed too), as Anki's table redraws after the op.
        else if (cmd === "noteUpdated") clearRows();
      } else if (event.source === previewFrame?.contentWindow && event.data?.klaus) {
        const { key, cmd, openLink } = event.data;
        if (key === " " || key === "Enter" || cmd === "ans") flipPreview();
        if (openLink !== undefined) openCardLink(openLink);
      }
    };
    const onKeydown = (event: KeyboardEvent) => {
      const mod = event.ctrlKey || event.metaKey;
      if (mod && event.shiftKey && event.key.toLowerCase() === "p") {
        event.preventDefault();
        openPreview();
      } else if (
        event.key === "Escape" &&
        !(event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) &&
        !document.querySelector('[role="dialog"], [role="menu"]')
      ) {
        leave();
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

<div class="grid h-screen grid-cols-[14rem_minmax(0,1fr)_minmax(20rem,28rem)] grid-rows-[auto_minmax(0,1fr)]">
  <header class="col-span-full flex items-center gap-2 border-b px-3 py-2">
    <Button
      href="/"
      variant="ghost"
      size="sm"
      onclick={(event: MouseEvent) => {
        event.preventDefault();
        leave();
      }}
    >
      <ArrowLeftIcon data-icon="inline-start" />
      Decks
    </Button>
    <form
      class="flex flex-1"
      onsubmit={(e) => {
        e.preventDefault();
        runSearch();
      }}
    >
      <Input type="search" bind:value={search} aria-label="Search" spellcheck="false" />
    </form>
    <ToggleGroup.Root
      type="single"
      variant="outline"
      size="sm"
      value={notesMode ? "notes" : "cards"}
      onValueChange={(v) => v && (v === "notes") !== notesMode && toggleMode()}
      aria-label="Show cards or notes"
    >
      <ToggleGroup.Item value="cards">Cards</ToggleGroup.Item>
      <ToggleGroup.Item value="notes">Notes</ToggleGroup.Item>
    </ToggleGroup.Root>
    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        {#snippet child({ props })}
          <Button {...props} variant="outline" size="sm">
            <Columns3Icon data-icon="inline-start" />
            Columns
          </Button>
        {/snippet}
      </DropdownMenu.Trigger>
      <DropdownMenu.Content align="end" class="max-h-[60vh] overflow-y-auto">
        <DropdownMenu.Group>
          {#each columns as column (column.key)}
            <DropdownMenu.CheckboxItem
              checked={active.includes(column.key)}
              onCheckedChange={() => toggleColumn(column.key)}
              closeOnSelect={false}
            >
              {columnLabel(column)}
            </DropdownMenu.CheckboxItem>
          {/each}
        </DropdownMenu.Group>
      </DropdownMenu.Content>
    </DropdownMenu.Root>
    <Button variant="outline" size="sm" onclick={openPreview} disabled={selected === undefined} title="Preview (Ctrl+Shift+P)">
      <EyeIcon data-icon="inline-start" />
      Preview
    </Button>
    <span class="text-sm whitespace-nowrap text-muted-foreground" aria-live="polite">
      {ids.length} {notesMode ? "notes" : "cards"}
    </span>
  </header>

  <Sidebar onsearch={sidebarSearch} current={search} />

  <div
    class="overflow-auto"
    bind:this={tableBox}
    bind:clientHeight={viewHeight}
    onscroll={() => (scrollTop = tableBox.scrollTop)}
  >
    <!-- A plain table: Table.Root's own scroll box would unstick the header. Only the
         visible rows exist, so each carries its absolute aria-rowindex (the header is
         row 1) and the grid states the full count. -->
    <table
      role="grid"
      tabindex="0"
      aria-label="Search results"
      aria-rowcount={ids.length + 1}
      onkeydown={onTableKey}
      class="w-full table-fixed caption-bottom text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
    >
      <Table.Header class="sticky top-0 bg-background">
        <Table.Row aria-rowindex={1}>
          {#each active as key (key)}
            {@const column = columns.find((c) => c.key === key)}
            <Table.Head
              title={column ? (notesMode ? column.notesModeTooltip : column.cardsModeTooltip) : key}
              aria-sort={key === sortColumn ? (sortBackwards ? "descending" : "ascending") : "none"}
              class="p-0"
            >
              <Button
                variant="ghost"
                size="sm"
                class="w-full justify-start rounded-none"
                onclick={() => column && sortBy(column)}
                disabled={sortingOf(column) === Sorting.NONE}
              >
                <span class="truncate">{column ? columnLabel(column) : key}</span>
                {#if key === sortColumn}<span aria-hidden="true">{sortBackwards ? "▼" : "▲"}</span>{/if}
              </Button>
            </Table.Head>
          {/each}
        </Table.Row>
      </Table.Header>
      <Table.Body>
        <tr style:height="{first * ROW_HEIGHT}px" aria-hidden="true"></tr>
        {#each visible as id, i (id)}
          {@const row = rowFor(id)}
          <Table.Row
            aria-rowindex={first + i + 2}
            class={["h-7 cursor-default", id !== selected && row && colorClass[row.color]]}
            data-state={id === selected ? "selected" : undefined}
            aria-selected={id === selected}
            onclick={() => select(id)}
          >
            {#each active as key, i (key)}
              <Table.Cell class="truncate py-0" dir={row?.cells[i]?.isRtl ? "rtl" : undefined}>
                {row?.cells[i]?.text ?? ""}
              </Table.Cell>
            {/each}
          </Table.Row>
        {/each}
        <tr style:height="{(ids.length - last) * ROW_HEIGHT}px" aria-hidden="true"></tr>
      </Table.Body>
    </table>
  </div>

  <iframe class="size-full border-0 border-l" bind:this={editorFrame} src={editorSrc} title="Editor"></iframe>
</div>

<Dialog.Root
  bind:open={previewOpen}
  onOpenChange={(open) => {
    if (!open) preview = undefined;
  }}
>
  <Dialog.Content class="flex h-[min(40rem,85vh)] flex-col sm:max-w-3xl">
    <Dialog.Header>
      <Dialog.Title>Preview</Dialog.Title>
    </Dialog.Header>
    <iframe
      bind:this={previewFrame}
      src={cardFrameSrc}
      sandbox="allow-scripts"
      title="Card preview"
      class="w-full flex-1 rounded-md border"
      onload={() => previewLoaded()}
    ></iframe>
    <Dialog.Footer class="sm:justify-center">
      <Button variant="outline" onclick={() => move(-1)}>Previous</Button>
      <Button onclick={flipPreview}>{previewSide === "question" ? "Show Answer" : "Show Question"}</Button>
      <Button variant="outline" onclick={() => move(1)}>Next</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
