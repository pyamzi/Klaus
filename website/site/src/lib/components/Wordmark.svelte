<script lang="ts">
	import KlausMark from './KlausMark.svelte';

	// The two products' lockups: the hand-drawn k (no tile) and the name in Excalifont.
	// Klaus, the app, wears the k in Klaus blue; Klaus Addon, the Anki add-on, wears it in
	// ink and is tagged "for Anki", so the two never read as the same thing.
	let {
		product = 'klaus',
		size = 'md'
	}: { product?: 'klaus' | 'addon'; size?: 'sm' | 'md' | 'lg' } = $props();
</script>

<span class="lockup {product} {size}">
	<span class="mark" aria-hidden="true"><KlausMark class="k" /></span>
	<span class="name">{product === 'klaus' ? 'Klaus Note' : 'Klaus Addon'}</span>
	{#if product === 'addon'}
		<!-- Anki's logo (docs-site/media/favicon.svg), unmodified, under its license's alternative terms: it refers to
		     Anki and links to apps.ankiweb.net (vendor/anki/LICENSE). -->
		<a class="for-anki" href="https://apps.ankiweb.net" title="Anki, at apps.ankiweb.net">
			<img src="/anki-logo.svg" alt="" width="33" height="33" />
			<span>for Anki</span>
		</a>
	{/if}
</span>

<style>
	.lockup {
		--size: 2rem;
		--fs: calc(var(--size) * 0.85);
		display: inline-flex;
		/* The mark's box has no text, so its baseline is its bottom edge: baseline
		   alignment puts the foot of the k on the wordmark's baseline. */
		align-items: baseline;
		gap: calc(var(--fs) * 0.45);
		line-height: 1;
	}
	.sm {
		--size: 1.5rem;
	}
	.lg {
		--size: 2.5rem;
	}
	.name {
		font-family: var(--font-hand);
		font-size: var(--fs);
		color: var(--foreground);
	}
	/* The k matches the wordmark's "l" exactly: Excalifont's l runs from 0.02em below
	   the baseline to 0.825em above it (0.845em tall), so the k is that tall and its
	   foot drops the same 0.02em. Width keeps the k's 935:850 proportions. */
	.mark {
		display: block;
		position: relative;
		top: calc(var(--fs) * 0.02);
		height: calc(var(--fs) * 0.845);
		width: calc(var(--fs) * 0.845 * 935 / 850);
	}
	.mark :global(.k) {
		width: 100%;
		height: 100%;
	}
	.klaus .mark {
		color: var(--klaus);
	}
	.addon .mark {
		color: var(--foreground);
	}
	/* Klaus Addon's "for Anki": Anki's icon, the same height as the wordmark's "l" (like
	   the k), with the words underneath, right-aligned to the icon. The words sit
	   outside the flow so the icon lines up with the wordmark top and bottom. */
	.for-anki {
		position: relative;
		top: calc(var(--fs) * 0.02);
		display: block;
		margin-left: calc(var(--fs) * 0.15);
		margin-bottom: 0.9rem;
		font-family: var(--font-sans);
		font-size: 0.7rem;
		font-weight: 700;
		line-height: 1;
		color: var(--muted-foreground);
		text-decoration: none;
		white-space: nowrap;
	}
	.for-anki img {
		display: block;
		height: calc(var(--fs) * 0.845);
		width: auto;
	}
	.for-anki span {
		position: absolute;
		top: calc(100% + 0.25rem);
		right: 0;
	}
	.for-anki:hover {
		color: var(--foreground);
	}
</style>
