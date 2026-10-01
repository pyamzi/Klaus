// Stands in for Anki's Qt reviewer inside the sandboxed card frame (static/card.html).
// The frame can't call /_anki; it only exchanges messages with Klaus's review screen.
(() => {
    const toParent = (msg) => parent.postMessage({ klaus: true, ...msg }, "*");

    // Anki's reviewer JS (and card JS) talks to its host with pycmd/bridgeCommand.
    globalThis.bridgeCommand = globalThis.pycmd = (cmd) => {
        // Qt-only housekeeping; nothing to do here.
        if (cmd === "updateToolbar" || cmd === "repaintNeeded") return;
        toParent({ cmd });
    };

    if (location.hash === "#night") {
        document.documentElement.classList.add("night-mode");
        document.documentElement.dataset.bsTheme = "dark";
    }

    addEventListener("message", (event) => {
        if (event.source !== parent || !event.data?.klaus) return;
        const { show, html, bodyClass, ask } = event.data;
        if (show === "question") globalThis._showQuestion(html, "", bodyClass);
        if (show === "answer") globalThis._showAnswer(html, bodyClass);
        if (ask === "typedAnswer") toParent({ typedAnswer: globalThis.getTypedAnswer() });
    });

    // Anki handles reviewer keys in Qt, globally; with focus inside this frame the
    // review screen wouldn't see them, so forward the reveal/grade keys (the same
    // power card JS has via pycmd("ans"/"easeN")). Undo and leaving are not
    // forwarded: card JS mustn't trigger them. Typing in the type-in box stays local.
    const forwarded = [" ", "Enter", "1", "2", "3", "4"];
    addEventListener("keydown", (e) => {
        if (e.target?.id === "typeans" || e.ctrlKey || e.metaKey || !forwarded.includes(e.key)) return;
        toParent({ key: e.key });
    });
})();
