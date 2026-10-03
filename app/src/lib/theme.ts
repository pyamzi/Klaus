/** `#night` for an Anki page opened now: Anki's pages learn dark mode from the URL. */
export function nightHash(): string {
  return matchMedia("(prefers-color-scheme: dark)").matches ? "#night" : "";
}
