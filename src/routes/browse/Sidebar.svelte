<script lang="ts">
  // The browser sidebar (Anki's aqt/browser/sidebar): saved searches, today, flags,
  // card states, decks, note types and tags. A click replaces the search.
  import { getConfigJson, getDeckNames, getNotetypeNames, setConfigJson, tagTree } from "@generated/backend";
  import {
    SearchNode,
    SearchNode_CardState as State,
    SearchNode_Flag as Flag,
    SearchNode_Rating as Rating,
  } from "@generated/anki/search_pb";
  import type { PlainMessage } from "@bufbuild/protobuf";
  import { onMount } from "svelte";

  type Node = PlainMessage<SearchNode>;
  type Item = { label: string; node: Node; children: Item[] };

  let { onsearch, current }: { onsearch: (node: Node) => void; current: string } = $props();

  const leaf = (label: string, filter: Node["filter"]): Item => ({ label, node: new SearchNode({ filter }), children: [] });
  const today = [
    leaf("Added today", { case: "addedInDays", value: 1 }),
    leaf("Edited today", { case: "editedInDays", value: 1 }),
    leaf("Studied today", { case: "rated", value: { days: 1, rating: Rating.ANY } }),
    leaf("Again today", { case: "rated", value: { days: 1, rating: Rating.AGAIN } }),
  ];
  const flags = (
    [
      ["Red", Flag.RED],
      ["Orange", Flag.ORANGE],
      ["Green", Flag.GREEN],
      ["Blue", Flag.BLUE],
      ["Pink", Flag.PINK],
      ["Turquoise", Flag.TURQUOISE],
      ["Purple", Flag.PURPLE],
      ["No flag", Flag.NONE],
    ] as const
  ).map(([label, value]) => leaf(label, { case: "flag", value }));
  const states = (
    [
      ["New", State.NEW],
      ["Learning", State.LEARN],
      ["Review", State.REVIEW],
      ["Suspended", State.SUSPENDED],
      ["Buried", State.BURIED],
    ] as const
  ).map(([label, value]) => leaf(label, { case: "cardState", value }));

  let saved: Record<string, string> = $state({});
  let decks: Item[] = $state([]);
  let notetypes: Item[] = $state([]);
  let tags: Item[] = $state([]);

  /** Nests "A::B::C" names into a tree; each node searches its full name. */
  function nest(names: string[], filter: (full: string) => Node["filter"]): Item[] {
    const root: Item[] = [];
    for (const full of names) {
      let level = root;
      const parts = full.split("::");
      parts.forEach((part, i) => {
        let item = level.find((it) => it.label === part);
        if (!item) {
          item = leaf(part, filter(parts.slice(0, i + 1).join("::")));
          level.push(item);
        }
        level = item.children;
      });
    }
    return root;
  }

  async function loadSaved() {
    const json = await getConfigJson({ val: "savedFilters" });
    saved = JSON.parse(new TextDecoder().decode(json.json)) ?? {};
  }
  async function storeSaved() {
    await setConfigJson({ key: "savedFilters", valueJson: new TextEncoder().encode(JSON.stringify(saved)), undoable: false });
  }

  export async function refresh() {
    const [deckNames, ntNames, tagRoot] = await Promise.all([
      getDeckNames({ skipEmptyDefault: true, includeFiltered: true }),
      getNotetypeNames({}),
      tagTree({}),
      loadSaved(),
    ]);
    decks = nest(
      deckNames.entries.map((d) => d.name).sort(),
      (full) => ({ case: "deck", value: full }),
    );
    notetypes = ntNames.entries.map((n) => leaf(n.name, { case: "note", value: n.name }));
    const tagItems = (node: typeof tagRoot, prefix: string): Item[] =>
      node.children.map((t) => {
        const full = prefix + t.name;
        return { ...leaf(t.name, { case: "tag", value: full }), children: tagItems(t, `${full}::`) };
      });
    tags = tagItems(tagRoot, "");
  }
  onMount(refresh);

  // Saving needs a name: a small inline form rather than prompt(), which has no UI here.
  let naming = $state(false);
  let name = $state("");
  async function saveCurrent(event: SubmitEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    saved = { ...saved, [name.trim()]: current };
    naming = false;
    name = "";
    await storeSaved();
  }
  async function removeSaved(key: string) {
    const { [key]: _, ...rest } = saved;
    saved = rest;
    await storeSaved();
  }
</script>

{#snippet tree(items: Item[])}
  <ul>
    {#each items as item (item.label)}
      <li>
        <button class="item" onclick={() => onsearch(item.node)}>{item.label}</button>
        {#if item.children.length}{@render tree(item.children)}{/if}
      </li>
    {/each}
  </ul>
{/snippet}

<nav aria-label="Browser sidebar">
  <details open>
    <summary>Saved Searches</summary>
    <ul>
      {#each Object.entries(saved) as [label, search] (label)}
        <li class="saved">
          <button class="item" onclick={() => onsearch(new SearchNode({ filter: { case: "parsableText", value: search } }))}
            >{label}</button
          >
          <button class="remove" aria-label="Remove saved search {label}" onclick={() => removeSaved(label)}>×</button>
        </li>
      {/each}
    </ul>
    {#if naming}
      <form onsubmit={saveCurrent}>
        <input bind:value={name} placeholder="Name" aria-label="Saved search name" required />
        <button type="submit">Save</button>
      </form>
    {:else}
      <button class="add" onclick={() => (naming = true)}>Save current search</button>
    {/if}
  </details>
  <details open><summary>Today</summary>{@render tree(today)}</details>
  <details open><summary>Flags</summary>{@render tree(flags)}</details>
  <details open><summary>Card State</summary>{@render tree(states)}</details>
  <details open><summary>Decks</summary>{@render tree(decks)}</details>
  <details open><summary>Note Types</summary>{@render tree(notetypes)}</details>
  <details open><summary>Tags</summary>{@render tree(tags)}</details>
</nav>

<style>
  nav { overflow: auto; padding: 0.5rem; font-size: 0.9rem; }
  summary { font-weight: 600; cursor: pointer; padding: 0.25rem 0; }
  ul { list-style: none; margin: 0; padding-left: 0.9rem; }
  details > ul { padding-left: 0.4rem; }
  .item, .add, .remove {
    border: 0;
    background: none;
    color: inherit;
    font: inherit;
    cursor: pointer;
    padding: 0.1rem 0.25rem;
    text-align: left;
  }
  .item:hover, .item:focus-visible { background: color-mix(in srgb, CanvasText 10%, transparent); border-radius: 4px; }
  .saved { display: flex; justify-content: space-between; }
  .remove { opacity: 0.6; }
  .add { opacity: 0.75; font-size: 0.85rem; }
  form { display: flex; gap: 0.25rem; }
  form input { min-width: 0; flex: 1; }
</style>
