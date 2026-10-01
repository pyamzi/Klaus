// Stands in for Anki's Qt host on Anki pages served by Klaus. Anki's webview
// injects a QWebChannel `pycmd`/`bridgeCommand`; Klaus defines it here, before any
// page script runs. Requests that need the host's data or native UI go to
// /_anki/<method> instead (the bridge and Klaus's shell answer those).
(() => {
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
        // Context-menu actions; Qt triggers the native page action.
        cut: () => document.execCommand("cut"),
        copy: () => document.execCommand("copy"),
        paste: () => document.execCommand("paste"),
    };
    // Everything else (focus:N, blur:N, key:N, saved, editorState:…) is a
    // notification Klaus doesn't need yet.
    globalThis.bridgeCommand = globalThis.pycmd = (cmd, callback) => {
        handlers[cmd]?.();
        callback?.(null);
        return false;
    };
    if (location.hash === "#night") {
        document.documentElement.classList.add("night-mode");
    }
})();
