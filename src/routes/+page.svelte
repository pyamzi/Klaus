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
  /* ≥4.5:1 against the Canvas background in both schemes. */
  :global(.new) { color: light-dark(#1d4ed8, #93c5fd); }
  :global(.learn) { color: light-dark(#b91c1c, #fca5a5); }
  :global(.review) { color: light-dark(#15803d, #86efac); }
</style>
