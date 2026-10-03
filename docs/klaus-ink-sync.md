# klaus.ink sync contract

> Domain superseded by ADR-0008: klaus.ink is now klaus.so (app.klaus.so for the Klaus account, note.klaus.so for the web app).

What the Klaus desktop app expects from klaus.ink (ADR-0007). The app's side is in `crates/bridge` (`account_*`, `sync`, `auto_sync_tick`) and is tested against a fake of this contract in `crates/bridge/tests/bridge.rs`.

## Sign-in: OAuth 2.0 authorization code with PKCE (RFC 6749, RFC 7636, RFC 8252)

The app is a public client (no secret), `client_id=klaus-desktop`.

1. The app opens the system browser at

   `GET https://klaus.ink/oauth/authorize?response_type=code&client_id=klaus-desktop&redirect_uri=<uri>&code_challenge=<challenge>&code_challenge_method=S256&state=<state>`

   - `redirect_uri` is a loopback URI, `http://127.0.0.1:<port>/auth/callback`. The port changes on every launch, so klaus.ink must accept any port on `127.0.0.1` for this path (RFC 8252 §7.3).
   - `code_challenge` is base64url (no padding) of SHA-256 of the verifier.
2. After the user signs in (and, when needed, subscribes), klaus.ink redirects to `<redirect_uri>?code=<code>&state=<state>`, or `?error=<code>&state=<state>` if the user cancels.
3. The app exchanges the code:

   `POST https://klaus.ink/oauth/token` (form-encoded) with `grant_type=authorization_code`, `code`, `code_verifier`, `redirect_uri`, `client_id`.

   Response, `200 application/json`:

   ```json
   { "access_token": "…", "token_type": "Bearer", "email": "user@example.com", "sync_url": "https://sync.klaus.ink/" }
   ```

   - `access_token` doubles as the Anki sync key (the protocol's `hkey`). It is long-lived until revoked, like Anki's own sync keys, so the app keeps no refresh token. Revoking it (sign-out everywhere, password change) makes the sync server answer `403`; the app then signs out and asks the user to sign in again.
   - `sync_url` is the sync server to use; it lets klaus.ink move users between servers.

## Sync: Anki's sync protocol

`sync_url` serves rslib's sync server (`/sync/…` and `/msync/…`, as `anki::sync::http_server` does). It accepts the `access_token` as the sync key. For AnkiMobile and AnkiDroid, its `hostKey` endpoint also issues a sync key for an account's email and password, so the phone can be pointed at `sync_url` with the user's Klaus Account credentials.
