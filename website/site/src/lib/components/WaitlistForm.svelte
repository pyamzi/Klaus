<script lang="ts">
	import { site } from '$lib/site';
	import { track } from '$lib/analytics';
	import { Button } from '$lib/components/ui/button';

	// `source` says which form on the page converted, for analytics.
	// hideLabel: the section's heading already says it (the label stays for screen readers).
	let { source, hideLabel = false }: { source: string; hideLabel?: boolean } = $props();

	let status: 'idle' | 'sending' | 'done' | 'error' = $state('idle');
	let email = $state('');
	let trap = $state(''); // a bot trap, never sent
	const id = $derived(`waitlist-email-${source}`);

	// Signs up through the Supabase join_waitlist() function (a repeat signup is a
	// silent success, so the list can't be probed).
	async function onsubmit(event: SubmitEvent) {
		event.preventDefault();
		if (trap) {
			status = 'done'; // a bot: pretend it worked, send nothing
			return;
		}
		status = 'sending';
		try {
			const res = await fetch(`${site.supabaseUrl}/rest/v1/rpc/join_waitlist`, {
				method: 'POST',
				headers: { apikey: site.supabaseKey, 'Content-Type': 'application/json' },
				body: JSON.stringify({ email: email.trim(), source })
			});
			if (!res.ok) throw new Error(String(res.status));
			status = 'done';
			track('Waitlist signup', { source });
		} catch {
			status = 'error';
		}
	}
</script>

{#if !site.supabaseUrl}
	<div class="waitlist">
		<Button href={site.discord} size="lg" onclick={() => track('Discord click', { source })}>
			Join the Discord for early access
		</Button>
		<p class="note">We post builds and progress there first.</p>
	</div>
{:else if status === 'done'}
	<p class="waitlist done" role="status">
		You’re on the list. We’ll email <strong>{email}</strong> when KlausNote is ready to install.
	</p>
{:else}
	<form class="waitlist" {onsubmit}>
		<label for={id} class:sr-only={hideLabel}>Get KlausNote first</label>
		<div class="row">
			<input
				{id}
				name="email"
				type="email"
				required
				autocomplete="email"
				placeholder="you@university.edu"
				bind:value={email}
				aria-describedby="{id}-note"
			/>
			<Button type="submit" size="lg" disabled={status === 'sending'}>
				{status === 'sending' ? 'Joining…' : 'Join the waitlist'}
			</Button>
		</div>
		<!-- Bots fill every field; people never see this one. -->
		<input class="trap" type="text" bind:value={trap} tabindex="-1" autocomplete="off" aria-hidden="true" />
		{#if status === 'error'}
			<p class="note error" role="alert">
				That didn’t go through. Check the address and try again, or
				<a href={site.discord}>join the Discord</a>.
			</p>
		{:else}
			<p class="note" id="{id}-note">
				Launch news only. Unsubscribe anytime.
				<a href="/privacy">Privacy</a>
			</p>
		{/if}
	</form>
{/if}

<style>
	.waitlist {
		display: grid;
		gap: 0.5rem;
		max-width: 30rem;
		justify-items: start;
	}
	label {
		font-weight: 700;
	}
	.row {
		display: flex;
		gap: 0.5rem;
		width: 100%;
		flex-wrap: wrap;
	}
	input[type='email'] {
		flex: 1 1 14rem;
		min-width: 0;
		height: 2.5rem;
		padding: 0 0.75rem;
		border-radius: 0.375rem;
		border: 1px solid var(--input);
		background: var(--card);
		color: inherit;
		font: inherit;
	}
	input[type='email']:focus-visible {
		outline: 2px solid var(--klaus);
		outline-offset: 1px;
	}
	.trap {
		position: absolute;
		left: -9999px;
		width: 1px;
		height: 1px;
		opacity: 0;
	}
	.note {
		font-size: 0.875rem;
		color: var(--muted-foreground);
		margin: 0;
	}
	.note a {
		color: inherit;
	}
	.error {
		color: var(--margin);
	}
	.done {
		display: block;
		font-size: 1.05rem;
		padding: 0.85rem 1rem;
		border-radius: 0.5rem;
		background: var(--accent);
		margin: 0;
	}
</style>
