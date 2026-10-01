// What Klaus provides on Anki pages in place of Anki's Qt window, injected
// before any page script runs. Anki's webview injects a QWebChannel
// `pycmd`/`bridgeCommand`; Klaus defines it here. Requests that need the host's
// data or native UI go to /_anki/<method> instead (the bridge and Klaus's shell
// answer those).
(() => {
    const page = location.pathname.split("/")[1];
    const handlers = {
        // aqt/editor.py NewEditor._set_ready -> load_note, in add mode.
        editorReady() {
            const mode = new URLSearchParams(location.search).get("mode") ?? "add";
            if (mode !== "add") return;
            globalThis.require("anki/ui").loaded.then(() =>
                globalThis.loadNote({
                    nid: null,
                    notetypeId: null,
                    focusTo: 0,
                    originalNoteId: null,
                    reviewerCardId: null,
                    deckId: null,
                    initial: true,
                })
            );
        },
        // Context-menu actions. Cut/copy work from script; paste doesn't (browsers
        // block it), so, like Anki's Qt host, Klaus's shell sends the native paste
        // action, which fires a real paste event with clipboard data.
        cut: () => document.execCommand("cut"),
        copy: () => document.execCommand("copy"),
        paste: () =>
            fetch("/_anki/klausPaste", { method: "POST", headers: { "Content-Type": "application/binary" } }),
    };
    // Everything else (focus:N, blur:N, key:N, saved, editorState:…) is a
    // notification Klaus doesn't need yet.
    globalThis.bridgeCommand = globalThis.pycmd = (cmd, callback) => {
        handlers[cmd]?.();
        callback?.(null);
        return false;
    };

    // Tauri's macOS webview has no alert()/confirm() UI: they return at once
    // (confirm() is always false). Anki pages rely on both (e.g. removing a deck
    // options preset, discarding changes, showing save errors), so show them through
    // the shell's native dialogs. A synchronous request blocks only this page, as a
    // native alert would; the shell's dialog runs in the app process.
    const field1 = (text) => {
        const bytes = new TextEncoder().encode(String(text ?? ""));
        const len = [];
        for (let n = bytes.length; ; n >>>= 7) {
            if (n < 0x80) { len.push(n); break; }
            len.push((n & 0x7f) | 0x80);
        }
        return new Uint8Array([0x0a, ...len, ...bytes]);
    };
    const hostSync = (method, body) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", `/_anki/${method}`, false);
        xhr.setRequestHeader("Content-Type", "application/binary");
        xhr.send(body);
        return xhr.responseText;
    };
    // AskUserRequest/ShowMessageBoxRequest.text is field 1; the reply generic.Bool
    // is 08 01 for true, and empty (204) for false.
    globalThis.alert = (text) => void hostSync("showMessageBox", field1(text));
    globalThis.confirm = (text) => hostSync("askUser", field1(text)).charCodeAt(1) === 1;

    if (location.hash === "#night") {
        document.documentElement.classList.add("night-mode");
    }

    // Anki pages are closed with their Qt window; Klaus has none, so offer a way
    // back (e.g. from the import log, which has no Close of its own). Esc does the
    // same, as it closes Anki's dialogs. The editor has its own Close.
    if (page === "editor") return;
    // Deck options asks before discarding unsaved changes, as Anki does when its
    // window is closed; the page then calls deckOptionsRequireClose.
    const leave = (e) => {
        const pending = globalThis.anki?.deckOptionsPendingChanges;
        if (page !== "deck-options" || !pending) return void (location.href = "/");
        e?.preventDefault();
        pending();
    };
    addEventListener("keydown", (e) => e.key === "Escape" && leave(e));
    const link = document.createElement("a");
    link.addEventListener("click", leave);
    link.href = "/";
    link.className = "klaus-back";
    link.textContent = "← Decks";
    // SvelteKit replaces <body>'s children when the page mounts; put it back.
    addEventListener("DOMContentLoaded", () => {
        const ensure = () => link.isConnected || document.body.append(link);
        ensure();
        new MutationObserver(ensure).observe(document.body, { childList: true });
    });
})();
