// The editor's only feedback channel: a transient toast, every message
// prefixed "Klaus: " (parity spec, "Voice"). Never a modal, never inline text.

const DISMISS_MS = 2200;

let host: HTMLDivElement | null = null;
let timer: number | undefined;

export function toast(message: string): void {
  if (!host) {
    host = document.createElement("div");
    host.className = "klaus-toast";
    document.body.appendChild(host);
  }
  host.textContent = `Klaus: ${message}`;
  // Re-trigger the transition even while a previous toast is still up.
  host.classList.add("visible");
  window.clearTimeout(timer);
  const current = host;
  timer = window.setTimeout(() => current.classList.remove("visible"), DISMISS_MS);
}
