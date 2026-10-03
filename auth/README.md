# Klaus Auth

The Klaus account: one OpenID Connect provider at app.klaus.so, shared by every Klaus product (KlausNote desktop and web, Klaus Agenda, later ones). Each product is an OIDC client; a user is the same `sub` everywhere. Decision record: `../app/docs/adr/0008-klaus-so-domains-and-shared-oidc-auth.md`.

- After signing in at app.klaus.so you land on a basic dashboard with a link to each Klaus app (decided 2026-10-02). It starts as links only; showing data from the apps would need each app to publish a summary.
- Built on [Better Auth](https://better-auth.com) with its OIDC provider plugin, on Postgres.
- Open source, AGPL-3.0, like the rest of Klaus. Nothing hosted-only lives here; billing and operations go in the private `klaus-infra` repository.
- Self-hosters don't need it: self-hosted Klaus products accept any OIDC provider, or run single-user. It is there for anyone who runs several Klaus products and wants one login.
- Clients find endpoints through `/.well-known/openid-configuration`. The KlausNote desktop app's current expectations are in `../app/docs/klaus-ink-sync.md`: PKCE, loopback redirect on any port of `127.0.0.1`, client id `klaus-desktop`.
- Billing is undecided. The account is identity only for now.

No code yet. Tasks are on the Auth board (dashboard tab "Auth", prefix `KAU`):

```sh
python3 dashboard/workspace.py board auth list
```
