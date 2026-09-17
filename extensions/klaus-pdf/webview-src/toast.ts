// The channel for transient feedback — an action's outcome — as a toast with
// every message prefixed "Klaus: " (parity spec, "Voice"). Never a modal,
// never inline text.
//
// Persistent state is NOT feedback and does not belong here: the notes
// sidebar's save status and "Notes unavailable: …", and the stage's
// "Opening …" / "Could not open …", describe a condition that stays on
// screen, and a 2.2s toast would lose it. Whether those should also adopt
// the Klaus voice is KB-018.

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
