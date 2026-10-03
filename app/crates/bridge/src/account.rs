//! The Klaus Account (ADR-0007, ADR-0008): browser sign-in with PKCE, the sync
//! key in a [`Secrets`] store, and sign-out. ADR-0008's OIDC endpoint discovery
//! lands here. Sync (sync.rs) reads the key; nothing here depends on sync.

use std::sync::Mutex;

use serde_json::Value;

use crate::{Bridge, CallError};

/// Secret storage (the sync key must never be written to a plain file).
pub trait Secrets: Send + Sync {
    fn get(&self, key: &str) -> Option<String>;
    fn set(&self, key: &str, value: &str) -> Result<(), String>;
    /// Removing a key that isn't there succeeds.
    fn delete(&self, key: &str) -> Result<(), String>;
}

/// In-memory secrets: tests, and builds without a keychain.
#[derive(Default)]
pub struct MemorySecrets(Mutex<std::collections::HashMap<String, String>>);

impl Secrets for MemorySecrets {
    fn get(&self, key: &str) -> Option<String> {
        self.0.lock().unwrap().get(key).cloned()
    }
    fn set(&self, key: &str, value: &str) -> Result<(), String> {
        self.0.lock().unwrap().insert(key.into(), value.into());
        Ok(())
    }
    fn delete(&self, key: &str) -> Result<(), String> {
        self.0.lock().unwrap().remove(key);
        Ok(())
    }
}

pub(crate) const SYNC_KEY: &str = "klaus-account-sync-key";
/// Profile settings only the bridge writes: the sync key is sent to `syncUrl`.
pub(crate) const ACCOUNT_KEYS: &[&str] = &["syncUrl", "syncUser"];
const DEFAULT_ACCOUNT_URL: &str = "https://klaus.ink";

/// The account half of [`Bridge`].
pub(crate) struct Account {
    /// Where the AnkiWeb sync key lives: the macOS Keychain in the app.
    pub(crate) secrets: Box<dyn Secrets>,
    /// klaus.ink, where the Klaus Account signs in (ADR-0007).
    pub(crate) url: Mutex<String>,
    /// This bridge's own origin, for the sign-in redirect back to it; set by `serve`.
    pub(crate) origin: Mutex<Option<String>>,
    /// The sign-in in progress: (state, PKCE verifier, redirect URI).
    pub(crate) pending_sign_in: Mutex<Option<(String, String, String)>>,
}

impl Account {
    pub(crate) fn new(secrets: Box<dyn Secrets>) -> Self {
        Self {
            secrets,
            url: Mutex::new(std::env::var("KLAUS_ACCOUNT_URL").unwrap_or_else(|_| DEFAULT_ACCOUNT_URL.into())),
            origin: Mutex::new(None),
            pending_sign_in: Mutex::new(None),
        }
    }

    pub(crate) fn set_origin(&self, origin: String) {
        *self.origin.lock().unwrap() = Some(origin);
    }

    /// The account's sync key (Anki's hkey), if signed in.
    pub(crate) fn sync_key(&self) -> Option<String> {
        self.secrets.get(SYNC_KEY)
    }
}

impl Bridge {
    /// Where klaus.ink is (tests and staging point it elsewhere).
    pub fn set_account_url(&self, url: &str) {
        *self.account.url.lock().unwrap() = url.trim_end_matches('/').to_owned();
    }

    /// Starts a browser sign-in (OAuth 2.0 code flow with PKCE, RFC 8252 loopback
    /// redirect to this bridge): returns the klaus.ink URL the page opens.
    pub fn account_sign_in_url(&self) -> Result<String, CallError> {
        use base64::Engine;
        use rand::Rng;
        let origin = self.account.origin.lock().unwrap().clone().ok_or_else(|| CallError::Backend("bridge not serving".into()))?;
        let b64 = base64::engine::general_purpose::URL_SAFE_NO_PAD;
        let state = b64.encode(rand::rng().random::<[u8; 16]>());
        let verifier = b64.encode(rand::rng().random::<[u8; 32]>());
        let challenge = b64.encode(<sha2::Sha256 as sha2::Digest>::digest(verifier.as_bytes()));
        let redirect = format!("{origin}/auth/callback");
        let url = format!(
            "{}/oauth/authorize?response_type=code&client_id=klaus-desktop&redirect_uri={}&code_challenge={challenge}&code_challenge_method=S256&state={state}",
            self.account.url.lock().unwrap(),
            form_encode(&redirect),
        );
        *self.account.pending_sign_in.lock().unwrap() = Some((state, verifier, redirect));
        Ok(url)
    }

    /// klaus.ink's redirect back: checks the state (one-shot), exchanges the code
    /// for the account's sync key, and stores it.
    pub(crate) async fn finish_sign_in(&self, code: &str, state: &str) -> Result<String, String> {
        // Consumed only by its own state, so a stray callback can't cancel it.
        let pending = {
            let mut pending = self.account.pending_sign_in.lock().unwrap();
            pending.take_if(|(expected, ..)| expected == state)
        };
        let Some((_, verifier, redirect)) = pending else {
            return Err("This sign-in link has expired. Start again from KlausNote.".into());
        };
        #[derive(serde::Deserialize)]
        struct Token {
            access_token: String,
            email: String,
            sync_url: Option<String>,
        }
        let url = format!("{}/oauth/token", self.account.url.lock().unwrap());
        let form = [
            ("grant_type", "authorization_code"),
            ("code", code),
            ("code_verifier", &verifier),
            ("redirect_uri", &redirect),
            ("client_id", "klaus-desktop"),
        ];
        let response = reqwest::Client::new().post(url).form(&form).send().await.map_err(|e| e.to_string())?;
        if !response.status().is_success() {
            return Err(format!("klaus.ink refused the sign-in ({}).", response.status()));
        }
        let token: Token = response.json().await.map_err(|e| e.to_string())?;
        self.account.secrets.set(SYNC_KEY, &token.access_token)?;
        let set = |key: &str, value: Value| self.set_setting("profile", key, value).map_err(|e| format!("{e:?}"));
        set("syncUser", token.email.clone().into())?;
        set("syncUrl", token.sync_url.map_or(Value::Null, Value::from))?;
        Ok(token.email)
    }

    /// pm.clear_sync_auth.
    pub fn sync_sign_out(&self) -> Result<(), CallError> {
        self.account.secrets.delete(SYNC_KEY).map_err(CallError::Backend)?;
        self.set_setting("profile", "syncUser", Value::Null)?;
        self.set_setting("profile", "syncUrl", Value::Null)
    }
}

/// application/x-www-form-urlencoded value encoding.
fn form_encode(s: &str) -> String {
    s.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' => (b as char).to_string(),
            _ => format!("%{b:02X}"),
        })
        .collect()
}
