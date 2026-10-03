// The sandboxed card frame (static/card.html) shared by review and the browser's
// preview: Klaus renders a card's HTML through the bridge and posts it in.
import { RenderCardRequest, RenderCardResponse } from "@generated/klaus_pb";
import { Empty, String as PbString } from "@generated/anki/generic_pb";
import { postProto } from "@generated/post";

export const night = matchMedia("(prefers-color-scheme: dark)").matches;
// aqt/theme.py body_class
const platform = /Win/.test(navigator.userAgent) ? "isWin" : /Mac/.test(navigator.userAgent) ? "isMac" : "isLin";

export const cardFrameSrc = `/card.html${night ? "#night" : ""}`;

export function renderCard(cardId: bigint, typedAnswer?: string): Promise<RenderCardResponse> {
  return postProto("klausRenderCard", new RenderCardRequest({ cardId, typedAnswer }), RenderCardResponse);
}

export function cardBodyClass(templateIdx: number): string {
  return `card card${templateIdx + 1} ${platform} fancy${night ? " nightMode night_mode" : ""}`;
}

/** Card links open in the system browser, as in Anki's reviewer (the frame posts them). */
export function openCardLink(url: unknown): void {
  if (typeof url !== "string" || !/^https?:/i.test(url)) return;
  postProto("openLink", new PbString({ val: url }), Empty, { alertOnError: false }).catch(() => {});
}

export function postToCard(frame: HTMLIFrameElement | undefined, msg: object): void {
  // The frame has an opaque origin, so "*" is the only target that reaches it.
  frame?.contentWindow?.postMessage({ klaus: true, ...msg }, "*");
}
