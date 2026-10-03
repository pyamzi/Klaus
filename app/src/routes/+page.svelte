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
  import { Empty } from "@generated/anki/generic_pb";
  import { postProto } from "@generated/post";
  import { onMount } from "svelte";
  import { toast } from "svelte-sonner";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as Field from "$lib/components/ui/field";
  import { Input } from "$lib/components/ui/input";
  import { nightHash } from "$lib/theme";
  import * as Select from "$lib/components/ui/select";
  import * as Table from "$lib/components/ui/table";
  import DeckRows, { type DeckAction } from "./DeckRows.svelte";
  import SyncControl from "./SyncControl.svelte";

  let root: DeckTreeNode | undefined = $state();
  let loadError = $state("");

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
    location.href = `/editor/?mode=add${nightHash()}`;
  }

  // Klaus's shell shows a file picker, then opens Anki's import page.
  function importPackage() {
    postProto("klausImportPackage", new Empty(), Empty).catch(() => {
      // Shown by the bridge.
    });
  }

  // Create / Rename. "Parent::Child" nests, as in Anki.
  let nameOpen = $state(false);
  let renaming: DeckTreeNode | undefined = $state();
  let name = $state("");
  function askName(deck?: DeckTreeNode) {
    renaming = deck;
    name = deck ? fullName(deck) : "";
    nameOpen = true;
  }
  // Undo reverts the collection's latest operation, so only the newest delete's
  // toast may offer it: any later change (another delete, a rename…) retires it.
  let undoToast: string | number | undefined;
  function retireUndo() {
    if (undoToast !== undefined) toast.dismiss(undoToast);
    undoToast = undefined;
  }

  // A save in flight: a second Enter mustn't add the deck twice.
  let busy = $state(false);

  async function saveName(event: SubmitEvent) {
    event.preventDefault();
    if (busy) return;
    retireUndo();
    const trimmed = name.trim();
    if (!trimmed) return;
    busy = true;
    try {
      if (renaming) {
        await renameDeck({ deckId: renaming.deckId, newName: trimmed });
      } else {
        const deck = await newDeck({});
        deck.name = trimmed;
        await addDeck(deck);
      }
      nameOpen = false;
      await refresh();
    } catch {
      // The bridge's error was already shown.
    } finally {
      busy = false;
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

  const orderLabel = (value: Order) => orders.find(([v]) => v === value)?.[1] ?? "";

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
  let filteredOpen = $state(false);
  let filtered: FilteredDeckForUpdate | undefined = $state();
  let filteredName = $state("");
  // Plain objects: $state doesn't track protobuf class instances.
  type Term = { search: string; limit: number; order: Order };
  let terms: Term[] = $state([]);
  let second = $state(false);
  let reschedule = $state(true);
  async function openFiltered(deckId = 0n) {
    try {
      const deck = await getOrCreateFilteredDeck({ did: deckId });
      const saved = deck.config!.searchTerms;
      const plain = ({ search, limit, order }: Term): Term => ({ search, limit, order });
      terms = [plain(saved[0]), saved[1] ? plain(saved[1]) : { search: "", limit: 20, order: Order.DUE }];
      // As Anki: a second filter shows as enabled only for an existing deck.
      second = deckId !== 0n && saved.length > 1;
      reschedule = deck.config!.reschedule;
      filteredName = deck.name;
      filtered = deck;
      filteredOpen = true;
    } catch {
      // Shown by the bridge.
    }
  }
  async function saveFiltered(event: SubmitEvent) {
    event.preventDefault();
    if (busy) return;
    retireUndo();
    const deck = filtered!;
    deck.name = filteredName;
    deck.config!.searchTerms = (second ? terms : terms.slice(0, 1)).map((t) => new Deck_Filtered_SearchTerm(t));
    deck.config!.reschedule = reschedule;
    busy = true;
    try {
      // Saving (re)builds the deck; Anki then shows it.
      await addOrUpdateFilteredDeck(deck);
      filteredOpen = false;
      await refresh();
    } catch {
      // e.g. no cards matched: shown by the bridge; the dialog stays open.
    } finally {
      busy = false;
    }
  }

  async function onaction(action: DeckAction, deck: DeckTreeNode) {
    if (action !== "rename" && action !== "filteredOptions") retireUndo();
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
          // As Anki: no confirmation, but an undo in the "N cards deleted" notice.
          const { count } = await removeDecks({ dids: [deck.deckId] });
          undoToast = toast(`Deleted ${deck.name} (${count} ${count === 1 ? "card" : "cards"})`, {
            action: { label: "Undo", onClick: undoDelete },
            onDismiss: () => (undoToast = undefined),
            onAutoClose: () => (undoToast = undefined),
          });
          break;
        }
      }
      await refresh();
    } catch {
      // Shown by the bridge.
    }
  }

  async function undoDelete() {
    undoToast = undefined;
    await undo({}).catch(() => {});
    await refresh();
  }
</script>

<main class="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-8">
  <header class="flex flex-wrap items-center justify-between gap-4">
    <div class="flex items-center gap-4">
      <h1 class="text-2xl font-semibold tracking-tight">Decks</h1>
      <SyncControl onsynced={refresh} />
    </div>
    <div class="flex flex-wrap gap-2">
      <Button onclick={addNote}>Add</Button>
      <Button variant="outline" onclick={() => (location.href = "/browse")}>Browse</Button>
      <Button variant="outline" onclick={() => askName()}>Create Deck</Button>
      <Button variant="outline" onclick={() => openFiltered()}>Filtered Deck…</Button>
      <Button variant="outline" onclick={importPackage}>Import…</Button>
    </div>
  </header>
  {#if root}
    <Table.Root>
      <Table.Header>
        <Table.Row>
          <Table.Head>Deck</Table.Head>
          <Table.Head class="text-right">New</Table.Head>
          <Table.Head class="text-right">Learn</Table.Head>
          <Table.Head class="text-right">Due</Table.Head>
          <Table.Head class="w-10"><span class="sr-only">Actions</span></Table.Head>
        </Table.Row>
      </Table.Header>
      <Table.Body><DeckRows decks={root.children} {onaction} /></Table.Body>
    </Table.Root>
  {:else if loadError}
    <p role="alert" class="text-destructive">{loadError}</p>
  {:else}
    <p class="text-muted-foreground">Loading…</p>
  {/if}
</main>

<Dialog.Root bind:open={nameOpen}>
  <Dialog.Content class="sm:max-w-sm">
    <form onsubmit={saveName} class="flex flex-col gap-4">
      <Dialog.Header>
        <Dialog.Title>{renaming ? "Rename Deck" : "Create Deck"}</Dialog.Title>
      </Dialog.Header>
      <Field.Group>
        <Field.Field>
          <Field.Label for="deck-name">Name</Field.Label>
          <Input id="deck-name" bind:value={name} required />
          <Field.Description>Use <code>::</code> to nest, e.g. <code>Biology::Cells</code>.</Field.Description>
        </Field.Field>
      </Field.Group>
      <Dialog.Footer>
        <Dialog.Close>
          {#snippet child({ props })}<Button {...props} variant="outline">Cancel</Button>{/snippet}
        </Dialog.Close>
        <Button type="submit" disabled={busy}>{renaming ? "Rename" : "Create"}</Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:open={filteredOpen}>
  <Dialog.Content class="sm:max-w-lg">
    {#if filtered}
      <form onsubmit={saveFiltered} class="flex flex-col gap-4">
        <Dialog.Header>
          <Dialog.Title>{filtered.id ? `Options for ${filteredName}` : "Filtered Deck"}</Dialog.Title>
        </Dialog.Header>
        <Field.Group>
          <Field.Field>
            <Field.Label for="filtered-name">Name</Field.Label>
            <Input id="filtered-name" bind:value={filteredName} required />
          </Field.Field>
          {#each terms as term, i (i)}
            {#if i === 0 || second}
              <Field.Set>
                <Field.Legend>{i === 0 ? "Filter" : "Filter 2"}</Field.Legend>
                <Field.Group>
                  <Field.Field>
                    <Field.Label for="search-{i}">Search</Field.Label>
                    <Input id="search-{i}" bind:value={term.search} />
                  </Field.Field>
                  <div class="flex gap-4">
                    <Field.Field>
                      <Field.Label for="limit-{i}">Limit to</Field.Label>
                      <Input id="limit-{i}" type="number" min="1" max="99999" bind:value={term.limit} required />
                    </Field.Field>
                    <Field.Field>
                      <Field.Label for="order-{i}">Cards selected by</Field.Label>
                      <Select.Root
                        type="single"
                        bind:value={() => String(term.order), (v) => (term.order = Number(v))}
                      >
                        <Select.Trigger id="order-{i}" class="w-full">{orderLabel(term.order)}</Select.Trigger>
                        <Select.Content>
                          <Select.Group>
                            {#each orders as [value, label] (value)}
                              <Select.Item value={String(value)} {label}>{label}</Select.Item>
                            {/each}
                          </Select.Group>
                        </Select.Content>
                      </Select.Root>
                    </Field.Field>
                  </div>
                </Field.Group>
              </Field.Set>
            {/if}
          {/each}
          <Field.Field orientation="horizontal">
            <Checkbox id="second-filter" bind:checked={second} />
            <Field.Label for="second-filter">Enable second filter</Field.Label>
          </Field.Field>
          <Field.Field orientation="horizontal">
            <Checkbox id="reschedule" bind:checked={reschedule} />
            <Field.Label for="reschedule">Reschedule cards based on my answers in this deck</Field.Label>
          </Field.Field>
        </Field.Group>
        <Dialog.Footer>
          <Dialog.Close>
            {#snippet child({ props })}<Button {...props} variant="outline">Cancel</Button>{/snippet}
          </Dialog.Close>
          <Button type="submit" disabled={busy}>{filtered.id ? "Rebuild" : "Build"}</Button>
        </Dialog.Footer>
      </form>
    {/if}
  </Dialog.Content>
</Dialog.Root>
