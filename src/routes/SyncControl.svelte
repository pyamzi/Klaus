<script lang="ts">
  // Collection sync through the Klaus Account (ADR-0007). Syncing is automatic (the
  // bridge syncs on open, on quit, and when there's something to sync); this shows
  // its status, signs in through the browser, offers a manual sync, and asks the
  // one question sync can't answer itself: which side wins a full sync.
  import { latestProgress, mediaSyncStatus, setProfileConfigJson } from "@generated/backend";
  import { BackendError_Kind } from "@generated/anki/backend_pb";
  import { SyncCollectionResponse_ChangesRequired as Required } from "@generated/anki/sync_pb";
  import { Empty, String as PbString } from "@generated/anki/generic_pb";
  import { FullSyncRequest, SyncAccount, SyncOutcome, SyncOutcome_State as State } from "@generated/klaus_pb";
  import { postProto } from "@generated/post";
  import { IconRefresh as RefreshCwIcon } from "@tabler/icons-svelte";
  import { IconCloudExclamation as CloudAlertIcon } from "@tabler/icons-svelte";
  import { IconCloudCheck as CloudCheckIcon } from "@tabler/icons-svelte";
  import { IconUserCircle as UserIcon } from "@tabler/icons-svelte";
  import { onMount } from "svelte";
  import { toast } from "svelte-sonner";
  import { Button } from "$lib/components/ui/button";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";

  /** Called after a sync finished (the deck list reloads its counts). */
  let { onsynced }: { onsynced: () => void } = $props();

  let account = $state(new SyncAccount());
  let outcome = $state(new SyncOutcome());
  let progress = $state("");
  let mediaStatus = $state("");
  let now = $state(Date.now());

  const call = <T extends object>(
    method: string,
    input: object,
    output: { fromBinary(b: Uint8Array): T },
    options?: { alertOnError?: boolean },
  ) => postProto(method, input as never, output as never, options) as Promise<T>;
  // Background reads: polled, so a failure mustn't alert() on every tick.
  const quiet = { alertOnError: false };
  const loadAccount = async () => (account = await call("klausSyncAccount", new Empty(), SyncAccount, quiet));
  const running = $derived(outcome.state === State.RUNNING);
  /** The last sync needs the user's choice (a full sync). */
  const needsChoice = $derived(outcome.state === State.DONE && !outcome.error && outcome.required >= Required.FULL_SYNC);

  // Each finished sync is handled once, whoever started it (the page or automatic sync).
  let handledId = 0;

  async function poll() {
    outcome = await call("klausSyncOutcome", new Empty(), SyncOutcome, quiet);
    now = Date.now();
    if (outcome.state === State.RUNNING) {
      const p = (await latestProgress({}, { alertOnError: false }).catch(() => undefined))?.value;
      if (p?.case === "normalSync") progress = [p.value.stage, p.value.added, p.value.removed].filter(Boolean).join(" · ");
      else if (p?.case === "fullSync" && p.value.total)
        progress = `${Math.round((p.value.transferred / p.value.total) * 100)}% of ${(p.value.total / 1048576).toFixed(1)} MB`;
    } else {
      progress = "";
    }
    if (outcome.state === State.DONE && outcome.id > handledId) {
      handledId = outcome.id;
      finished(outcome);
    }
  }

  function finished(result: SyncOutcome) {
    // The page started it (sync button, full sync); automatic syncs report only errors.
    const manual = !result.background;
    if (result.error) {
      // A failed full sync hands the dialog back, with its choices, to try again.
      fullRunning = false;
      if (result.errorKind === BackendError_Kind.SYNC_AUTH_ERROR) {
        loadAccount().catch(() => {});
        toast.error("Your Klaus account sign-in has expired. Sign in again to keep syncing.");
      } else if (manual) {
        toast.error(result.error);
      }
      return;
    }
    if (result.serverMessage) toast.info(result.serverMessage);
    if (result.required >= Required.FULL_SYNC) return askFullSync(result);
    if (fullRunning) {
      fullRunning = false;
      fullOpen = false;
      toast.success(
        "Full sync complete.",
        result.backupFolder ? { description: `Your previous collection was backed up to ${result.backupFolder}.` } : {},
      );
    } else if (manual) {
      toast.success("Collection synced.");
    }
    onsynced();
    watchMedia();
  }

  async function syncNow() {
    if (running) return;
    if (!account.email) return signIn();
    if (needsChoice) return askFullSync(outcome);
    try {
      await call("klausSync", new Empty(), Empty, quiet);
    } catch (err) {
      toast.error("Couldn't start syncing", { description: (err as Error).message });
      return;
    }
    await poll().catch(() => {});
  }

  async function watchMedia() {
    if (!account.syncMedia) return;
    for (;;) {
      // A failed media sync reports its error here once it stops.
      const media = await mediaSyncStatus({}, { alertOnError: false }).catch((err: Error) => {
        toast.error("Media sync failed", { description: err.message });
      });
      if (!media?.active) break;
      const p = media.progress;
      mediaStatus = p ? ["Media", p.checked, p.added, p.removed].filter(Boolean).join(" · ") : "Syncing media…";
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    mediaStatus = "";
  }

  // Full sync (aqt/sync.py full_sync / confirm_full_download / confirm_full_upload),
  // with Anki's wording. A download backs the Collection up first.
  let fullOpen = $state(false);
  let full: SyncOutcome | undefined = $state();
  let fullRunning = $state(false);
  function askFullSync(result: SyncOutcome) {
    full = result;
    fullOpen = true;
  }
  async function fullSync(upload: boolean) {
    const serverMediaUsn = account.syncMedia ? full!.serverMediaUsn : undefined;
    fullRunning = true;
    try {
      await call("klausFullSync", new FullSyncRequest({ upload, serverMediaUsn }), Empty);
      await poll();
    } catch {
      fullRunning = false;
    }
  }
  const fullText = $derived(
    full?.required === Required.FULL_DOWNLOAD
      ? "This device's collection has no cards. Download your collection from your Klaus account?"
      : full?.required === Required.FULL_UPLOAD
        ? "Your Klaus account's collection has no cards. Replace it with this device's collection?"
        : "There is a conflict between decks on this device and your Klaus account. You must choose which version to keep:",
  );

  // Browser sign-in: klaus.ink signs the user in, then sends them back to Klaus.
  let signInOpen = $state(false);
  let signInUrl = $state("");
  async function signIn() {
    try {
      signInUrl = (await call("klausAccountSignIn", new Empty(), PbString, quiet)).val;
    } catch (err) {
      toast.error("Couldn't start signing in", { description: (err as Error).message });
      return;
    }
    openLink(signInUrl);
    signInOpen = true;
    while (signInOpen) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      await loadAccount().catch(() => {});
      if (account.email) {
        signInOpen = false;
        toast.success(`Signed in as ${account.email}.`);
        syncNow();
      }
    }
  }
  function openLink(url: string) {
    postProto("openLink", new PbString({ val: url }), Empty, { alertOnError: false }).catch(() => {});
  }

  async function toggle(key: "autoSync" | "syncMedia", value: boolean) {
    try {
      await setProfileConfigJson({ key, valueJson: new TextEncoder().encode(JSON.stringify(value)) }, quiet);
    } catch (err) {
      toast.error("Couldn't change the sync setting", { description: (err as Error).message });
      return;
    }
    // Saved; a failed reload only leaves the menu showing the old value.
    await loadAccount().catch(() => {});
  }
  async function signOut() {
    try {
      await call("klausSyncSignOut", new Empty(), Empty, quiet);
    } catch (err) {
      toast.error("Couldn't sign out", { description: (err as Error).message });
      return;
    }
    await loadAccount().catch(() => {});
  }

  const statusText = $derived.by(() => {
    if (running) return progress || "Syncing…";
    if (mediaStatus) return mediaStatus;
    if (!account.email) return "";
    if (outcome.state === State.DONE && outcome.error) return "Sync failed";
    if (needsChoice) return "Full sync needed";
    if (outcome.finishedMs) {
      const minutes = Math.floor((now - Number(outcome.finishedMs)) / 60000);
      return minutes < 1 ? "Synced just now" : `Synced ${minutes} min ago`;
    }
    return "";
  });

  onMount(() => {
    loadAccount().catch(() => {});
    // A sync that finished before this page opened isn't news; a full sync still
    // waiting for a choice is asked about again.
    call("klausSyncOutcome", new Empty(), SyncOutcome, quiet)
      .then((current) => {
        handledId = current.state === State.DONE && current.required < Required.FULL_SYNC ? current.id : 0;
        return poll();
      })
      .catch(() => {});
    const timer = setInterval(() => poll().catch(() => {}), 2000);
    return () => clearInterval(timer);
  });
</script>

<div class="flex items-center gap-2">
  {#if account.email}
    <Button
      variant="ghost"
      size="sm"
      onclick={syncNow}
      disabled={running}
      title={needsChoice ? "Choose how to finish syncing" : "Sync now"}
      class="text-muted-foreground"
    >
      {#if running}
        <RefreshCwIcon data-icon="inline-start" class="animate-spin" />
      {:else if (outcome.state === State.DONE && outcome.error) || needsChoice}
        <CloudAlertIcon data-icon="inline-start" />
      {:else}
        <CloudCheckIcon data-icon="inline-start" />
      {/if}
      <span aria-live="polite">{statusText || "Sync"}</span>
    </Button>
    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        {#snippet child({ props })}
          <Button {...props} variant="ghost" size="icon" aria-label="Klaus account"><UserIcon /></Button>
        {/snippet}
      </DropdownMenu.Trigger>
      <DropdownMenu.Content align="end" class="w-64">
        <DropdownMenu.Group>
          <DropdownMenu.Label class="truncate">{account.email}</DropdownMenu.Label>
        </DropdownMenu.Group>
        <DropdownMenu.Separator />
        <DropdownMenu.Group>
          <DropdownMenu.CheckboxItem checked={account.autoSync} onCheckedChange={(v) => toggle("autoSync", v)}>
            Sync automatically
          </DropdownMenu.CheckboxItem>
          <DropdownMenu.CheckboxItem checked={account.syncMedia} onCheckedChange={(v) => toggle("syncMedia", v)}>
            Sync media
          </DropdownMenu.CheckboxItem>
        </DropdownMenu.Group>
        <DropdownMenu.Separator />
        <DropdownMenu.Group>
          <DropdownMenu.Item onSelect={signOut}>Sign out</DropdownMenu.Item>
        </DropdownMenu.Group>
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  {:else}
    <Button variant="outline" onclick={signIn}>Sign in to sync</Button>
  {/if}
</div>

<Dialog.Root bind:open={signInOpen}>
  <Dialog.Content class="sm:max-w-sm">
    <Dialog.Header>
      <Dialog.Title>Finish signing in in your browser</Dialog.Title>
      <Dialog.Description>
        Sign in to your Klaus account on klaus.ink. KlausNote will pick it up as soon as you're done.
      </Dialog.Description>
    </Dialog.Header>
    <p class="text-sm text-muted-foreground">
      Browser didn't open?
      <Button variant="link" class="h-auto p-0" onclick={() => openLink(signInUrl)}>Open klaus.ink</Button>
    </p>
    <Dialog.Footer>
      <Dialog.Close>
        {#snippet child({ props })}<Button {...props} variant="outline">Cancel</Button>{/snippet}
      </Dialog.Close>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<!-- A full sync takes the Collection away while it runs, so this stays modal until done. -->
<Dialog.Root bind:open={() => fullOpen, (open) => (fullOpen = open || fullRunning)}>
  <Dialog.Content class="sm:max-w-lg" showCloseButton={!fullRunning}>
    <Dialog.Header>
      <Dialog.Title>{fullRunning ? progress || "Syncing…" : "Full sync required"}</Dialog.Title>
      {#if !fullRunning}
        <Dialog.Description>{fullText}</Dialog.Description>
      {/if}
    </Dialog.Header>
    {#if fullRunning}
      <p class="text-sm text-muted-foreground">KlausNote can't be used until this finishes.</p>
    {:else if full?.required === Required.FULL_SYNC}
      <ul class="flex list-disc flex-col gap-2 pl-5 text-sm">
        <li>
          Select <strong>Download</strong> to replace decks here with your Klaus account's version. You will lose any changes
          you made on this device since your last sync.
        </li>
        <li>
          Select <strong>Upload</strong> to overwrite your Klaus account's version with decks from this device, and delete
          any changes made on your other devices.
        </li>
      </ul>
      <p class="text-sm text-muted-foreground">Once the conflict is resolved, syncing will work as usual.</p>
    {/if}
    {#if !fullRunning}
      <Dialog.Footer>
        <Dialog.Close>
          {#snippet child({ props })}<Button {...props} variant="outline">Not now</Button>{/snippet}
        </Dialog.Close>
        {#if full?.required !== Required.FULL_DOWNLOAD}
          <Button variant={full?.required === Required.FULL_UPLOAD ? "default" : "outline"} onclick={() => fullSync(true)}>
            Upload
          </Button>
        {/if}
        {#if full?.required !== Required.FULL_UPLOAD}
          <Button onclick={() => fullSync(false)}>Download</Button>
        {/if}
      </Dialog.Footer>
    {/if}
  </Dialog.Content>
</Dialog.Root>
