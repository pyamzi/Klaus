<script lang="ts">
  // AnkiWeb sync, as aqt/sync.py drives it: sign in, sync (then media in the
  // background), and the full-sync choice. The sync key never reaches the page:
  // the bridge's klausSync* methods hold it (Keychain).
  import { latestProgress, mediaSyncStatus, setProfileConfigJson } from "@generated/backend";
  import { BackendError_Kind } from "@generated/anki/backend_pb";
  import { SyncCollectionResponse_ChangesRequired as Required } from "@generated/anki/sync_pb";
  import { Empty, String as PbString } from "@generated/anki/generic_pb";
  import { FullSyncRequest, SyncAccount, SyncOutcome, SyncOutcome_State as State, SyncSignIn } from "@generated/klaus_pb";
  import { postProto } from "@generated/post";
  import RefreshCwIcon from "@lucide/svelte/icons/refresh-cw";
  import UserIcon from "@lucide/svelte/icons/circle-user";
  import { onMount } from "svelte";
  import { toast } from "svelte-sonner";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import * as Collapsible from "$lib/components/ui/collapsible";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import * as Field from "$lib/components/ui/field";
  import { Input } from "$lib/components/ui/input";

  /** Called after a sync changed the Collection (the deck list reloads). */
  let { onsynced }: { onsynced: () => void } = $props();

  let account = $state(new SyncAccount());
  let busy = $state(false);
  let status = $state("");
  let mediaStatus = $state("");

  const call = <T extends object>(method: string, input: object, output: { fromBinary(b: Uint8Array): T }) =>
    postProto(method, input as never, output as never) as Promise<T>;
  const loadAccount = async () => (account = await call("klausSyncAccount", new Empty(), SyncAccount));

  const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

  /** Polls a background sync (klausSync / klausFullSync) until it's done, showing
   * its progress like aqt/sync.py's 150 ms timer. */
  async function outcome(): Promise<SyncOutcome> {
    for (;;) {
      await wait(150);
      const progress = (await latestProgress({}, { alertOnError: false }).catch(() => undefined))?.value;
      if (progress?.case === "normalSync") {
        const { stage, added, removed } = progress.value;
        status = [stage, added, removed].filter(Boolean).join(" · ");
      } else if (progress?.case === "fullSync" && progress.value.total) {
        const { transferred, total } = progress.value;
        status = `${Math.round((transferred / total) * 100)}% of ${(total / 1024 / 1024).toFixed(1)} MB`;
      }
      const result = await call("klausSyncOutcome", new Empty(), SyncOutcome);
      if (result.state === State.DONE) return result;
    }
  }

  async function sync() {
    if (busy) return;
    if (!account.username) return openSignIn();
    busy = true;
    status = "Checking…";
    try {
      await call("klausSync", new Empty(), Empty);
      const result = await outcome();
      if (failed(result)) return;
      if (result.serverMessage) toast.info(result.serverMessage);
      if (result.required === Required.NO_CHANGES || result.required === Required.NORMAL_SYNC) {
        toast.success("Collection sync complete.");
        onsynced();
        watchMedia();
      } else {
        askFullSync(result);
      }
    } catch {
      // The bridge's error was shown.
    } finally {
      busy = false;
      status = "";
    }
  }

  /** Shows a sync error; an expired sign-in (the bridge signed out) asks again. */
  function failed(result: SyncOutcome): boolean {
    if (!result.error) return false;
    if (result.errorKind === BackendError_Kind.SYNC_AUTH_ERROR) {
      loadAccount();
      openSignIn(result.error);
    } else {
      toast.error(result.error);
    }
    return true;
  }

  async function watchMedia() {
    if (!account.syncMedia) return;
    for (;;) {
      const media = await mediaSyncStatus({}, { alertOnError: false }).catch(() => undefined);
      if (!media?.active) break;
      const p = media.progress;
      mediaStatus = p ? ["Media", p.checked, p.added, p.removed].filter(Boolean).join(" · ") : "Syncing media…";
      await wait(1000);
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
    const result = full!;
    fullRunning = true;
    status = upload ? "Uploading to AnkiWeb…" : "Downloading from AnkiWeb…";
    try {
      const serverMediaUsn = account.syncMedia ? result.serverMediaUsn : undefined;
      await call("klausFullSync", new FullSyncRequest({ upload, serverMediaUsn }), Empty);
      const done = await outcome();
      fullOpen = false;
      if (failed(done)) return;
      toast.success(
        upload ? "Uploaded to AnkiWeb." : "Downloaded from AnkiWeb.",
        done.backupFolder ? { description: `Your previous collection was backed up to ${done.backupFolder}.` } : {},
      );
      onsynced();
      watchMedia();
    } finally {
      fullRunning = false;
      status = "";
    }
  }

  // Sign in (aqt/sync.py get_id_and_pass_from_user), with the self-hosted server
  // and the two sync preferences Anki keeps in its profile.
  let signInOpen = $state(false);
  let signInError = $state("");
  let signingIn = $state(false);
  let username = $state("");
  let password = $state("");
  let customUrl = $state("");
  let autoSync = $state(true);
  let syncMedia = $state(true);
  function openSignIn(error = "") {
    signInError = error;
    username = account.username;
    password = "";
    customUrl = account.customUrl;
    autoSync = account.autoSync;
    syncMedia = account.syncMedia;
    signInOpen = true;
  }
  async function signIn(event: SubmitEvent) {
    event.preventDefault();
    signInError = "";
    signingIn = true;
    try {
      if (customUrl.trim() !== account.customUrl) await call("klausSetSyncUrl", new PbString({ val: customUrl }), Empty);
      await saveFlag("autoSync", autoSync);
      await saveFlag("syncMedia", syncMedia);
      await postProto("klausSyncSignIn", new SyncSignIn({ username: username.trim(), password }), Empty, {
        alertOnError: false,
      });
      await loadAccount();
      signInOpen = false;
      sync();
    } catch (err) {
      signInError = err instanceof Error ? err.message : String(err);
    } finally {
      signingIn = false;
    }
  }

  function saveFlag(key: "autoSync" | "syncMedia", value: boolean) {
    return setProfileConfigJson({ key, valueJson: new TextEncoder().encode(JSON.stringify(value)) });
  }
  async function toggle(key: "autoSync" | "syncMedia", value: boolean) {
    await saveFlag(key, value);
    await loadAccount();
  }
  async function signOut() {
    await call("klausSyncSignOut", new Empty(), Empty);
    await loadAccount();
  }

  onMount(async () => {
    await loadAccount();
    // Anki syncs when the profile opens; once per launch, not on every return to the deck list.
    let opened = false;
    try {
      opened = sessionStorage.getItem("klausSyncedOnOpen") === "1";
      sessionStorage.setItem("klausSyncedOnOpen", "1");
    } catch {
      // Storage unavailable: sync anyway.
    }
    if (!opened && account.username && account.autoSync) sync();
  });

  // Full-sync wording, by what the server requires.
  const fullText = $derived(
    full?.required === Required.FULL_DOWNLOAD
      ? "Local collection has no cards. Download from AnkiWeb?"
      : full?.required === Required.FULL_UPLOAD
        ? "AnkiWeb collection has no cards. Replace it with local collection?"
        : "There is a conflict between decks on this device and AnkiWeb. You must choose which version to keep:",
  );
</script>

<div class="flex items-center gap-2">
  {#if status || mediaStatus}
    <span class="text-sm text-muted-foreground" aria-live="polite">{status || mediaStatus}</span>
  {/if}
  <Button variant="outline" onclick={sync} disabled={busy} title={account.username ? "Sync with AnkiWeb" : "Sign in to sync"}>
    <RefreshCwIcon data-icon="inline-start" class={busy ? "animate-spin" : ""} />
    Sync
  </Button>
  {#if account.username}
    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        {#snippet child({ props })}
          <Button {...props} variant="ghost" size="icon" aria-label="AnkiWeb account"><UserIcon /></Button>
        {/snippet}
      </DropdownMenu.Trigger>
      <DropdownMenu.Content align="end" class="w-64">
        <DropdownMenu.Group>
          <DropdownMenu.Label class="truncate">{account.username}</DropdownMenu.Label>
          {#if account.customUrl}
            <DropdownMenu.Label class="truncate text-xs font-normal text-muted-foreground">{account.customUrl}</DropdownMenu.Label>
          {/if}
        </DropdownMenu.Group>
        <DropdownMenu.Separator />
        <DropdownMenu.Group>
          <DropdownMenu.CheckboxItem checked={account.autoSync} onCheckedChange={(v) => toggle("autoSync", v)}>
            Sync on open and close
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
  {/if}
</div>

<Dialog.Root bind:open={signInOpen}>
  <Dialog.Content class="sm:max-w-sm">
    <form onsubmit={signIn} class="flex flex-col gap-4">
      <Dialog.Header>
        <Dialog.Title>Sign in to AnkiWeb</Dialog.Title>
        <Dialog.Description>
          Syncs your collection with Anki on your other devices. Your AnkiWeb key is kept in the macOS Keychain.
        </Dialog.Description>
      </Dialog.Header>
      <Field.Group>
        <Field.Field data-invalid={signInError ? true : undefined}>
          <Field.Label for="sync-user">Email</Field.Label>
          <Input id="sync-user" type="email" autocomplete="username" bind:value={username} required />
        </Field.Field>
        <Field.Field data-invalid={signInError ? true : undefined}>
          <Field.Label for="sync-password">Password</Field.Label>
          <Input
            id="sync-password"
            type="password"
            autocomplete="current-password"
            bind:value={password}
            aria-invalid={signInError ? true : undefined}
            required
          />
          {#if signInError}<Field.Error>{signInError}</Field.Error>{/if}
        </Field.Field>
        <Field.Field orientation="horizontal">
          <Checkbox id="sync-auto" bind:checked={autoSync} />
          <Field.Label for="sync-auto">Sync on open and close</Field.Label>
        </Field.Field>
        <Field.Field orientation="horizontal">
          <Checkbox id="sync-media" bind:checked={syncMedia} />
          <Field.Label for="sync-media">Sync media</Field.Label>
        </Field.Field>
        <Collapsible.Root open={!!customUrl}>
          <Collapsible.Trigger class="text-sm text-muted-foreground underline-offset-4 hover:underline">
            Self-hosted sync server
          </Collapsible.Trigger>
          <Collapsible.Content class="pt-2">
            <Field.Field>
              <Field.Label for="sync-url">Server URL</Field.Label>
              <Input id="sync-url" type="url" placeholder="https://sync.example.com/" bind:value={customUrl} />
              <Field.Description>Leave empty for AnkiWeb.</Field.Description>
            </Field.Field>
          </Collapsible.Content>
        </Collapsible.Root>
      </Field.Group>
      <Dialog.Footer>
        <Dialog.Close>
          {#snippet child({ props })}<Button {...props} variant="outline">Cancel</Button>{/snippet}
        </Dialog.Close>
        <Button type="submit" disabled={signingIn}>{signingIn ? "Signing in…" : "Sign in"}</Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>

<!-- A full sync takes the Collection away while it runs, so this stays modal until done. -->
<Dialog.Root
  bind:open={() => fullOpen, (open) => (fullOpen = open || fullRunning)}
>
  <Dialog.Content class="sm:max-w-lg" showCloseButton={!fullRunning}>
    <Dialog.Header>
      <Dialog.Title>{fullRunning ? status : "Full sync required"}</Dialog.Title>
      {#if !fullRunning}
        <Dialog.Description>{fullText}</Dialog.Description>
      {/if}
    </Dialog.Header>
    {#if fullRunning}
      <p class="text-sm text-muted-foreground">Klaus can't be used until this finishes.</p>
    {:else if full?.required === Required.FULL_SYNC}
      <ul class="flex list-disc flex-col gap-2 pl-5 text-sm">
        <li>
          Select <strong>Download from AnkiWeb</strong> to replace decks here with AnkiWeb’s version. You will lose any
          changes you made on this device since your last sync.
        </li>
        <li>
          Select <strong>Upload to AnkiWeb</strong> to overwrite AnkiWeb’s versions with decks from this device, and delete
          any changes on AnkiWeb.
        </li>
      </ul>
      <p class="text-sm text-muted-foreground">Once the conflict is resolved, syncing will work as usual.</p>
    {/if}
    {#if !fullRunning}
      <Dialog.Footer>
        <Dialog.Close>
          {#snippet child({ props })}<Button {...props} variant="outline">Cancel</Button>{/snippet}
        </Dialog.Close>
        {#if full?.required !== Required.FULL_DOWNLOAD}
          <Button variant={full?.required === Required.FULL_UPLOAD ? "default" : "outline"} onclick={() => fullSync(true)}>
            Upload to AnkiWeb
          </Button>
        {/if}
        {#if full?.required !== Required.FULL_UPLOAD}
          <Button onclick={() => fullSync(false)}>Download from AnkiWeb</Button>
        {/if}
      </Dialog.Footer>
    {/if}
  </Dialog.Content>
</Dialog.Root>
