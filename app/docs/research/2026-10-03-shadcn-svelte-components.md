# What do shadcn-svelte's Sidebar, Command, Sonner and Kbd need in this app?

Research for issue #39 (child of map #37, "Klaus look"). Names follow `CONTEXT.md`: Home, Study, Browser, Sidebar, Command Palette.

**Versions read** (from `node_modules` in the main checkout): `shadcn-svelte` CLI 1.7.0, `bits-ui` 2.19.4, `svelte-sonner` 1.2.1, `mode-watcher` 1.1.0. Component source is the `nova` registry (`https://shadcn-svelte.com/registry/styles/nova/<name>.json`, fetched 2026-10-02), which is what `add` installs; docs are `https://shadcn-svelte.com/docs/components/<name>.md`.

## Answer in short

| Component | Install | Provider / state | Ships keys | Guard the app needs |
| --- | --- | --- | --- | --- |
| Sidebar | `npx shadcn-svelte@latest add sidebar` | `Sidebar.Provider` per layout; read the `sidebar_state` cookie yourself | ⌘B / Ctrl+B toggle (window, any focus) | none for ⌘B; plain `B` (browse) must ignore modifiers |
| Command | `npx shadcn-svelte@latest add command` | none; own `open` state plus an app-written ⌘K | arrows, Home/End, Enter, Ctrl+N/J/P/K (vim, on by default); Esc comes from Dialog | Study and Browser handlers must stand down for events in the dialog; `vimBindings={false}` |
| Sonner | already installed and mounted; nothing to add | none; keep `theme="system"` | Alt+T focus, Esc collapse (only with focus in the list) | Study handler must ignore events from `[data-sonner-toaster]` |
| Kbd | `npx shadcn-svelte@latest add kbd` | none | none (display only) | none |

One command for the three missing ones: `npx shadcn-svelte@latest add sidebar command kbd`. It also pulls `sheet`, `tooltip`, `skeleton`, `input-group`, `textarea` and the `is-mobile` hook (`src/lib/hooks/is-mobile.svelte.ts`); `button`, `input`, `separator`, `dialog` already exist, so do not pass `--overwrite`, and read `git diff` afterwards. No new npm package: `bits-ui`, `@internationalized/date`, `tailwind-variants`, `svelte-sonner`, `mode-watcher` are all in `devDependencies`.

## What the app looks like to these components

- `svelte.config.js`: adapter-static with `fallback: "index.html"`; `src/routes/+layout.ts` sets `ssr = false`. There is no server, so nothing here can read request cookies; every component runs only in the browser.
- The Tauri shell serves the UI from the Backend Bridge: the window is `WebviewUrl::External("http://127.0.0.1:<port>/")`, with the port chosen by the OS on every launch (`crates/bridge/src/lib.rs` binds `("127.0.0.1", 0)`). `src-tauri/src/main.rs` sets no custom menu. The web build is the same UI (ADR-0006).
- Navigation between Home, Study and Browser is `location.href = ...`, a full page load, so a root layout and everything in it (palette state, toasts, sidebar state) is rebuilt on every screen change.
- `src/app.css` already defines the `--sidebar-*` tokens and `@custom-variant dark (@media (prefers-color-scheme: dark))`, so shadcn's `dark:` utilities follow the system and no `.dark` class is needed.

## Sidebar

**Requires.** `Sidebar.Provider` above every `Sidebar.*` part: `Sidebar.Root` and the rest call `useSidebar()`, which is `getContext` on a symbol and has no fallback (`context.svelte.ts`). The provider also supplies `Tooltip.Provider`. Install adds `sheet`, `tooltip`, `skeleton`, the `is-mobile` hook (a `MediaQuery("max-width: 767px")`). Under 768px `Sidebar.Root` renders a `Sheet` (a bits-ui Dialog) instead of the column, so it is not the phone tab bar from `CONTEXT.md`; keep the tab bar a separate component and treat the Sheet as an accident to avoid or restyle (Tauri's window is resizable, so a narrow window reaches it).

**Cookie state.** `Sidebar.Provider`'s `setOpen` writes `document.cookie = "sidebar_state=<true|false>; path=/; max-age=604800"` and nothing in the component ever reads it (`sidebar-provider.svelte`; the docs page says nothing about persistence). In a SvelteKit app the reader is a `+layout.server.ts`; adapter-static has none, so as installed the sidebar opens expanded on every load. Because every screen change is a full load here, that means it re-expands each time you go Home to Browser. The write works (it is `document.cookie`, client-side); the read is ours to add, synchronously, so there is no flash (the page is not server-rendered):

```svelte
<script lang="ts">
  import * as Sidebar from "$lib/components/ui/sidebar";
  const saved = document.cookie.split("; ").find((c) => c.startsWith("sidebar_state="))?.split("=")[1];
  let open = $state(saved !== "false");
  let { children } = $props();
</script>
<Sidebar.Provider bind:open>{@render children()}</Sidebar.Provider>
```

In Tauri this should survive launches: cookies are host-scoped, not port-scoped (the bridge's own comment says so: `klaus_<port>` cookie names exist because "Cookies aren't scoped by port"), so the changing port does not orphan it. The bridge's auth check splits the `Cookie` header on `;` and tests each entry, so an extra cookie is harmless (`crates/bridge/src/lib.rs`, around line 1250). Do not use `localStorage` for this: it is scoped by origin including the port, so it would reset every launch. The alternative, if state should follow the account across devices, is a Collection config key through the bridge (`setConfigJson`, as `browse/Sidebar.svelte` does for saved filters), at the price of an async first paint.

**Where the Provider goes.** Study has no Sidebar, so put the Provider in a route group that holds Home and Browser, e.g. `src/routes/(shell)/+layout.svelte`, and leave `review` outside it. Moving `+page.svelte` into `(shell)/` does not change URLs. This also keeps ⌘B out of Study.

**Layout fit.** The Provider is `flex min-h-svh w-full`; the default `collapsible="offcanvas"` renders a spacer div plus a `fixed inset-y-0` panel, and content goes in `Sidebar.Inset` (a `<main>`). Browser's current `grid-cols-[14rem_...]` with its own `browse/Sidebar.svelte` therefore changes shape: the Sidebar column leaves the grid. `collapsible="none"` renders an in-flow `div` instead (fits a grid column) but drops collapsing and ⌘B. Default width is 16rem; Browser uses 14rem, set with `style="--sidebar-width: 14rem"` on the Provider (the style attribute is appended after the default).

**Keyboard shipped.** One shortcut: `Sidebar.Provider` mounts `<svelte:window onkeydown>` that, on `e.key === "b"` with `metaKey || ctrlKey`, calls `preventDefault()` and toggles (`SIDEBAR_KEYBOARD_SHORTCUT` in `constants.ts`). It fires from any focus, text inputs included, and ignores `altKey`/`shiftKey`. No arrow-key navigation: menu items are ordinary tabbable buttons or links; the rail button is `tabindex=-1`. Keys inside the Anki editor and card iframes are separate documents and never reach it.

**Conflicts.** None with today's handlers: Study returns `false` for any ctrl/meta key it does not own and Browser only owns ⌘⇧P. The risk is the design system's plain `B` (browse): a future handler that tests `e.key === "b"` without checking modifiers would also fire on ⌘B. Rule for every single-letter shortcut: bail on `metaKey || ctrlKey || altKey`. Add "Toggle Sidebar ⌘B" to the palette so it is discoverable.

**Recommendation.** `add sidebar`; Provider in a `(shell)` route group with the cookie read above; Sidebar only in Home and Browser; keep ⌘B; no `Sheet` behaviour for phones.

## Command

**Requires.** `add command` installs `command/*` and `input-group/*` (registry dependencies: `dialog`, `input-group`; the latter needs `button`, `input`, `textarea`). The primitive is bits-ui's `Command`. No provider. For a palette use `Command.Dialog`: it is `Dialog.Root` + `Dialog.Content` (a screen-reader `Dialog.Title` "Command Palette" and description are built in, `showCloseButton` defaults to false) around `Command.Root`, with `bind:open` and every other prop forwarded to both.

**⌘K is not shipped.** Neither the docs page nor `command-dialog.svelte` binds any key to open it. The app writes it once, in the root `+layout.svelte`, so Home, Study and Browser all get it (Anki's own pages, the editor, deck options, import, are separate documents and will not):

```svelte
<svelte:window onkeydown={(e) => { if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === "k") { e.preventDefault(); open = !open; } }} />
<Command.Dialog bind:open vimBindings={false}> ... </Command.Dialog>
```

**Keyboard shipped** (bits-ui `command.svelte.js`, handler on the Command root, so only while focus is inside it): ArrowDown/ArrowUp move the selection (⌘+arrow jumps to the end, ⌥+arrow moves by group); Home/End first/last; Enter clicks the selected item (skipped during IME composition); typing in `Command.Input` is the type-ahead: a fuzzy score (`compute-command-score.js`) over each item's `value` (default: its text) plus `keywords`, re-sorting and resetting selection to the first match (`shouldFilter`/`filter` override it). **`vimBindings` defaults to `true`** (`command.svelte`): Ctrl+N/J next, Ctrl+P/K previous, each with `preventDefault`. Esc is not Command's: it comes from the Dialog, which listens on `document` (bits-ui `use-escape-layer.svelte.js`) and calls `preventDefault()` on the event. Focus is trapped in the dialog and returns to the previously focused element on close.

**Conflicts.**

1. Vim bindings against our own keys. On Windows and Linux ⌘K is Ctrl+K and ⌘N (new note) is Ctrl+N; inside the palette Ctrl+K would move the selection up and Ctrl+N down, then the event still bubbles to our window handler. Set `vimBindings={false}`. On macOS the vim keys need `ctrlKey`, so ⌘K and ⌘N do not collide there.
2. Study's window handler has no focus awareness: it treats `1`-`4`, Space, Enter and `u` as grade/reveal/undo wherever they come from, and calls `preventDefault()`. With the palette open over Study, typing "u" undoes a card, typing "2" grades Hard, and Enter both selects the item (Command clicks it) and reveals or grades the card, because Command does not stop propagation. This writes to the Collection, so the guard is mandatory (below).
3. Browser's Esc leaves for Home unless `document.querySelector('[role="dialog"], [role="menu"]')` finds an open layer (`browse/+page.svelte`). That works only while the closing animation keeps the dialog node in the DOM; the Escape layer's `defaultPrevented` is the reliable signal.
4. Browser's arrow handler (`onTableKey`) is on the table element, and the dialog is portalled out of it, so Command's arrows do not reach it. When the palette closes, focus returns to the table.
5. ⌘K never reaches the page when focus is inside a framed document: the card frame (`static/card-host.js` forwards only Space, Enter and 1-4, and drops anything with ctrl/meta), the Anki editor frame, the preview frame. Follow-up for the implementation issue: forward ⌘K from `card-host.js` and from `anki-host.js` (embedded mode) by `postMessage` and have the layout listen.

**Recommendation.** `add command`; `Command.Dialog` in the root layout with `vimBindings={false}`, items grouped in `Command.Group`, each action closing the palette first (`open = false`, then run it, so the focus return does not steal focus from a dialog the action opens), `Command.Shortcut` for the key.

## Sonner

**Requires.** Already in place: `src/lib/components/ui/sonner/sonner.svelte`, `<Toaster theme="system" />` in the root layout, and `toast(..., { action: { label: "Undo", onClick } })` on Home. Packages `svelte-sonner` and `mode-watcher` (the registry lists both as dependencies of `sonner`). No provider, nothing to install.

**mode-watcher.** `sonner.svelte` imports `mode` and passes `theme={mode.current}` before `{...restProps}`; the layout's `theme="system"` therefore wins. Reading the sources: `mode-watcher`'s module top level builds `userPrefersMode` (reads `localStorage["mode-watcher-mode"]`) and `systemPrefersMode` (a `MediaQuery`) when imported, but the DOM side effects (setting `style.colorScheme`, a transition-suppressing `<style>`, a `dark` class) live in the `derivedMode` getter and in the `ModeWatcher` component. With `theme` supplied, Svelte's spread props never evaluate the shadowed `mode.current`, and `ModeWatcher` is not mounted, so nothing is touched. `svelte-sonner` resolves `theme="system"` itself with `matchMedia("(prefers-color-scheme: dark)")` and follows live changes (`Toaster.svelte`). Keep `theme="system"` on every `<Toaster>`; without it, the first read of `mode.current` writes an inline `color-scheme` on `<html>`. Do not mount `ModeWatcher` (it would add a `dark` class and persist a mode the app does not have). The upstream docs describe removing `mode-watcher` entirely, but leaving the generated file untouched keeps `shadcn-svelte update` diff-free and costs one `localStorage` read.

**Keyboard shipped** (`svelte-sonner` `Toaster.svelte`, a `document` keydown listener): Alt+T (`hotkey = ['altKey','KeyT']`, matches `event.code`, so macOS Option+T works) expands the stack and focuses the list; Esc collapses it only when focus is inside the list. Neither calls `preventDefault` and Esc does not dismiss a toast. The toast `li` is `tabindex=0`, so Tab reaches the Undo button, which Enter or Space activates natively. Default lifetime is 4000 ms. Toasts are lost on a full page load, so an Undo offered on Home disappears if the user opens Study; Study's own `u` and ⌘Z still undo through the Collection's undo stack.

**Conflicts.** With focus on a toast's Undo button, Space or Enter reaches Study's window handler, which reveals or grades the card and calls `preventDefault()`, which cancels the button's activation. Alt+T and Esc are harmless to the app handlers (Study ignores Alt+T; Esc in the toast list still leaves Study, acceptable). One cosmetic gap: `sonner.svelte` carries a `cn-toast` class that neither `src/app.css` nor `shadcn-svelte/tailwind.css` defines (a `grep` finds none), so toast corners and padding are svelte-sonner defaults, not the preset's.

**Recommendation.** Leave Sonner as is; guard Study against `[data-sonner-toaster]`; if the Klaus look wants toast radius or padding from the preset, define `cn-toast` in `src/app.css` or pass `toastOptions.classes`.

## Kbd

`add kbd` installs `kbd/kbd.svelte` and `kbd-group.svelte`, nothing else (no dependencies, no registry dependencies). Both render a native `<kbd>`; there is no keyboard handling at all, and `Kbd` has `pointer-events-none select-none` so it never takes focus or clicks. It has a tooltip variant (`in-data-[slot=tooltip-content]`, needs `tooltip`, which `add sidebar` installs) and a `data-icon="inline-end"` placement inside `Button`. Usage: `<Kbd.Group><Kbd.Root>⌘</Kbd.Root><Kbd.Root>K</Kbd.Root></Kbd.Group>`.

Two things the app must supply: (a) the modifier glyph per platform: the app's handlers accept `ctrlKey || metaKey` everywhere, so display `⌘` on macOS and `Ctrl` elsewhere (one small helper from `navigator.platform` or the user agent); (b) a font: Fontsource's Inter, as imported in `app.css`, covers only the Latin, Latin-ext, Cyrillic, Greek and Vietnamese ranges in its `unicode-range` blocks, and ⌘ (U+2318), ⌥ and ⇧ are in none, so they fall back to the system font (fine in the macOS webview; varies elsewhere). In the palette, `Command.Shortcut` is a plain styled `<span>`; put `Kbd.Group` inside it where the design system's kbd style is wanted.

## The guard for Study and Browser

The bits-ui Escape layer (Dialog, AlertDialog, and everything built on `PopperLayer`: DropdownMenu, ContextMenu, Menu, Popover, Select, Tooltip, LinkPreview, plus NavigationMenu; a Sheet is a Dialog) listens on `document`, which runs before our `window` listeners, and calls `preventDefault()` on Escape. So `e.defaultPrevented` in a window handler means "an overlay just closed on this key". Add `src/lib/keys.ts`:

```ts
/** True when a window-level shortcut should stand down because another layer owns this key. */
export function keyIsTaken(e: KeyboardEvent): boolean {
  if (e.defaultPrevented || e.isComposing) return true;
  const t = e.target;
  return t instanceof Element && !!t.closest(
    'input, textarea, select, [contenteditable]:not([contenteditable="false"]), ' +
    '[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"], [data-sonner-toaster]',
  );
}
```

- **Study** (`review/+page.svelte`): `const onKeydown = (e) => !keyIsTaken(e) && onKey(e.key, e.ctrlKey || e.metaKey) && e.preventDefault();`. Effects: Esc closes the palette, a menu or a sheet without leaving Study (the Dialog already took it); typing in the palette input, or Enter on a toast's Undo, never reveals, grades or undoes.
- **Browser** (`browse/+page.svelte`): in the Esc branch use `!event.defaultPrevented` in place of (or alongside) the `querySelector`. Leave the ⌘⇧P branch alone. Its table arrows need no guard.
- **Space on a focused button.** Study today calls `preventDefault()` on Space and Enter on keydown so a focused "Show Answer" button activates once; Enter is reliable (its click comes from the keydown default action), Space is not guaranteed: browsers differ on whether cancelling keydown stops the click fired on keyup. This was not tested in the Tauri macOS webview (WKWebView). Related existing quirk: Enter on the focused "Decks" link reveals the card instead of following the link; if that matters, add `a[href]` to the guard for Enter only.
- **Future single-letter keys** (A, B, S, Z from the design system): bail on `keyIsTaken(e)` and on `e.metaKey || e.ctrlKey || e.altKey`, which also keeps clear of ⌘B (Sidebar) and Alt+T (Sonner).

## Not verified

- Nothing was run in a browser or in the Tauri webview; all key behaviour above is from reading the installed source and the registry output. The first implementation issue should test: Space on a focused button with `preventDefault()` in WKWebView; that the `sidebar_state` cookie survives a restart in the Tauri webview (reasoned from host-scoped cookies, not observed); that the palette input takes focus on open.
- The claim that `mode-watcher` is inert without `ModeWatcher` and with an explicit `theme` rests on reading its source and Svelte's spread semantics, not on running it.
- Browser-reserved shortcuts for the web build (⌘/Ctrl+N, T, W cannot be overridden by a page in Chrome-family browsers; Ctrl+K and Ctrl+B may be claimed by Firefox but can be `preventDefault`ed) are from general knowledge, not a primary source read here. The design system's ⌘N may need an alternative on the web.
- The CLI resolves `@latest` registry items at install time; the files read here were fetched on 2026-10-02 and may differ slightly.
- The docs markdown for Command and Kbd dropped the symbol glyphs (⌘ and so on) in the pages fetched; behaviour was taken from source, not from those examples.
