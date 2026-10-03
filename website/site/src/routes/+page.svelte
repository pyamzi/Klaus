<script lang="ts">
	import Wordmark from '$lib/components/Wordmark.svelte';
	import ReviewCard from '$lib/components/ReviewCard.svelte';
	import { Button } from '$lib/components/ui/button';
	import WaitlistForm from '$lib/components/WaitlistForm.svelte';
	import Star from '@lucide/svelte/icons/star';
	import { site } from '$lib/site';
	import { track } from '$lib/analytics';

	const { discord, appRepo, addonRepo } = site;
	const out = (to: string) => () => track('Outbound click', { to });

	// The header button lands the visitor in the email field, ready to type.
	function joinFromHeader() {
		track('CTA click', { source: 'header' });
		// After the browser's own jump to #waitlist, which would otherwise take focus.
		setTimeout(() => document.getElementById('waitlist-email-hero')?.focus({ preventScroll: true }));
	}

	const title = 'KlausNote — Anki flashcards that remember the lecture';
	const description =
		'KlausNote is a spaced-repetition app built on Anki’s own engine, with FSRS, that keeps your lecture PDFs beside your cards. KlausNote for Anki brings its lecture library into Anki.';

	// Shown on the page and given to search engines as FAQPage data; one source.
	const faq = [
		{
			q: 'Is KlausNote an Anki alternative?',
			a: 'KlausNote runs Anki’s own engine, so it reads the same kind of Collection and schedules cards the same way. It is being built to sync through AnkiWeb, so you can keep using Anki, AnkiMobile and AnkiDroid alongside it.'
		},
		{
			q: 'Does KlausNote support FSRS?',
			a: 'Yes. KlausNote uses Anki’s scheduler, FSRS included, and Anki’s own deck options page, where you can optimise FSRS parameters from your review history.'
		},
		{
			q: 'What is KlausNote for Anki?',
			a: 'An add-on for Anki desktop. Add a lecture PDF and it searches your collection by meaning, tags the cards that lecture covers, and shows a retention score for each lecture so you know what to study first.'
		},
		{
			q: 'Where do my PDFs and cards go?',
			a: 'Your PDFs and notes stay as ordinary files in a folder you choose. KlausNote for Anki matches cards on your own computer through Ollama, so your cards are not sent anywhere to be matched.'
		},
		{
			q: 'How much does it cost?',
			a: 'Both KlausNote and KlausNote for Anki are free and open source under AGPL-3.0. A paid Klaus account is planned for what klaus.so will host, such as syncing your PDFs and notes.'
		},
		{
			q: 'When can I use it?',
			a: 'Neither is released yet. The KlausNote app comes to macOS first, then Windows and Linux. Join the waitlist and we’ll email you when each is ready to install.'
		}
	];

	const jsonLd = JSON.stringify({
		'@context': 'https://schema.org',
		'@graph': [
			{
				'@type': 'WebSite',
				'@id': `${site.url}/#website`,
				url: `${site.url}/`,
				name: site.name,
				description
			},
			{
				'@type': 'SoftwareApplication',
				name: 'KlausNote',
				applicationCategory: 'EducationalApplication',
				operatingSystem: 'macOS',
				description:
					'A spaced-repetition study app built on Anki’s engine that keeps lecture PDFs and notes beside the cards they cover.',
				license: 'https://www.gnu.org/licenses/agpl-3.0.html',
				isAccessibleForFree: true,
				codeRepository: appRepo,
				url: `${site.url}/#app`
			},
			{
				'@type': 'SoftwareApplication',
				name: 'KlausNote for Anki',
				applicationCategory: 'EducationalApplication',
				operatingSystem: 'Windows, macOS, Linux (Anki desktop add-on)',
				description:
					'An Anki add-on that matches lecture PDFs to the cards they cover and scores how well you retain each lecture.',
				license: 'https://www.gnu.org/licenses/agpl-3.0.html',
				isAccessibleForFree: true,
				codeRepository: addonRepo,
				url: `${site.url}/#addon`
			},
			{
				'@type': 'FAQPage',
				mainEntity: faq.map(({ q, a }) => ({
					'@type': 'Question',
					name: q,
					acceptedAnswer: { '@type': 'Answer', text: a }
				}))
			}
		]
	}).replaceAll('<', '\\u003c');

	// The app's milestone order (klaus-note/app docs). Order matters: each builds on the last.
	const roadmap = [
		{ name: 'Everything you use Anki for', detail: 'Review, add and edit, deck options with FSRS, browse, stats, AnkiWeb sync.', now: true },
		{ name: 'Documents', detail: 'Read and annotate lecture PDFs inside KlausNote.' },
		{ name: 'Linking', detail: 'Headings become sections; each section shows the cards that cover it.' },
		{ name: 'Recordings', detail: 'Record a lecture while the slides are open; each slide keeps its own clip and transcript.' },
		{ name: 'Pages', detail: 'Markdown notes with LaTeX that link to your PDFs, Wikipedia-style.' },
		{ name: 'Klaus account', detail: 'Sign in with your Klaus account to sync your PDFs and notes and reach them from AI assistants.' },
		{ name: 'Card generation', detail: 'Draft cards from a section, which you review before they are added.' }
	];
</script>

<svelte:head>
	<title>{title}</title>
	<meta name="description" content={description} />
	<link rel="canonical" href="{site.url}/" />
	<meta property="og:type" content="website" />
	<meta property="og:url" content="{site.url}/" />
	<meta property="og:title" content={title} />
	<meta property="og:description" content={description} />
	<meta property="og:image" content="{site.url}/og.png" />
	<meta property="og:image:width" content="1200" />
	<meta property="og:image:height" content="630" />
	<meta property="og:image:alt" content="KlausNote: study the card, keep the lecture it came from." />
	<meta name="twitter:card" content="summary_large_image" />
	{@html `<script type="application/ld+json">${jsonLd}</script>`}
</svelte:head>

<a class="skip" href="#main">Skip to content</a>

<header class="site-header">
	<a href="/" class="brand" aria-label="KlausNote home"><Wordmark /></a>
	<nav aria-label="Main">
		<a href="#app">App</a>
		<a href="#addon">Anki add-on</a>
		<a href="#faq">FAQ</a>
		{#if site.supabaseUrl}
			<Button href="#waitlist" size="sm" onclick={joinFromHeader}>Join the waitlist</Button>
		{:else}
			<Button href={discord} size="sm" onclick={out('discord')}>Join the Discord</Button>
		{/if}
	</nav>
</header>

<main id="main">
	<section class="hero">
		<div class="pitch">
			<h1>Every card knows its lecture.</h1>
			<p class="lede">
				KlausNote is a study app built on Anki’s own engine, with your lecture PDFs linked to the
				cards that cover them.
			</p>
			<div id="waitlist" class="hero-cta">
				<WaitlistForm source="hero" />
			</div>
			<p class="availability">
				Coming to macOS first. KlausNote for Anki brings the lecture library into Anki.
				<a href={appRepo} onclick={out('app repo')}>View source</a>
			</p>
		</div>
		<div class="demo">
			<ReviewCard />
			<p class="try">Try it. Show the answer, then grade it.</p>
		</div>
	</section>

	<section class="pillars" aria-label="Why KlausNote">
		<dl>
			<div>
				<dt>Anki-native</dt>
				<dd>
					Runs Anki’s own Rust engine, so your Collection, review history and FSRS parameters
					carry over untouched.
				</dd>
			</div>
			<div>
				<dt>Lecture-aware</dt>
				<dd>
					Matches each lecture PDF to the cards it covers, by meaning, on your own computer.
				</dd>
			</div>
			<div>
				<dt>Yours</dt>
				<dd>
					PDFs and notes stay plain files in a folder you choose. Open source under AGPL-3.0.
				</dd>
			</div>
		</dl>
	</section>

	<section class="products" aria-labelledby="products-title">
		<div class="products-intro">
			<h2 id="products-title">Two ways in.</h2>
		</div>

		<article id="app" class="product">
			<div class="product-head">
				<h3><Wordmark size="lg" /></h3>
			</div>
			<p class="product-line">
				<strong>The app.</strong> Everything you use Anki for, with your lectures beside it.
			</p>
			<h4>Working now</h4>
			<ul>
				<li>Review with Anki’s scheduler, FSRS included: show the answer, grade, undo</li>
				<li>Cards render as in Anki: templates, cloze, type-in answers, MathJax</li>
				<li>Add notes with Anki’s own editor, including pasted images</li>
				<li>Import shared <code>.apkg</code> decks</li>
				<li>Deck options, including FSRS optimisation from your review history</li>
			</ul>
			<h4>Coming in the first release</h4>
			<ul class="later">
				<li>Browse and search, with bulk edits</li>
				<li>AnkiWeb sync with Anki, AnkiMobile and AnkiDroid</li>
				<li>Stats, backups, import and export</li>
			</ul>
			<div class="actions">
				<Button href={appRepo} variant="outline" onclick={out('star app')}>
					<Star aria-hidden="true" /> Star KlausNote on GitHub
				</Button>
			</div>
			<p class="fine">In development, macOS first. No download yet. Free and open source under AGPL-3.0.</p>
		</article>

		<article id="addon" class="product">
			<div class="product-head">
				<h3><Wordmark product="addon" size="lg" /></h3>
			</div>
			<p class="product-line">
				<strong>The add-on.</strong> KlausNote’s lecture library, inside the Anki you already use.
			</p>
			<h4>What it does</h4>
			<ul>
				<li>
					<strong>Card matching:</strong> searches your whole collection by meaning and tags every
					card a lecture covers
				</li>
				<li>
					<strong>Library:</strong> your lecture PDFs in folders, each with a retention score for
					its matched cards, so you can see what to study first
				</li>
				<li>
					<strong>PDF viewer:</strong> highlights and sticky notes saved into the PDF as real
					annotations
				</li>
				<li>
					<strong>Curated decks:</strong> copy the matched notes into a new deck in one undoable
					step; originals stay untouched
				</li>
				<li><strong>Image cropping:</strong> crop any image in a field without changing the original</li>
			</ul>
			<div class="actions">
				<Button href={addonRepo} variant="outline" onclick={out('star addon')}>
					<Star aria-hidden="true" /> Star KlausNote for Anki on GitHub
				</Button>
			</div>
			<p class="fine">
				Pre-release, not on AnkiWeb yet. Matching runs on your computer through Ollama; your
				cards are not sent anywhere to be matched.
			</p>
		</article>
	</section>


	<section id="faq" class="faq" aria-labelledby="faq-title">
		<h2 id="faq-title">Questions</h2>
		{#each faq as item (item.q)}
			<details>
				<summary>{item.q}</summary>
				<p>{item.a}</p>
			</details>
		{/each}
	</section>

	<section id="roadmap" class="roadmap" aria-labelledby="roadmap-title">
		<h2 id="roadmap-title">Roadmap</h2>
		<p class="section-lede">Built in this order. Each step needs the one before it.</p>
		<ol>
			{#each roadmap as step (step.name)}
				<li class:now={step.now}>
					<span class="step-name">
						{step.name}{#if step.now}<span class="now-note"> · in progress</span>{/if}
					</span>
					<span class="step-detail">{step.detail}</span>
				</li>
			{/each}
		</ol>
		<p class="fine">
			Also planned: KlausNote in the browser at <strong>note.klaus.so</strong>, and Windows, Linux,
			iOS and Android after macOS.
		</p>
	</section>

	<section class="closing" aria-labelledby="closing-title">
		<h2 id="closing-title">Get KlausNote first.</h2>
		{#if site.supabaseUrl}
			<p>One email when KlausNote for Anki is ready. One when the KlausNote app is.</p>
		{/if}
		<WaitlistForm source="closing" hideLabel />
		{#if site.supabaseUrl}
			<p class="fine">
				Rather talk now? <a href={discord} onclick={out('discord')}>Join the Discord</a>.
			</p>
		{/if}
	</section>
</main>

<footer class="site-footer">
	<div class="brand"><Wordmark size="sm" /></div>
	<p>
		KlausNote is built on Anki’s open-source engine. It is an independent project, not made by or
		affiliated with Ankitects.
	</p>
	<nav aria-label="Footer">
		<a href={appRepo} onclick={out('app repo')}>App on GitHub</a>
		<a href={addonRepo} onclick={out('addon repo')}>Add-on on GitHub</a>
		<a href={discord} onclick={out('discord')}>Discord</a>
		<a href="/privacy">Privacy</a>
	</nav>
</footer>

<style>
	.skip {
		position: absolute;
		left: 1rem;
		top: -3rem;
		background: var(--card);
		padding: 0.5rem 0.75rem;
		border-radius: 0.375rem;
		z-index: 10;
	}
	.skip:focus {
		top: 1rem;
	}
	.site-header,
	main,
	.site-footer {
		max-width: 72rem;
		margin-inline: auto;
		padding-inline: clamp(1rem, 4vw, 2.5rem);
	}
	.site-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		padding-block: 1.25rem;
	}
	.brand {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		color: var(--klaus-ink);
		text-decoration: none;
	}
	nav {
		display: flex;
		align-items: center;
		gap: 1.25rem;
		flex-wrap: wrap;
	}
	nav a:not([data-slot]) {
		color: inherit;
		text-decoration: none;
		font-size: 0.95rem;
	}
	nav a:not([data-slot]):hover {
		text-decoration: underline;
		text-underline-offset: 0.25em;
	}

	.hero {
		display: grid;
		grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
		gap: clamp(2rem, 5vw, 4.5rem);
		align-items: center;
		padding-block: clamp(2.5rem, 7vw, 6rem);
	}
	h1 {
		font-family: var(--font-display);
		font-size: clamp(2.4rem, 1.5rem + 2.8vw, 3.9rem);
		line-height: 1.05;
		margin: 0 0 1.25rem;
		text-wrap: balance;
	}
	.lede {
		font-size: 1.2rem;
		line-height: 1.6;
		max-width: 34rem;
		margin: 0 0 1.25rem;
	}
	.hero-cta {
		margin: 0 0 1rem;
		scroll-margin-top: 2rem;
	}
	.availability {
		font-size: 0.9rem;
		color: var(--muted-foreground);
		margin: 0;
	}
	.availability a {
		color: var(--klaus-ink);
		white-space: nowrap;
	}
	.demo {
		display: grid;
		gap: 0.75rem;
	}
	.pillars {
		padding-block: 0 4rem;
	}
	.pillars dl {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 2rem;
		margin: 0;
	}
	.pillars dt {
		font-family: var(--font-display);
		font-size: 1.35rem;
		margin-bottom: 0.4rem;
	}
	.pillars dd {
		margin: 0;
		line-height: 1.55;
		color: var(--muted-foreground);
	}
	.product-line {
		font-size: 1.1rem;
		margin: 0.75rem 0 0;
	}
	.try {
		font-size: 0.875rem;
		color: var(--muted-foreground);
		margin: 0;
	}

	.products-intro {
		grid-column: 1 / -1;
		max-width: 44rem;
	}
	.products-intro h2 {
		margin-bottom: 0.75rem;
	}
	.products {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 1.5rem;
		padding-block: 1rem 4rem;
	}
	.product {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 0.75rem;
		padding: clamp(1.25rem, 3vw, 2rem);
		display: flex;
		flex-direction: column;
	}
	.product-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 0.75rem;
		flex-wrap: wrap;
	}
	h3 {
		font-family: var(--font-display);
		font-size: 2rem;
		margin: 0;
	}
	.product p {
		line-height: 1.6;
	}
	h4 {
		font-weight: 700;
		font-size: 0.95rem;
		margin: 1.25rem 0 0.5rem;
	}
	ul {
		margin: 0;
		padding-left: 1.1rem;
		display: grid;
		gap: 0.45rem;
		line-height: 1.5;
	}
	ul.later {
		color: var(--muted-foreground);
	}
	code {
		font-family: var(--font-mono);
		font-size: 0.9em;
	}
	.actions {
		margin-top: auto;
		padding-top: 1.5rem;
	}
	.fine {
		font-size: 0.875rem;
		color: var(--muted-foreground);
		margin: 0.75rem 0 0;
	}

	h2 {
		font-family: var(--font-display);
		font-size: clamp(1.8rem, 1.4rem + 1.5vw, 2.5rem);
		margin: 0 0 1.5rem;
	}

	.faq {
		padding-block: 3rem;
		border-top: 1px solid var(--border);
		max-width: 48rem;
	}
	details {
		border-bottom: 1px solid var(--rule);
	}
	summary {
		cursor: pointer;
		font-weight: 700;
		padding: 1rem 2.5rem 1rem 0;
		list-style: none;
		position: relative;
	}
	summary::-webkit-details-marker {
		display: none;
	}
	summary:hover {
		color: var(--klaus-ink);
	}
	/* A drawn plus that turns into a minus when open. */
	summary::before,
	summary::after {
		content: '';
		position: absolute;
		right: 0.25rem;
		top: 50%;
		width: 0.8rem;
		height: 2px;
		border-radius: 1px;
		background: currentColor;
		transition: transform 200ms cubic-bezier(0.16, 1, 0.3, 1);
	}
	summary::after {
		transform: rotate(90deg);
	}
	details[open] summary::after {
		transform: rotate(0deg);
	}
	details p {
		max-width: 65ch;
		margin: 0 0 1.1rem;
		line-height: 1.6;
		color: var(--muted-foreground);
	}
	.closing {
		padding-block: 3rem 4.5rem;
		border-top: 1px solid var(--border);
		display: grid;
		gap: 1rem;
		justify-items: start;
	}
	.closing h2 {
		margin: 0;
	}
	.closing > p {
		margin: 0;
	}
	.closing .fine a {
		color: inherit;
	}
	.roadmap {
		padding-block: 3rem 4rem;
		border-top: 1px solid var(--border);
	}
	.section-lede {
		margin: -0.75rem 0 1.75rem;
		color: var(--muted-foreground);
	}
	ol {
		list-style: none;
		counter-reset: step;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 0;
	}
	ol li {
		counter-increment: step;
		display: grid;
		grid-template-columns: 2.5rem 1fr;
		column-gap: 0.75rem;
		align-items: baseline;
		padding: 0.9rem 0;
		border-bottom: 1px solid var(--rule);
	}
	ol li::before {
		content: counter(step);
		font-family: var(--font-display);
		font-size: 1.25rem;
		color: var(--muted-foreground);
		grid-row: span 2;
	}
	.now-note {
		font-weight: 400;
		color: var(--klaus-ink);
	}
	ol li.now::before {
		color: var(--klaus-ink);
	}
	.step-name {
		font-weight: 700;
	}
	.step-detail {
		grid-column: 2 / -1;
		color: var(--muted-foreground);
		line-height: 1.5;
	}

	.site-footer {
		display: grid;
		gap: 1rem;
		padding-block: 2.5rem 3rem;
		border-top: 1px solid var(--border);
		color: var(--muted-foreground);
		font-size: 0.9rem;
	}
	.site-footer p {
		margin: 0;
		max-width: 40rem;
	}
	.site-footer a {
		color: inherit;
	}

	:global(a:focus-visible),
	:global(button:focus-visible) {
		outline: 2px solid var(--klaus);
		outline-offset: 2px;
	}

	@media (max-width: 40rem) {
		.site-header nav a:not([data-slot]) {
			display: none;
		}
	}
	@media (max-width: 52rem) {
		.pillars dl {
			grid-template-columns: 1fr;
			gap: 1.25rem;
		}
		.hero,
		.products {
			grid-template-columns: 1fr;
		}
	}
</style>
