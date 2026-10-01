<script lang="ts">
  import type { DeckTreeNode } from "$lib/generated/anki/decks_pb";
  import DeckRows from "./DeckRows.svelte";

  let { decks }: { decks: DeckTreeNode[] } = $props();
</script>

{#each decks as deck (deck.deckId)}
  <tr>
    <td style:padding-left="{deck.level - 1}rem">{deck.name}</td>
    <td class="new">{deck.newCount}</td>
    <td class="learn">{deck.learnCount}</td>
    <td class="review">{deck.reviewCount}</td>
  </tr>
  {#if !deck.collapsed}<DeckRows decks={deck.children} />{/if}
{/each}
