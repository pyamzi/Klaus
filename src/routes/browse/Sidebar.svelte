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
  import ChevronDownIcon from "@lucide/svelte/icons/chevron-down";
  import XIcon from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import * as Collapsible from "$lib/components/ui/collapsible";
  import { Input } from "$lib/components/ui/input";
  import { ScrollArea } from "$lib/components/ui/scroll-area";

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
  // A failed load was already alerted by the bridge.
  onMount(() => void refresh().catch(() => {}));

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
  <ul class="flex flex-col">
    {#each items as item (item.label)}
      <li>
        <Button variant="ghost" size="xs" class="w-full justify-start font-normal" onclick={() => onsearch(item.node)}>
          <span class="truncate">{item.label}</span>
        </Button>
        {#if item.children.length}<div class="pl-3">{@render tree(item.children)}</div>{/if}
      </li>
    {/each}
  </ul>
{/snippet}

{#snippet section(title: string, body: import("svelte").Snippet)}
  <Collapsible.Root open class="flex flex-col gap-1">
    <Collapsible.Trigger
      class="group flex w-full items-center gap-1 rounded-sm px-2 py-1 text-xs font-semibold text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <ChevronDownIcon class="size-3.5 transition-transform group-data-[state=closed]:-rotate-90" />
      {title}
    </Collapsible.Trigger>
    <Collapsible.Content class="pl-3">{@render body()}</Collapsible.Content>
  </Collapsible.Root>
{/snippet}

{#snippet savedSearches()}
  <ul class="flex flex-col">
    {#each Object.entries(saved) as [label, search] (label)}
      <li class="flex items-center">
        <Button
          variant="ghost"
          size="xs"
          class="flex-1 justify-start font-normal"
          onclick={() => onsearch(new SearchNode({ filter: { case: "parsableText", value: search } }))}
        >
          <span class="truncate">{label}</span>
        </Button>
        <Button variant="ghost" size="icon-xs" aria-label="Remove saved search {label}" onclick={() => removeSaved(label)}>
          <XIcon />
        </Button>
      </li>
    {/each}
  </ul>
  {#if naming}
    <form onsubmit={saveCurrent} class="flex gap-1 py-1">
      <Input bind:value={name} placeholder="Name" aria-label="Saved search name" class="h-7" required />
      <Button type="submit" size="xs">Save</Button>
    </form>
  {:else}
    <Button variant="link" size="xs" class="text-muted-foreground" onclick={() => (naming = true)}>Save current search</Button>
  {/if}
{/snippet}

{#snippet todayItems()}{@render tree(today)}{/snippet}
{#snippet flagItems()}{@render tree(flags)}{/snippet}
{#snippet stateItems()}{@render tree(states)}{/snippet}
{#snippet deckItems()}{@render tree(decks)}{/snippet}
{#snippet notetypeItems()}{@render tree(notetypes)}{/snippet}
{#snippet tagItems()}{@render tree(tags)}{/snippet}

<ScrollArea class="min-h-0 border-r">
  <nav aria-label="Browser sidebar" class="flex flex-col gap-2 p-2">
    {@render section("Saved Searches", savedSearches)}
    {@render section("Today", todayItems)}
    {@render section("Flags", flagItems)}
    {@render section("Card State", stateItems)}
    {@render section("Decks", deckItems)}
    {@render section("Note Types", notetypeItems)}
    {@render section("Tags", tagItems)}
  </nav>
</ScrollArea>
