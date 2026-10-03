<script lang="ts">
	import Wordmark from '$lib/components/Wordmark.svelte';
	import { site } from '$lib/site';
</script>

<svelte:head>
	<title>Privacy · KlausNote</title>
	<meta name="description" content="What klaus.so collects, why, and how to have it removed." />
	<link rel="canonical" href="{site.url}/privacy" />
</svelte:head>

<main class="privacy">
	<a href="/" class="brand" aria-label="Back to KlausNote"><Wordmark size="sm" /></a>
	<h1>Privacy</h1>
	<p class="lede">This covers klaus.so, the website. The KlausNote app and KlausNote for Anki have their own notes in their repositories.</p>

	<h2>Waitlist</h2>
	<p>
		If you join the waitlist we keep your email address, which form you used and when, to tell you
		when KlausNote or KlausNote for Anki is ready to install. It is stored in our database at Supabase (in the
		United States). We don’t sell it or share it with anyone except the services that store it and
		send the messages. Every email has an unsubscribe link, and you can ask us
		to delete your address at any time.
	</p>

	<h2>Analytics</h2>
	{#if site.plausibleDomain}
		<p>
			We count visits with Plausible Analytics. It uses no cookies and stores no personal data:
			only page views, the referring site, rough location by country, and events such as joining
			the waitlist.
		</p>
	{/if}
	{#if site.gaId}
		<p>
			With your permission only, we also use Google Analytics, which sets cookies and sends usage
			data to Google. If you decline, it is never loaded. To change your choice, clear this site’s
			data in your browser and you’ll be asked again.
		</p>
	{/if}
	{#if !site.plausibleDomain && !site.gaId}
		<p>This site does not use analytics.</p>
	{/if}

	<h2>Contact</h2>
	<p>
		To have your email removed or to ask anything about this page, message us on
		<a href={site.discord}>Discord</a> or open an issue on
		<a href={site.appRepo}>GitHub</a>.
	</p>
</main>

<style>
	.privacy {
		max-width: 42rem;
		margin-inline: auto;
		padding: 2rem clamp(1rem, 4vw, 2.5rem) 4rem;
		line-height: 1.65;
	}
	.brand {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		color: var(--klaus-ink);
		text-decoration: none;
	}
	h1 {
		font-family: var(--font-display);
		font-size: 2.5rem;
		margin: 2rem 0 0.5rem;
	}
	h2 {
		font-family: var(--font-display);
		font-size: 1.4rem;
		margin: 2rem 0 0.5rem;
	}
	.lede {
		color: var(--muted-foreground);
	}
	a {
		color: var(--klaus-ink);
	}
</style>
