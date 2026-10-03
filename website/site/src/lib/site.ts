// Everything account-specific about klausnote.com, in one place. None of these are
// secrets: they all end up in the public page. Leave a value empty to switch that
// feature off; the site still builds and works without it.
export const site = {
	url: 'https://klausnote.com',
	name: 'KlausNote',

	// Waitlist signups go to the "Klaus" Supabase project, through its public
	// join_waitlist() function; the table itself is closed to the public. The
	// publishable key is meant to be public. Empty: the waitlist shows a Discord link.
	supabaseUrl: 'https://pmdpzroiuhlhwovcqvuz.supabase.co',
	supabaseKey: 'sb_publishable_Y3hIvybDMyie11S9rspcYQ_HQjE4KQj',

	// Plausible (no cookies, no consent needed): the site's domain as set up in
	// Plausible. scriptSrc can point at a self-hosted Plausible.
	plausibleDomain: '',
	plausibleScript: 'https://plausible.io/js/script.tagged-events.js',

	// Google Analytics 4 measurement ID (G-…). Loaded only after the visitor accepts
	// it in the consent banner.
	gaId: '',

	discord: 'https://discord.gg/uFRgE8RtDY',
	appRepo: 'https://github.com/pyamzi/klaus-note',
	addonRepo: 'https://github.com/pyamzi/klaus-note-addon'
};
