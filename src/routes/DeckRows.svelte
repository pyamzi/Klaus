<script lang="ts" module>
  export type DeckAction = "collapse" | "rename" | "delete" | "filteredOptions" | "rebuild" | "empty";
</script>

<script lang="ts">
  import type { DeckTreeNode } from "@generated/anki/decks_pb";
  import DeckRows from "./DeckRows.svelte";

  let { decks, onaction }: { decks: DeckTreeNode[]; onaction: (action: DeckAction, deck: DeckTreeNode) => void } =
    $props();
  // Anki pages learn dark mode from the URL, as Anki tells them.
  const night = matchMedia("(prefers-color-scheme: dark)").matches ? "#night" : "";

  // Menu items close their menu, like Anki's gear menu.
  function act(event: Event, action: DeckAction, deck: DeckTreeNode) {
    (event.currentTarget as HTMLElement).closest("details")!.open = false;
    onaction(action, deck);
  }
</script>

{#each decks as deck (deck.deckId)}
  <tr>
    <td style:padding-left="{deck.level - 1}rem">
      {#if deck.children.length}
        <button
          class="toggle"
          aria-expanded={!deck.collapsed}
          aria-label="{deck.collapsed ? 'Expand' : 'Collapse'} {deck.name}"
          onclick={() => onaction("collapse", deck)}>{deck.collapsed ? "▸" : "▾"}</button
        >
      {:else}<span class="toggle"></span>{/if}
      <a href="/review?deck={deck.deckId}" class:filtered={deck.filtered}>{deck.name}</a>
    </td>
    <td class="new">{deck.newCount}</td>
    <td class="learn">{deck.learnCount}</td>
    <td class="review">{deck.reviewCount}</td>
    <td>
      <details class="menu">
        <summary aria-label="Actions for {deck.name}" title="Actions">⚙</summary>
        <div class="items">
          {#if deck.filtered}
            <button onclick={(e) => act(e, "filteredOptions", deck)}>Options</button>
            <button onclick={(e) => act(e, "rebuild", deck)}>Rebuild</button>
            <button onclick={(e) => act(e, "empty", deck)}>Empty</button>
          {:else}
            <a data-sveltekit-reload href="/deck-options/{deck.deckId}{night}">Options</a>
          {/if}
          <button onclick={(e) => act(e, "rename", deck)}>Rename</button>
          <button onclick={(e) => act(e, "delete", deck)}>Delete</button>
        </div>
      </details>
    </td>
  </tr>
  {#if !deck.collapsed}<DeckRows decks={deck.children} {onaction} />{/if}
{/each}

<style>
  .toggle {
    display: inline-block;
    width: 1.4rem;
    padding: 0;
    border: 0;
    background: none;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }
  .filtered { color: light-dark(#1d4ed8, #93c5fd); }
  .menu { position: relative; display: inline-block; }
  summary { list-style: none; cursor: pointer; padding: 0 0.25rem; }
  summary::-webkit-details-marker { display: none; }
  .items {
    position: absolute;
    right: 0;
    z-index: 1;
    display: flex;
    flex-direction: column;
    min-width: 8rem;
    padding: 0.25rem 0;
    background: Canvas;
    border: 1px solid color-mix(in srgb, CanvasText 20%, transparent);
    border-radius: 6px;
    box-shadow: 0 4px 12px rgb(0 0 0 / 0.15);
  }
  .items > * {
    padding: 0.35rem 0.75rem;
    border: 0;
    background: none;
    color: inherit;
    font: inherit;
    text-align: left;
    text-decoration: none;
    cursor: pointer;
  }
  .items > :hover, .items > :focus-visible { background: color-mix(in srgb, CanvasText 10%, transparent); }
</style>
