# Klaus Note Website

The klausnote.com marketing site lives in `site/` (SvelteKit + Tailwind + shadcn-svelte, prerendered by adapter-static). This folder is its own Git repository (local only for now), and the site is not deployed.

Read `../shared-context/CONTEXT.md` for shared decisions and cross-project handoffs.

Logo: `../addon/docs/reference/brand/klaus-logo.svg` (favicon: the full tile; page chrome: the bare k in the accent colour).

```sh
cd site
npm install
npm run dev        # http://localhost:5173
npm run build      # static site in site/build, ready for any static host
npm run deploy     # build and publish to klausnote.com (Vercel project klaus-ink, still named after the old domain; link in site/.vercel)
```

Before launch, fill in `site/src/lib/site.ts` (the only account-specific file): the Supabase project the waitlist writes to (already set: the "Klaus" project; schema in `site/supabase/waitlist.sql`, signups readable only from the Supabase dashboard), the Plausible domain, and the Google Analytics ID (loaded only after consent). Conversions are tracked as `Waitlist signup` (with the form's `source`), `CTA click` and `Outbound click`; in Plausible, add `Waitlist signup` as a custom-event goal. After deploying, submit `https://klausnote.com/sitemap.xml` in Google Search Console.

The page is `site/src/routes/+page.svelte`; the hero's review card is `site/src/lib/components/ReviewCard.svelte`; the palette and fonts are in `site/src/routes/layout.css`. Product claims on the page come from the app's and add-on's docs: keep them in step when either ships something (the app's status list, the add-on's AnkiWeb status, the roadmap order). Planned: Klaus Note in the browser at note.klaus.so, signing in through the Klaus Account at auth.klaus.so (app ADR-0008).

Use the Note Website tab at http://127.0.0.1:8766 for tasks.

From this folder, run the shared board CLI with an explicit directory and ID prefix:

```sh
BOARD_DIR="$PWD/board" KLAUS_BOARD_DIR="$PWD/board" BOARD_PREFIX=KW python3 ../addon/board/board.py list
```

Replace `list` with the needed board command. Never edit board state by hand.
