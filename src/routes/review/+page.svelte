<script lang="ts">
  // The review screen: what Anki's Qt reviewer (aqt/reviewer.py) and its bottom bar
  // do. Cards render in a sandboxed frame (static/card.html) running Anki's reviewer
  // JS; this page owns the queue, grading and undo.
  import { answerCard, describeNextStates, getQueuedCards, setCurrentDeck, undo } from "@generated/backend";
  import { CardAnswer_Rating, type QueuedCards_QueuedCard } from "@generated/anki/scheduler_pb";
  import type { RenderCardResponse } from "@generated/klaus_pb";
  import { onMount } from "svelte";
  import { cardBodyClass, cardFrameSrc, night, postToCard, renderCard as render } from "$lib/card";

  const ratings = [CardAnswer_Rating.AGAIN, CardAnswer_Rating.HARD, CardAnswer_Rating.GOOD, CardAnswer_Rating.EASY];
  const ratingNames = ["Again", "Hard", "Good", "Easy"];

  let frame: HTMLIFrameElement;
  let current: QueuedCards_QueuedCard | undefined = $state();
  let counts = $state([0, 0, 0]);
  let labels: string[] = $state([]);
  let side: "question" | "answer" = $state("question");
  let rendered: RenderCardResponse | undefined;
  let shownAt = 0;
  // Card transitions run one at a time: reveal/grade are dropped while one is in
  // flight or queued (no double grades from key repeat), undo waits its turn.
  let last: Promise<void> = Promise.resolve();
  let pending = 0;
  let frameReady: Promise<void>;
  let pendingTyped: ((typed: string | null) => void) | undefined;

  function bodyClass(card: QueuedCards_QueuedCard): string {
    return cardBodyClass(card.card?.templateIdx ?? 0);
  }

  function exclusive(fn: () => Promise<void>): Promise<void> {
    pending++;
    const run = last.then(fn).finally(() => pending--);
    last = run.catch(() => {});
    return run;
  }

  function post(msg: object) {
    postToCard(frame, msg);
  }

  // Call only inside exclusive().
  async function next() {
    const queued = await getQueuedCards({ fetchLimit: 1, intradayLearningOnly: false });
    const card = queued.cards[0];
    if (!card) {
      current = undefined;
      location.href = `/congrats${night ? "#night" : ""}`;
      return;
    }
    const nextLabels = (await describeNextStates(card.states!)).vals;
    const nextRendered = await render(card.card!.id);
    await frameReady;
    [current, rendered, labels, side] = [card, nextRendered, nextLabels, "question"];
    counts = [queued.newCount, queued.learningCount, queued.reviewCount];
    // The answer goes along so the reviewer preloads its images and MathJax.
    post({ show: "question", html: rendered.question, answer: rendered.answer, bodyClass: bodyClass(card) });
    shownAt = Date.now();
  }

  function reveal() {
    if (pending || !current || side !== "question") return;
    exclusive(async () => {
      const card = current!;
      post({ ask: "typedAnswer" });
      const typed = await new Promise<string | null>((resolve) => (pendingTyped = resolve));
      pendingTyped = undefined;
      const answer = typed === null ? rendered!.answer : (await render(card.card!.id, typed)).answer;
      side = "answer";
      post({ show: "answer", html: answer, bodyClass: bodyClass(card) });
    });
  }

  function grade(ease: number) {
    if (pending || !current || side !== "answer") return;
    const card = current;
    const states = card.states!;
    exclusive(async () => {
      await answerCard({
        cardId: card.card!.id,
        currentState: states.current,
        newState: [states.again, states.hard, states.good, states.easy][ease - 1],
        rating: ratings[ease - 1],
        answeredAtMillis: BigInt(Date.now()),
        millisecondsTaken: Date.now() - shownAt,
      });
      await next();
    });
  }

  function undoLast() {
    exclusive(async () => {
      // Nothing to undo is not an error worth showing (Anki ignores UndoEmpty too).
      await undo({}, { alertOnError: false }).catch(() => {});
      await next();
    });
  }

  // Anki's reviewer shortcuts (aqt/reviewer.py _shortcutKeys), subset for #7.
  /** True if the key was a reviewer shortcut. */
  function onKey(key: string, ctrl: boolean): boolean {
    if (key === "Escape") location.href = "/";
    else if (ctrl && key === "z") undoLast();
    else if (ctrl) return false;
    else if (key === " " || key === "Enter") side === "question" ? reveal() : grade(3);
    else if (["1", "2", "3", "4"].includes(key)) grade(Number(key));
    else if (key === "u") undoLast();
    else return false;
    return true;
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
      const { cmd, key, typedAnswer } = event.data;
      if (typeof cmd === "string") onCommand(cmd);
      // Card JS can post these too, so only reveal/grade keys count from the frame.
      if (typeof key === "string" && [" ", "Enter", "1", "2", "3", "4"].includes(key)) onKey(key, false);
      if ("typedAnswer" in event.data) pendingTyped?.(typeof typedAnswer === "string" ? typedAnswer : null);
    };
    // A focused button would also activate on Space/Enter: handle the key once.
    const onKeydown = (e: KeyboardEvent) => onKey(e.key, e.ctrlKey || e.metaKey) && e.preventDefault();
    addEventListener("message", onMessage);
    addEventListener("keydown", onKeydown);
    const deck = BigInt(new URLSearchParams(location.search).get("deck") ?? "1");
    exclusive(async () => {
      await setCurrentDeck({ did: deck });
      await next();
    });
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
    src={cardFrameSrc}
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
