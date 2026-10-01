<script lang="ts">
  import type { DeckTreeNode } from "@generated/anki/decks_pb";
  import DeckRows from "./DeckRows.svelte";

  let { decks }: { decks: DeckTreeNode[] } = $props();
</script>

{#each decks as deck (deck.deckId)}
  <tr>
    <td style:padding-left="{deck.level - 1}rem"><a href="/review?deck={deck.deckId}">{deck.name}</a></td>
    <td class="new">{deck.newCount}</td>
    <td class="learn">{deck.learnCount}</td>
    <td class="review">{deck.reviewCount}</td>
  </tr>
  {#if !deck.collapsed}<DeckRows decks={deck.children} />{/if}
{/each}
