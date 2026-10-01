<script lang="ts">
  import { deckTree } from "$lib/generated/backend";
  import DeckRows from "./DeckRows.svelte";

  const tree = deckTree({ now: BigInt(Math.floor(Date.now() / 1000)) });
</script>

<main>
  <h1>Decks</h1>
  {#await tree}
    <p>Loading…</p>
  {:then root}
    <table>
      <thead><tr><th>Deck</th><th>New</th><th>Learn</th><th>Due</th></tr></thead>
      <tbody><DeckRows decks={root.children} /></tbody>
    </table>
  {:catch err}
    <p role="alert">{err.message}</p>
  {/await}
</main>

<style>
  :global(body) {
    font-family: system-ui, sans-serif;
    color: CanvasText;
    background: Canvas;
    color-scheme: light dark;
  }
  main { max-width: 40rem; margin: 2rem auto; padding: 0 1rem; }
  table { width: 100%; border-collapse: collapse; }
  th, :global(td) { padding: 0.35rem 0.5rem; text-align: right; }
  th:first-child, :global(td:first-child) { text-align: left; }
  :global(.new) { color: #2563eb; }
  :global(.learn) { color: #dc2626; }
  :global(.review) { color: #16a34a; }
</style>
