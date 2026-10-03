<script lang="ts">
	import { fly, fade } from 'svelte/transition';
	import { Button } from '$lib/components/ui/button';

	// A tiny review session, graded the way Klaus's reviewer is: Space or Enter shows
	// the answer, 1–4 grade it. Again and Hard bring the card back later in the
	// session, as a learning card would.
	type Card = { q: string; a: string; intervals: [string, string, string, string] };
	const deck: Card[] = [
		{
			q: 'What is Klaus Note?',
			a: 'A study app built on Anki’s own engine: your cards and their scheduling (FSRS included), with the lecture PDFs and notes they came from kept beside them.',
			intervals: ['<1m', '<6m', '<10m', '4d']
		},
		{
			q: 'Do I have to give up Anki?',
			a: 'No. Klaus Note uses the same Collection and is being built to sync through AnkiWeb, so AnkiMobile and AnkiDroid keep working. Or stay in Anki: the Klaus Addon brings the lecture library there.',
			intervals: ['<1m', '<6m', '<10m', '4d']
		},
		{
			q: 'Where do my PDFs and notes live?',
			a: 'In a folder you choose, as ordinary PDF and Markdown files. Highlights and lecture transcripts are stored inside the PDF, so other apps can still open everything.',
			intervals: ['<1m', '<6m', '<10m', '4d']
		},
		{
			q: 'What does it cost?',
			a: 'The app is free and open source (AGPL-3.0). A Klaus Note Account, planned for later, will pay for what klaus.so hosts, such as syncing your PDFs and notes.',
			intervals: ['<1m', '<6m', '<10m', '4d']
		}
	];
	const grades = ['Again', 'Hard', 'Good', 'Easy'];

	let queue = $state(deck.map((card, i) => ({ ...card, id: i, learning: false })));
	let seen = $state(0);
	let revealed = $state(false);
	const current = $derived(queue[0]);
	const counts = $derived({
		new: queue.filter((c) => !c.learning).length,
		learn: queue.filter((c) => c.learning).length
	});

	const reduced =
		typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
	const motion = (ms: number) => (reduced ? 0 : ms);

	let root: HTMLElement | undefined = $state();
	// The pressed button is replaced (Show answer → grades → next card), which would
	// drop focus to the page and stop the keys working; keep it in the card.
	function keepFocus() {
		root?.focus({ preventScroll: true });
	}

	function reveal() {
		if (!current) return;
		revealed = true;
		keepFocus();
	}

	function grade(ease: number) {
		if (!current || !revealed) return;
		const [card, ...rest] = queue;
		queue = ease <= 2 ? [...rest, { ...card, learning: true, id: card.id + deck.length * ++seen }] : rest;
		revealed = false;
		keepFocus();
	}

	function restart() {
		queue = deck.map((card, i) => ({ ...card, id: i, learning: false }));
		revealed = false;
		keepFocus();
	}

	function onkeydown(e: KeyboardEvent) {
		if (e.metaKey || e.ctrlKey || e.altKey) return;
		if ((e.key === ' ' || e.key === 'Enter') && !revealed) {
			e.preventDefault();
			reveal();
		} else if ((e.key === ' ' || e.key === 'Enter') && revealed) {
			e.preventDefault();
			grade(3);
		} else if (['1', '2', '3', '4'].includes(e.key)) {
			e.preventDefault();
			grade(Number(e.key));
		}
	}
</script>

<!-- Keys work while focus is inside the card, so Space still scrolls the page elsewhere. -->
<!-- svelte-ignore a11y_no_noninteractive_element_interactions (key events bubble up from its buttons) -->
<section
	class="review"
	aria-label="Try a review: questions about Klaus Note"
	tabindex="-1"
	bind:this={root}
	{onkeydown}
>
	<div class="index-card" aria-live="polite">
		{#if current}
			{#key current.id}
				<div class="face" in:fly={{ y: 12, duration: motion(220) }}>
					<p class="question">{current.q}</p>
					{#if revealed}
						<div transition:fade={{ duration: motion(160) }}>
							<p class="answer">{current.a}</p>
						</div>
					{/if}
				</div>
			{/key}
		{:else}
			<div class="face" in:fade={{ duration: motion(200) }}>
				<p class="question">Congratulations!</p>
				<p class="answer">You have finished this deck for now.</p>
			</div>
		{/if}
	</div>

	<div class="bar">
		{#if !current}
			<Button variant="outline" onclick={restart}>Study again</Button>
		{:else if !revealed}
			<Button class="show" onclick={reveal}>
				Show answer
			</Button>
		{:else}
			<div class="grades" role="group" aria-label="Grade your answer">
				{#each grades as name, i (name)}
					<Button variant="outline" class="grade" onclick={() => grade(i + 1)}>
						<span class="interval">{current.intervals[i]}</span>
						<span>{name}</span>
					</Button>
				{/each}
			</div>
		{/if}
		<p class="counts" aria-label="{counts.new} new, {counts.learn} learning">
			<span class="text-count-new" class:current={current && !current.learning}>{counts.new}</span>
			<span class="text-count-learn" class:current={current?.learning}>{counts.learn}</span>
			<span class="text-count-due">0</span>
		</p>
	</div>
</section>

<style>
	.review {
		outline: none;
		display: grid;
		gap: 1rem;
	}
	/* A ruled index card: blue lines, a red margin line under the heading band. */
	.index-card {
		position: relative;
		min-height: 19rem;
		border-radius: 0.375rem;
		background-color: var(--card);
		background-image: repeating-linear-gradient(
				to bottom,
				transparent 0,
				transparent calc(2rem - 1px),
				var(--rule) calc(2rem - 1px),
				var(--rule) 2rem
			);
		/* Text sits on a 2rem line grid from the 1rem top padding, a blue rule under
		   every line; the question's own red line covers the rule beneath it. */
		background-position: 0 1rem;
		background-repeat: no-repeat;
		box-shadow:
			0 1px 0 color-mix(in oklab, var(--ink) 8%, transparent),
			0 18px 40px -24px color-mix(in oklab, var(--klaus-ink) 45%, transparent);
		border: 1px solid var(--border);
		padding: 1rem 1.5rem 1.5rem;
	}
	.question {
		font-family: var(--font-display);
		font-size: clamp(1.5rem, 1.2rem + 1vw, 1.9rem);
		line-height: 2rem;
		margin: 0 -1.5rem 2rem;
		padding-inline: 1.5rem;
		background: linear-gradient(var(--margin), var(--margin)) bottom / 100% 2px no-repeat;
	}
	.answer {
		font-size: 1.05rem;
		line-height: 2rem;
		margin: 0;
	}
	.bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		flex-wrap: wrap;
	}
	.grades {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 0.4rem;
		flex: 1 1 18rem;
	}
	.grades :global(.grade) {
		height: auto;
		flex-direction: column;
		gap: 0.1rem;
		padding: 0.4rem 0.25rem;
	}
	.interval {
		font-size: 0.75rem;
		font-variant-numeric: tabular-nums;
		color: var(--muted-foreground);
	}
	.counts {
		display: flex;
		gap: 0.6rem;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		margin: 0 0 0 auto;
	}
	.current {
		text-decoration: underline;
		text-underline-offset: 0.2em;
	}
</style>
