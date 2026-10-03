# Klaus Auth board

<!-- Source of truth for all agent work. State changes (claim/move/comment)
     MUST go through board/board.py so they are serialized by its lockfile.
     Direct edits to this file: card *body* prose only, by the orchestrator
     or designer. See klaus-note/addon/context/ROLES.md. -->

## Backlog

### KAU-001: Better Auth OIDC provider for app.klaus.so
owner: -
priority: P1
created: 2026-10-02

Small TypeScript service: Better Auth + its OIDC provider plugin on Postgres, AGPL-3.0, in klaus-auth/ (git init its own repo). Served at app.klaus.so (decided 2026-10-02; was auth.klaus.so), the same app as the dashboard (KAU-003). Discovery at /.well-known/openid-configuration; register client klaus-desktop (PKCE, loopback redirect on any 127.0.0.1 port; see klaus-note/app/docs/klaus-ink-sync.md). Check the current state of Better Auth's OIDC/OAuth provider plugin before choosing it. Branded sign-in page. Docker Compose for local dev. Decision: klaus-note/app/docs/adr/0008-klaus-so-domains-and-shared-oidc-auth.md (needs amending: it still says auth.klaus.so).

### KAU-002: Private klaus-infra repo for hosted-only services
owner: -
priority: P3
created: 2026-10-02

Billing (undecided), production config and operations for klaus.so live here, never linked into Klaus Note (Anki rslib is AGPL). Create when the first hosted-only piece exists.

### KAU-003: Basic dashboard at app.klaus.so after sign-in
owner: -
priority: P2
created: 2026-10-02

Once signed in at app.klaus.so, the user lands on a basic dashboard: the Klaus account (name, email, sign out) and a tile linking to each Klaus app (KlausNote at note.klaus.so, Klaus Agenda at agenda.klaus.so, later ones). Links only to start; showing app data (due cards, today's agenda) would need each app to publish a summary endpoint and is a later card. Same app and origin as the OIDC provider (KAU-001), per the user's decision on 2026-10-02. Optional in self-host Compose. Built with shadcn-svelte like the other Klaus UIs.

## Ready

## Doing

## Review

## Done
