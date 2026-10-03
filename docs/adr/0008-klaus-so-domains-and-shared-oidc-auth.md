# Klaus lives on klaus.so, and signs in through a shared OIDC provider

_Amended 2026-10-02: the provider and its dashboard are at app.klaus.so (was auth.klaus.so), and klaus.so is the marketing site (was klausnote.com)._

klaus.ink is retired. klaus.so itself is the marketing site; klausnote.com and klaus.ink redirect to it. The Klaus account lives at app.klaus.so: you sign in there, and once signed in it shows a basic dashboard linking to every Klaus app. The products live on klaus.so subdomains: KlausNote's web app at note.klaus.so and Klaus Agenda at agenda.klaus.so. Wherever ADR-0003, ADR-0006, ADR-0007 and `docs/klaus-ink-sync.md` say klaus.ink, read the klaus.so host above. Those decisions otherwise stand.

The Klaus account is a single OpenID Connect provider at app.klaus.so, built on Better Auth and open source (AGPL) in the `klaus-auth` repository. It is shared by every Klaus product: each product (KlausNote desktop, KlausNote web, Klaus Agenda, later ones) is one OIDC client, and a user is identified everywhere by the same `sub`. Klaus finds the authorize and token endpoints through the provider's `/.well-known/openid-configuration` instead of hard-coding `/oauth/authorize` and `/oauth/token`, so a self-hosted Klaus can sign in through any OIDC provider (or none, in single-user mode).

Klaus stays AGPL with no proprietary code linked into it, because it embeds Anki's AGPL rslib. What only the hosted service has (billing, operations) runs as separate services that talk to Klaus over HTTP. The self-hosted build is the same image, run from one Docker Compose file: the server bridge with the web UI, rslib's sync server, SQLite or Postgres, and an optional OIDC provider.

## Consequences

- To change in the bridge: `DEFAULT_ACCOUNT_URL` and `DEFAULT_SYNC_URL` (`crates/bridge/src/lib.rs`), endpoint discovery in place of the fixed `/oauth/*` paths, the "Open klaus.ink" wording in `src/routes/SyncControl.svelte`, and the fake server in `crates/bridge/tests/bridge.rs`. A server-URL setting lets a self-hosted user point Klaus at their own server.
- `docs/klaus-ink-sync.md` keeps its name until that change lands, then becomes the klaus.so sync contract.
- Billing is undecided; the account is identity only for now.
