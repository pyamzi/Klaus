# Klaus lives on klaus.so, and signs in through a shared OIDC provider

klaus.ink is retired. The hosted products live on klaus.so: Klaus Note's web app at note.klaus.so, the Klaus Account at auth.klaus.so, and Klaus Agenda at agenda.klaus.so. klausnote.com is Klaus Note's marketing site. Wherever ADR-0003, ADR-0006, ADR-0007 and `docs/klaus-ink-sync.md` say klaus.ink, read the klaus.so host above. Those decisions otherwise stand.

The Klaus Account is a single OpenID Connect provider at auth.klaus.so, built on Better Auth and open source (AGPL) in the `klaus-auth` repository. It is shared by every Klaus product: each product (Klaus Note desktop, Klaus Note web, Klaus Agenda, later ones) is one OIDC client, and a user is identified everywhere by the same `sub`. Klaus finds the authorize and token endpoints through the provider's `/.well-known/openid-configuration` instead of hard-coding `/oauth/authorize` and `/oauth/token`, so a self-hosted Klaus can sign in through any OIDC provider (or none, in single-user mode).

Klaus stays AGPL with no proprietary code linked into it, because it embeds Anki's AGPL rslib. What only the hosted service has (billing, operations) runs as separate services that talk to Klaus over HTTP. The self-hosted build is the same image, run from one Docker Compose file: the server bridge with the web UI, rslib's sync server, SQLite or Postgres, and an optional OIDC provider.

## Consequences

- To change in the bridge: `DEFAULT_ACCOUNT_URL` and `DEFAULT_SYNC_URL` (`crates/bridge/src/lib.rs`), endpoint discovery in place of the fixed `/oauth/*` paths, the "Open klaus.ink" wording in `src/routes/SyncControl.svelte`, and the fake server in `crates/bridge/tests/bridge.rs`. A server-URL setting lets a self-hosted user point Klaus at their own server.
- `docs/klaus-ink-sync.md` keeps its name until that change lands, then becomes the klaus.so sync contract.
- Billing is undecided; the account is identity only for now.
