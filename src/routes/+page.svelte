<script lang="ts">
  import {
    addDeck,
    addOrUpdateFilteredDeck,
    deckTree,
    emptyFilteredDeck,
    getOrCreateFilteredDeck,
    newDeck,
    rebuildFilteredDeck,
    removeDecks,
    renameDeck,
    setDeckCollapsed,
    undo,
  } from "@generated/backend";
  import {
    Deck_Filtered_SearchTerm,
    Deck_Filtered_SearchTerm_Order as Order,
    type DeckTreeNode,
    FilteredDeckForUpdate,
    SetDeckCollapsedRequest_Scope,
  } from "@generated/anki/decks_pb";
  import { onMount } from "svelte";
  import DeckRows, { type DeckAction } from "./DeckRows.svelte";

  let root: DeckTreeNode | undefined = $state();
  let loadError = $state("");
  // After a delete, as Anki's "N cards deleted" tooltip: offers undo.
  let deleted = $state("");

  async function refresh() {
    try {
      root = await deckTree({ now: BigInt(Math.floor(Date.now() / 1000)) });
    } catch (err) {
      loadError = String(err);
    }
  }
  onMount(refresh);

  // Anki's own editor; it adds the note itself through the bridge.
  function addNote() {
    const night = matchMedia("(prefers-color-scheme: dark)").matches ? "#night" : "";
    location.href = `/editor/?mode=add${night}`;
  }

  // Klaus's shell shows a file picker, then opens Anki's import page.
  function importPackage() {
    fetch("/_anki/klausImportPackage", { method: "POST", headers: { "Content-Type": "application/binary" } });
  }

  // Create / Rename. "Parent::Child" nests, as in Anki.
  let nameDialog: HTMLDialogElement;
  let renaming: DeckTreeNode | undefined = $state();
  let name = $state("");
  function askName(deck?: DeckTreeNode) {
    renaming = deck;
    name = deck ? fullName(deck) : "";
    nameDialog.showModal();
  }
  async function saveName(event: SubmitEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      if (renaming) {
        await renameDeck({ deckId: renaming.deckId, newName: trimmed });
      } else {
        const deck = await newDeck({});
        deck.name = trimmed;
        await addDeck(deck);
      }
      nameDialog.close();
      await refresh();
    } catch {
      // The bridge's error was already shown.
    }
  }

  /** The tree holds each deck's last component; renaming needs the full path. */
  function fullName(target: DeckTreeNode): string {
    const walk = (node: DeckTreeNode, path: string[]): string | undefined => {
      for (const child of node.children) {
        const here = [...path, child.name];
        if (child.deckId === target.deckId) return here.join("::");
        const found = walk(child, here);
        if (found) return found;
      }
    };
    return (root && walk(root, [])) ?? target.name;
  }

  // Anki's filtered deck dialog (aqt/filtered_deck.py): first search, optional
  // second, reschedule. Preview delays keep their saved values.
  const orders: [Order, string][] = [
    [Order.OLDEST_REVIEWED_FIRST, "Oldest seen first"],
    [Order.RANDOM, "Random"],
    [Order.INTERVALS_ASCENDING, "Increasing intervals"],
    [Order.INTERVALS_DESCENDING, "Decreasing intervals"],
    [Order.LAPSES, "Most lapses"],
    [Order.ADDED, "Order added"],
    [Order.DUE, "Order due"],
    [Order.REVERSE_ADDED, "Latest added first"],
    [Order.RETRIEVABILITY_ASCENDING, "Retrievability ascending"],
    [Order.RETRIEVABILITY_DESCENDING, "Retrievability descending"],
    [Order.RELATIVE_OVERDUENESS, "Relative overdueness"],
  ];
  let filteredDialog: HTMLDialogElement;
  let filtered: FilteredDeckForUpdate | undefined = $state();
  let terms: Deck_Filtered_SearchTerm[] = $state([]);
  let second = $state(false);
  let reschedule = $state(true);
  async function openFiltered(deckId = 0n) {
    try {
      const deck = await getOrCreateFilteredDeck({ did: deckId });
      const saved = deck.config!.searchTerms;
      terms = [
        saved[0],
        saved[1] ?? new Deck_Filtered_SearchTerm({ search: "", limit: 20, order: Order.DUE }),
      ];
      // As Anki: a second filter shows as enabled only for an existing deck.
      second = deckId !== 0n && saved.length > 1;
      reschedule = deck.config!.reschedule;
      filtered = deck;
      filteredDialog.showModal();
    } catch {
      // Shown by the bridge.
    }
  }
  async function saveFiltered(event: SubmitEvent) {
    event.preventDefault();
    const deck = filtered!;
    deck.config!.searchTerms = second ? terms : terms.slice(0, 1);
    deck.config!.reschedule = reschedule;
    try {
      // Saving (re)builds the deck; Anki then shows it.
      await addOrUpdateFilteredDeck(deck);
      filteredDialog.close();
      await refresh();
    } catch {
      // e.g. no cards matched: shown by the bridge; the dialog stays open.
    }
  }

  async function onaction(action: DeckAction, deck: DeckTreeNode) {
    try {
      switch (action) {
        case "collapse":
          await setDeckCollapsed({
            deckId: deck.deckId,
            collapsed: !deck.collapsed,
            scope: SetDeckCollapsedRequest_Scope.REVIEWER,
          });
          break;
        case "rename":
          return askName(deck);
        case "filteredOptions":
          return openFiltered(deck.deckId);
        case "rebuild":
          await rebuildFilteredDeck({ did: deck.deckId });
          break;
        case "empty":
          await emptyFilteredDeck({ did: deck.deckId });
          break;
        case "delete": {
          const { count } = await removeDecks({ dids: [deck.deckId] });
          deleted = `Deleted ${deck.name} (${count} ${count === 1 ? "card" : "cards"}).`;
          break;
        }
      }
      await refresh();
    } catch {
      // Shown by the bridge.
    }
  }

  async function undoDelete() {
    deleted = "";
    await undo({}).catch(() => {});
    await refresh();
  }
</script>

<main>
  <header>
    <h1>Decks</h1>
    <div class="actions">
      <button onclick={addNote}>Add</button>
      <button onclick={() => askName()}>Create Deck</button>
      <button onclick={() => openFiltered()}>Filtered Deck…</button>
      <button onclick={importPackage}>Import…</button>
    </div>
  </header>
  {#if deleted}
    <p class="status" role="status">{deleted} <button onclick={undoDelete}>Undo</button></p>
  {/if}
  {#if root}
    <table>
      <thead>
        <tr><th>Deck</th><th>New</th><th>Learn</th><th>Due</th><th><span class="visually-hidden">Actions</span></th></tr>
      </thead>
      <tbody><DeckRows decks={root.children} {onaction} /></tbody>
    </table>
  {:else if loadError}
    <p role="alert">{loadError}</p>
  {:else}
    <p>Loading…</p>
  {/if}
</main>

<dialog bind:this={nameDialog} aria-labelledby="name-title">
  <form onsubmit={saveName}>
    <h2 id="name-title">{renaming ? "Rename Deck" : "Create Deck"}</h2>
    <label>Name <input bind:value={name} required /></label>
    <p class="hint">Use <code>::</code> to nest, e.g. <code>Biology::Cells</code>.</p>
    <div class="buttons">
      <button type="button" onclick={() => nameDialog.close()}>Cancel</button>
      <button type="submit">{renaming ? "Rename" : "Create"}</button>
    </div>
  </form>
</dialog>

<dialog bind:this={filteredDialog} aria-labelledby="filtered-title">
  {#if filtered}
    <form onsubmit={saveFiltered}>
      <h2 id="filtered-title">{filtered.id ? `Options for ${filtered.name}` : "Filtered Deck"}</h2>
      <label>Name <input bind:value={filtered.name} required /></label>
      {#each terms as term, i (i)}
        {#if i === 0 || second}
          <fieldset>
            <legend>{i === 0 ? "Filter" : "Filter 2"}</legend>
            <label>Search <input bind:value={term.search} /></label>
            <label>Limit to <input type="number" min="1" max="99999" bind:value={term.limit} /> cards</label>
            <label
              >Cards selected by
              <select bind:value={term.order}>
                {#each orders as [value, label] (value)}<option {value}>{label}</option>{/each}
              </select>
            </label>
          </fieldset>
        {/if}
      {/each}
      <label><input type="checkbox" bind:checked={second} /> Enable second filter</label>
      <label><input type="checkbox" bind:checked={reschedule} /> Reschedule cards based on my answers in this deck</label>
      <div class="buttons">
        <button type="button" onclick={() => filteredDialog.close()}>Cancel</button>
        <button type="submit">{filtered.id ? "Rebuild" : "Build"}</button>
      </div>
    </form>
  {/if}
</dialog>

<style>
  :global(body) {
    font-family: system-ui, sans-serif;
    color: CanvasText;
    background: Canvas;
    color-scheme: light dark;
  }
  main { max-width: 44rem; margin: 2rem auto; padding: 0 1rem; }
  header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
  .actions { display: flex; gap: 0.4rem; flex-wrap: wrap; }
  .status { display: flex; align-items: center; gap: 0.5rem; }
  table { width: 100%; border-collapse: collapse; }
  th, :global(td) { padding: 0.35rem 0.5rem; text-align: right; }
  th:first-child, :global(td:first-child) { text-align: left; }
  .visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
  /* ≥4.5:1 against the Canvas background in both schemes. */
  :global(.new) { color: light-dark(#1d4ed8, #93c5fd); }
  :global(.learn) { color: light-dark(#b91c1c, #fca5a5); }
  :global(.review) { color: light-dark(#15803d, #86efac); }
  dialog { min-width: 22rem; border: 1px solid color-mix(in srgb, CanvasText 20%, transparent); border-radius: 8px; color: inherit; background: Canvas; }
  dialog form { display: flex; flex-direction: column; gap: 0.6rem; }
  dialog h2 { margin: 0; font-size: 1.1rem; }
  dialog label { display: flex; align-items: center; gap: 0.5rem; }
  dialog input:not([type]), dialog input[type="number"] { flex: 1; }
  fieldset { display: flex; flex-direction: column; gap: 0.5rem; border-radius: 6px; }
  .hint { margin: 0; font-size: 0.85rem; opacity: 0.75; }
  .buttons { display: flex; justify-content: flex-end; gap: 0.5rem; }
</style>
