<script lang="ts">
	import './layout.css';
	import { site } from '$lib/site';
	import ConsentBanner from '$lib/components/ConsentBanner.svelte';
	// The headline and body faces, fetched before the CSS asks for them: the headline
	// is the largest paint.
	import body from '@fontsource-variable/atkinson-hyperlegible-next/files/atkinson-hyperlegible-next-latin-wght-normal.woff2?url';

	let { children } = $props();
</script>

<svelte:head>
	<link rel="preload" href="/fonts/Excalifont.woff2" as="font" type="font/woff2" crossorigin="anonymous" />
	<link rel="preload" href={body} as="font" type="font/woff2" crossorigin="anonymous" />
	<link rel="icon" href="/favicon.svg" type="image/svg+xml" />
	<link rel="apple-touch-icon" href="/apple-touch-icon.png" />
	<meta name="theme-color" content="#f5f8fc" media="(prefers-color-scheme: light)" />
	<meta name="theme-color" content="#0a1322" media="(prefers-color-scheme: dark)" />
	<meta property="og:site_name" content={site.name} />
	{#if site.plausibleDomain}
		<script defer data-domain={site.plausibleDomain} src={site.plausibleScript}></script>
		<script>
			window.plausible =
				window.plausible ||
				function () {
					(window.plausible.q = window.plausible.q || []).push(arguments);
				};
		</script>
	{/if}
</svelte:head>

{@render children()}
<ConsentBanner />
