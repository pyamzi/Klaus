<script lang="ts">
  import type { DeckTreeNode } from "@generated/anki/decks_pb";
  import DeckRows from "./DeckRows.svelte";

  let { decks }: { decks: DeckTreeNode[] } = $props();
  // Anki pages learn dark mode from the URL, as Anki tells them.
  const night = matchMedia("(prefers-color-scheme: dark)").matches ? "#night" : "";
</script>

{#each decks as deck (deck.deckId)}
  <tr>
    <td style:padding-left="{deck.level - 1}rem">{deck.name}</td>
    <td class="new">{deck.newCount}</td>
    <td class="learn">{deck.learnCount}</td>
    <td class="review">{deck.reviewCount}</td>
    <td><a data-sveltekit-reload href="/deck-options/{deck.deckId}{night}" aria-label="Options for {deck.name}" title="Options">⚙</a></td>
  </tr>
  {#if !deck.collapsed}<DeckRows decks={deck.children} />{/if}
{/each}
