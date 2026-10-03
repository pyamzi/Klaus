<script lang="ts">
	import { onMount } from 'svelte';
	import { site } from '$lib/site';
	import { loadGoogleAnalytics, setConsent, storedConsent } from '$lib/analytics';
	import { Button } from '$lib/components/ui/button';

	// Google Analytics sets cookies, so it waits for a yes. Plausible needs no consent
	// and isn't covered here.
	let open = $state(false);

	onMount(() => {
		if (!site.gaId) return;
		const choice = storedConsent();
		if (choice === 'granted') loadGoogleAnalytics();
		else if (choice === null) open = true;
	});

	function choose(choice: 'granted' | 'denied') {
		setConsent(choice);
		open = false;
	}
</script>

{#if open}
	<div class="consent" role="region" aria-label="Analytics cookies">
		<p>
			Can we use Google Analytics to see which parts of this page help people? It sets
			cookies. <a href="/privacy">Privacy</a>
		</p>
		<div class="buttons">
			<Button variant="outline" size="sm" onclick={() => choose('denied')}>Decline</Button>
			<Button size="sm" onclick={() => choose('granted')}>Allow analytics</Button>
		</div>
	</div>
{/if}

<style>
	.consent {
		position: fixed;
		inset: auto 1rem 1rem auto;
		max-width: 24rem;
		z-index: 20;
		display: grid;
		gap: 0.75rem;
		padding: 1rem;
		border-radius: 0.75rem;
		background: var(--card);
		border: 1px solid var(--border);
		box-shadow: 0 12px 32px -16px color-mix(in oklab, var(--ink) 40%, transparent);
		font-size: 0.9rem;
	}
	p {
		margin: 0;
		line-height: 1.5;
	}
	a {
		color: inherit;
	}
	.buttons {
		display: flex;
		gap: 0.5rem;
		justify-content: flex-end;
	}
	@media (max-width: 30rem) {
		.consent {
			inset: auto 0.75rem 0.75rem 0.75rem;
			max-width: none;
		}
	}
</style>
