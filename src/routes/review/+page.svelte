<script lang="ts">
  // The review screen: what Anki's Qt reviewer (aqt/reviewer.py) and its bottom bar
  // do. Cards render in a sandboxed frame (static/card.html) running Anki's reviewer
  // JS; this page owns the queue, grading and undo.
  import { answerCard, describeNextStates, getQueuedCards, setCurrentDeck, undo } from "@generated/backend";
  import { CardAnswer_Rating, type QueuedCards_QueuedCard } from "@generated/anki/scheduler_pb";
  import { RenderCardRequest, RenderCardResponse } from "@generated/klaus_pb";
  import { postProto } from "@generated/post";
  import { onMount } from "svelte";

  const night = matchMedia("(prefers-color-scheme: dark)").matches;
  const ratings = [CardAnswer_Rating.AGAIN, CardAnswer_Rating.HARD, CardAnswer_Rating.GOOD, CardAnswer_Rating.EASY];
  const ratingNames = ["Again", "Hard", "Good", "Easy"];

  let frame: HTMLIFrameElement;
  let current: QueuedCards_QueuedCard | undefined = $state();
  let counts = $state([0, 0, 0]);
  let labels: string[] = $state([]);
  let side: "question" | "answer" = $state("question");
  let rendered: RenderCardResponse | undefined;
  let shownAt = 0;
  let busy = false;
  let frameReady: Promise<void>;
  let pendingTyped: ((typed: string | null) => void) | undefined;

  function render(cardId: bigint, typedAnswer?: string) {
    return postProto("klausRenderCard", new RenderCardRequest({ cardId, typedAnswer }), RenderCardResponse);
  }

  function bodyClass(card: QueuedCards_QueuedCard): string {
    const ord = (card.card?.templateIdx ?? 0) + 1;
    return `card card${ord} isMac fancy${night ? " nightMode night_mode" : ""}`;
  }

  function post(msg: object) {
    // The frame has an opaque origin, so "*" is the only target that reaches it.
    frame.contentWindow?.postMessage({ klaus: true, ...msg }, "*");
  }

  async function next() {
    const queued = await getQueuedCards({ fetchLimit: 1, intradayLearningOnly: false });
    current = queued.cards[0];
    if (!current) {
      location.href = `/congrats${night ? "#night" : ""}`;
      return;
    }
    counts = [queued.newCount, queued.learningCount, queued.reviewCount];
    labels = (await describeNextStates(current.states!)).vals;
    rendered = await render(current.card!.id);
    side = "question";
    await frameReady;
    post({ show: "question", html: rendered.question, bodyClass: bodyClass(current) });
    shownAt = Date.now();
  }

  async function reveal() {
    if (!current || side !== "question") return;
    post({ ask: "typedAnswer" });
    const typed = await new Promise<string | null>((resolve) => (pendingTyped = resolve));
    const answer = typed === null ? rendered!.answer : (await render(current.card!.id, typed)).answer;
    side = "answer";
    post({ show: "answer", html: answer, bodyClass: bodyClass(current) });
  }

  async function grade(ease: number) {
    if (!current || side !== "answer" || busy) return;
    busy = true;
    const states = current.states!;
    const newState = [states.again, states.hard, states.good, states.easy][ease - 1];
    try {
      await answerCard({
        cardId: current.card!.id,
        currentState: states.current,
        newState,
        rating: ratings[ease - 1],
        answeredAtMillis: BigInt(Date.now()),
        millisecondsTaken: Date.now() - shownAt,
      });
      await next();
    } finally {
      busy = false;
    }
  }

  async function undoLast() {
    // Nothing to undo is not an error worth showing (Anki ignores UndoEmpty too).
    await undo({}, { alertOnError: false }).catch(() => {});
    await next();
  }

  // Anki's reviewer shortcuts (aqt/reviewer.py _shortcutKeys), subset for #7.
  function onKey(key: string, ctrl: boolean) {
    if (key === "Escape") location.href = "/";
    else if (ctrl && key === "z") undoLast();
    else if (ctrl) return;
    else if (key === " " || key === "Enter") side === "question" ? reveal() : grade(3);
    else if (["1", "2", "3", "4"].includes(key)) grade(Number(key));
    else if (key === "u") undoLast();
  }

  // Commands the card frame may send (Anki's reviewer _linkHandler); anything else,
  // e.g. from card JS, is ignored.
  function onCommand(cmd: string) {
    if (cmd === "ans") reveal();
    else if (/^ease[1-4]$/.test(cmd)) grade(Number(cmd.slice(4)));
    // play:q:N / play:a:N: audio playback is #13.
  }

  onMount(() => {
    frameReady = new Promise((resolve) => frame.addEventListener("load", () => resolve(), { once: true }));
    const onMessage = (event: MessageEvent) => {
      if (event.source !== frame.contentWindow || !event.data?.klaus) return;
      const { cmd, key, ctrl, typedAnswer } = event.data;
      if (typeof cmd === "string") onCommand(cmd);
      if (typeof key === "string") onKey(key, !!ctrl);
      if ("typedAnswer" in event.data) pendingTyped?.(typeof typedAnswer === "string" ? typedAnswer : null);
    };
    const onKeydown = (e: KeyboardEvent) => onKey(e.key, e.ctrlKey || e.metaKey);
    addEventListener("message", onMessage);
    addEventListener("keydown", onKeydown);
    const deck = BigInt(new URLSearchParams(location.search).get("deck") ?? "1");
    setCurrentDeck({ did: deck }).then(next);
    return () => {
      removeEventListener("message", onMessage);
      removeEventListener("keydown", onKeydown);
    };
  });
</script>

<div class="reviewer">
  <iframe
    bind:this={frame}
    title="Card"
    src={`/card.html${night ? "#night" : ""}`}
    sandbox="allow-scripts"
  ></iframe>
  <footer>
    <a href="/" class="back">← Decks</a>
    <div class="actions">
      {#if side === "question"}
        <button class="show" onclick={reveal} disabled={!current}>Show Answer</button>
      {:else}
        {#each ratingNames as name, i (name)}
          <button onclick={() => grade(i + 1)}>
            <span class="interval">{labels[i] ?? ""}</span>
            {name}
          </button>
        {/each}
      {/if}
    </div>
    <div class="counts" aria-label="New, learning, due">
      {#each counts as count, i (i)}
        <span class:current={current?.queue === i} class={["new", "learn", "review"][i]}>{count}</span>
      {/each}
    </div>
  </footer>
</div>

<style>
  :global(body) {
    margin: 0;
    font-family: system-ui, sans-serif;
    color: CanvasText;
    background: Canvas;
    color-scheme: light dark;
  }
  .reviewer { display: flex; flex-direction: column; height: 100vh; }
  iframe { flex: 1; border: 0; width: 100%; }
  footer {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    gap: 1rem;
    padding: 0.6rem 1rem;
    border-top: 1px solid color-mix(in srgb, CanvasText 15%, transparent);
  }
  .back { color: inherit; justify-self: start; }
  .actions { display: flex; gap: 0.5rem; }
  .actions button { min-width: 5.5rem; padding: 0.35rem 0.8rem; }
  .interval { display: block; font-size: 0.75rem; opacity: 0.75; }
  .counts { justify-self: end; display: flex; gap: 0.6rem; font-variant-numeric: tabular-nums; }
  .current { text-decoration: underline; }
  /* ≥4.5:1 against the Canvas background in both schemes (see the deck list). */
  .new { color: light-dark(#1d4ed8, #93c5fd); }
  .learn { color: light-dark(#b91c1c, #fca5a5); }
  .review { color: light-dark(#15803d, #86efac); }
</style>
