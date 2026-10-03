<script lang="ts" module>
  export type DeckAction = "collapse" | "rename" | "delete" | "filteredOptions" | "rebuild" | "empty";
</script>

<script lang="ts">
  import type { DeckTreeNode } from "@generated/anki/decks_pb";
  import { IconChevronDown as ChevronDownIcon } from "@tabler/icons-svelte";
  import { IconChevronRight as ChevronRightIcon } from "@tabler/icons-svelte";
  import { IconDots as EllipsisIcon } from "@tabler/icons-svelte";
  import { Button } from "$lib/components/ui/button";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import * as Table from "$lib/components/ui/table";
  import DeckRows from "./DeckRows.svelte";

  let { decks, onaction }: { decks: DeckTreeNode[]; onaction: (action: DeckAction, deck: DeckTreeNode) => void } =
    $props();
  // Anki pages learn dark mode from the URL, as Anki tells them.
  const night = matchMedia("(prefers-color-scheme: dark)").matches ? "#night" : "";
</script>

{#each decks as deck (deck.deckId)}
  <Table.Row>
    <Table.Cell style="padding-left: {(deck.level - 1) * 1.25 + 0.5}rem">
      <div class="flex items-center gap-1">
        {#if deck.children.length}
          <Button
            variant="ghost"
            size="icon-xs"
            aria-expanded={!deck.collapsed}
            aria-label="{deck.collapsed ? 'Expand' : 'Collapse'} {deck.name}"
            onclick={() => onaction("collapse", deck)}
          >
            {#if deck.collapsed}<ChevronRightIcon />{:else}<ChevronDownIcon />{/if}
          </Button>
        {:else}
          <span class="size-6" aria-hidden="true"></span>
        {/if}
        <a
          href="/review?deck={deck.deckId}"
          class="font-medium hover:underline"
          class:text-primary={deck.filtered}>{deck.name}</a
        >
      </div>
    </Table.Cell>
    <Table.Cell class="text-right text-count-new tabular-nums">{deck.newCount}</Table.Cell>
    <Table.Cell class="text-right text-count-learn tabular-nums">{deck.learnCount}</Table.Cell>
    <Table.Cell class="text-right text-count-review tabular-nums">{deck.reviewCount}</Table.Cell>
    <Table.Cell class="text-right">
      <DropdownMenu.Root>
        <DropdownMenu.Trigger>
          {#snippet child({ props })}
            <Button {...props} variant="ghost" size="icon-sm" aria-label="Actions for {deck.name}">
              <EllipsisIcon />
            </Button>
          {/snippet}
        </DropdownMenu.Trigger>
        <DropdownMenu.Content align="end" class="w-40">
          <DropdownMenu.Group>
            {#if deck.filtered}
              <DropdownMenu.Item onSelect={() => onaction("filteredOptions", deck)}>Options</DropdownMenu.Item>
              <DropdownMenu.Item onSelect={() => onaction("rebuild", deck)}>Rebuild</DropdownMenu.Item>
              <DropdownMenu.Item onSelect={() => onaction("empty", deck)}>Empty</DropdownMenu.Item>
            {:else}
              <DropdownMenu.Item onSelect={() => (location.href = `/deck-options/${deck.deckId}${night}`)}>
                Options
              </DropdownMenu.Item>
            {/if}
            <DropdownMenu.Item onSelect={() => onaction("rename", deck)}>Rename</DropdownMenu.Item>
          </DropdownMenu.Group>
          <DropdownMenu.Separator />
          <DropdownMenu.Group>
            <DropdownMenu.Item variant="destructive" onSelect={() => onaction("delete", deck)}>Delete</DropdownMenu.Item>
          </DropdownMenu.Group>
        </DropdownMenu.Content>
      </DropdownMenu.Root>
    </Table.Cell>
  </Table.Row>
  {#if !deck.collapsed}<DeckRows decks={deck.children} {onaction} />{/if}
{/each}
