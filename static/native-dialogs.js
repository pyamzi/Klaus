// Loaded first on every page Klaus serves (its own and Anki's).
(() => {
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
})();
