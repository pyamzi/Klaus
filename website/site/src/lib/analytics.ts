import { site } from '$lib/site';

type Props = Record<string, string>;
type Win = Window & {
	plausible?: (event: string, options?: { props?: Props }) => void;
	gtag?: (...args: unknown[]) => void;
	dataLayer?: unknown[];
};

const CONSENT_KEY = 'klaus-analytics-consent';

/** Sends one event to whichever analytics are running (none, Plausible, GA or both). */
export function track(event: string, props: Props = {}) {
	const w = window as Win;
	w.plausible?.(event, { props });
	w.gtag?.('event', event.toLowerCase().replaceAll(' ', '_'), props);
}

/** 'granted' | 'denied' | null (not asked yet). Storage can be blocked; then ask. */
export function storedConsent(): string | null {
	try {
		return localStorage.getItem(CONSENT_KEY);
	} catch {
		return null;
	}
}

export function setConsent(choice: 'granted' | 'denied') {
	try {
		localStorage.setItem(CONSENT_KEY, choice);
	} catch {
		// Not remembered; the banner asks again next visit.
	}
	if (choice === 'granted') loadGoogleAnalytics();
}

let gaLoaded = false;
/** Google Analytics 4, loaded only once the visitor has accepted it. */
export function loadGoogleAnalytics() {
	if (!site.gaId || gaLoaded) return;
	gaLoaded = true;
	const w = window as Win;
	w.dataLayer = w.dataLayer || [];
	w.gtag = function () {
		// gtag.js reads the raw arguments object.
		// eslint-disable-next-line prefer-rest-params
		w.dataLayer!.push(arguments);
	};
	w.gtag('js', new Date());
	w.gtag('config', site.gaId, { anonymize_ip: true });
	const script = document.createElement('script');
	script.async = true;
	script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(site.gaId)}`;
	document.head.append(script);
}
