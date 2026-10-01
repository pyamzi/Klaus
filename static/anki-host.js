// What Klaus provides on Anki pages in place of Anki's Qt window, injected
// before any page script runs.
(() => {
    if (location.hash === "#night") {
        document.documentElement.classList.add("night-mode");
    }
    // Anki pages are closed with their Qt window; Klaus has none, so offer a way
    // back (e.g. from the import log, which has no Close of its own). Esc does the
    // same, as it closes Anki's dialogs. The editor has its own Close.
    const page = location.pathname.split("/")[1];
    if (page === "editor") return;
    const back = () => (location.href = "/");
    addEventListener("keydown", (e) => e.key === "Escape" && back());
    const link = document.createElement("a");
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
