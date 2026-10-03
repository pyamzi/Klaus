<script lang="ts">
  // The review screen: what Anki's Qt reviewer (aqt/reviewer.py) and its bottom bar
  // do. Cards render in a sandboxed frame (static/card.html) running Anki's reviewer
  // JS; this page owns the queue, grading and undo.
  import { answerCard, describeNextStates, getQueuedCards, setCurrentDeck, undo } from "@generated/backend";
  import { CardAnswer_Rating, type QueuedCards_QueuedCard } from "@generated/anki/scheduler_pb";
  import type { RenderCardResponse } from "@generated/klaus_pb";
  import { onMount } from "svelte";
  import { toast } from "svelte-sonner";
  import { cardBodyClass, cardFrameSrc, night, openCardLink, postToCard, renderCard as render } from "$lib/card";
  import { IconArrowLeft as ArrowLeftIcon } from "@tabler/icons-svelte";
  import { Button } from "$lib/components/ui/button";

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
  // A failed transition shows a toast, and later ones still run.
  let last: Promise<void> = Promise.resolve();
  let pending = 0;
  let frameReady: Promise<void>;
  let pendingTyped: ((typed: string | null) => void) | undefined;
  let destroyed = false;

  function bodyClass(card: QueuedCards_QueuedCard): string {
    return cardBodyClass(card.card?.templateIdx ?? 0);
  }

  function exclusive(fn: () => Promise<void>): Promise<void> {
    pending++;
    const run = last
      .then(fn)
      .catch((err: unknown) => {
        toast.error("Review failed", { description: String(err) });
      })
      .finally(() => pending--);
    last = run;
    return run;
  }

  function post(msg: object) {
    postToCard(frame, msg);
  }

  // Call only inside exclusive().
  async function next() {
    const queued = await getQueuedCards({ fetchLimit: 1, intradayLearningOnly: false }, { alertOnError: false });
    // Left via client-side navigation (Decks) while this was in flight.
    if (destroyed) return;
    const card = queued.cards[0];
    if (!card) {
      current = undefined;
      location.href = `/congrats${night ? "#night" : ""}`;
      return;
    }
    const nextLabels = (await describeNextStates(card.states!, { alertOnError: false })).vals;
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
      // Card JS that throws or overrides getTypedAnswer never replies: carry on without.
      const typed = await new Promise<string | null>((resolve) => {
        pendingTyped = resolve;
        setTimeout(() => resolve(null), 1000);
      });
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
      await answerCard(
        {
          cardId: card.card!.id,
          currentState: states.current,
          newState: [states.again, states.hard, states.good, states.easy][ease - 1],
          rating: ratings[ease - 1],
          answeredAtMillis: BigInt(Date.now()),
          millisecondsTaken: Date.now() - shownAt,
        },
        { alertOnError: false },
      );
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
      const { cmd, key, typedAnswer, openLink } = event.data;
      if (typeof cmd === "string") onCommand(cmd);
      if (openLink !== undefined) openCardLink(openLink);
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
      await setCurrentDeck({ did: deck }, { alertOnError: false });
      await next();
    });
    return () => {
      destroyed = true;
      removeEventListener("message", onMessage);
      removeEventListener("keydown", onKeydown);
    };
  });
</script>

<div class="flex h-screen flex-col">
  <iframe bind:this={frame} title="Card" src={cardFrameSrc} sandbox="allow-scripts" class="w-full flex-1 border-0"
  ></iframe>
  <footer class="grid grid-cols-[1fr_auto_1fr] items-center gap-4 border-t px-4 py-2">
    <Button href="/" variant="ghost" size="sm" class="justify-self-start">
      <ArrowLeftIcon data-icon="inline-start" />
      Decks
    </Button>
    <div class="flex gap-2">
      {#if side === "question"}
        <Button class="min-w-32" onclick={reveal} disabled={!current}>Show Answer</Button>
      {:else}
        {#each ratingNames as name, i (name)}
          <Button variant="outline" class="h-auto min-w-24 flex-col gap-0 py-1" onclick={() => grade(i + 1)}>
            <span class="text-xs text-muted-foreground">{labels[i] ?? ""}</span>
            {name}
          </Button>
        {/each}
      {/if}
    </div>
    <div class="flex gap-3 justify-self-end tabular-nums" aria-label="New, learning, due">
      {#each counts as count, i (i)}
        <span
          class={["text-count-new", "text-count-learn", "text-count-review"][i]}
          class:underline={current?.queue === i}>{count}</span
        >
      {/each}
    </div>
  </footer>
</div>
