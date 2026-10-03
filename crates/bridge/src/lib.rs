//! The Backend Bridge: the one seam between Klaus's webview and Anki's rslib.
//!
//! It speaks the contract Anki's generated TypeScript client already uses
//! (`POST /_anki/<camelCaseMethod>`, protobuf bytes in and out), so Anki's own
//! pages and client run unmodified.

use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use anki::backend::{init_backend, Backend};
use anki_proto::backend::{backend_error, BackendError, BackendInit};
use anki_proto::collection::{CloseCollectionRequest, OpenCollectionRequest};
use anki_proto::generic;
use axum::body::Bytes;
use axum::extract::{DefaultBodyLimit, Path as UrlPath, Query, Request, State};
use axum::http::{header, HeaderMap, HeaderValue, StatusCode};
use axum::middleware::{self, Next};
use axum::response::{Html, IntoResponse, Response};
use axum::routing::{get, post};
use axum::Router;
use prost::Message;
use serde_json::Value;
use tower::ServiceExt;
use tower_http::services::{ServeDir, ServeFile};

include!(concat!(env!("OUT_DIR"), "/methods.rs"));

/// Klaus's own bridge methods' messages (`proto/klaus.proto`).
pub mod klaus {
    include!(concat!(env!("OUT_DIR"), "/klaus.rs"));
}

/// Messages from Anki's `anki/frontend.proto` (the page ↔ Qt host contract), which
/// anki_proto doesn't compile for Rust. Field tags must match the .proto.
pub mod frontend {
    #[derive(Clone, PartialEq, prost::Message)]
    pub struct ConvertPastedImageRequest {
        #[prost(bytes = "vec", tag = "1")]
        pub data: Vec<u8>,
        #[prost(string, tag = "2")]
        pub ext: String,
    }
    #[derive(Clone, PartialEq, prost::Message)]
    pub struct ConvertPastedImageResponse {
        #[prost(bytes = "vec", tag = "1")]
        pub data: Vec<u8>,
    }
    #[derive(Clone, PartialEq, prost::Message)]
    pub struct SetSettingJsonRequest {
        #[prost(string, tag = "1")]
        pub key: String,
        #[prost(bytes = "vec", tag = "2")]
        pub value_json: Vec<u8>,
    }
    #[derive(Clone, PartialEq, prost::Message)]
    pub struct OpenFilePickerRequest {
        #[prost(string, tag = "1")]
        pub title: String,
        #[prost(string, tag = "2")]
        pub key: String,
        #[prost(string, tag = "3")]
        pub filter_description: String,
        #[prost(string, repeated, tag = "4")]
        pub extensions: Vec<String>,
    }
    #[derive(Clone, PartialEq, prost::Message)]
    pub struct AskUserRequest {
        #[prost(string, tag = "1")]
        pub text: String,
        #[prost(string, optional, tag = "4")]
        pub title: Option<String>,
        #[prost(bool, optional, tag = "5")]
        pub default_no: Option<bool>,
    }
    #[derive(Clone, PartialEq, prost::Message)]
    pub struct ShowMessageBoxRequest {
        #[prost(string, tag = "1")]
        pub text: String,
        /// MessageBoxType: 0 info, 1 warning, 2 error.
        #[prost(int32, tag = "2")]
        pub r#type: i32,
        #[prost(string, optional, tag = "4")]
        pub title: Option<String>,
    }
}
use frontend::{ConvertPastedImageRequest, ConvertPastedImageResponse, SetSettingJsonRequest};

/// Methods the webview may call. Anki's mediasrv allowlist plus what Klaus's own
/// screens need; grow it per feature. Card HTML can carry arbitrary JS, so the
/// webview never gets the whole backend.
const ALLOWED: &[&str] = &[
    "deckTree",
    // Klaus's review screen (Anki's reviewer calls these from Python, not a page).
    // Cards render in a sandboxed frame that can't reach /_anki, so card JS never
    // gets these.
    "setCurrentDeck",
    "getQueuedCards",
    "describeNextStates",
    "answerCard",
    "undo",
    "getUndoStatus",
    "congratsInfo",
    // Sync progress and cancelling (the sync itself goes through Klaus's methods,
    // which keep the AnkiWeb key out of the page).
    "mediaSyncStatus",
    "abortSync",
    "abortMediaSync",
    // Klaus's deck list (Anki's deckbrowser.py and filtered deck dialog).
    "newDeck",
    "addDeck",
    "renameDeck",
    "removeDecks",
    "setDeckCollapsed",
    "getOrCreateFilteredDeck",
    "addOrUpdateFilteredDeck",
    "rebuildFilteredDeck",
    "emptyFilteredDeck",
    // Klaus's browser (Anki's is Qt: aqt/browser). The side editor is Anki's
    // editor page, which saves through updateNotes itself.
    "searchCards",
    "searchNotes",
    "browserRowForId",
    "allBrowserColumns",
    "setActiveBrowserColumns",
    "buildSearchString",
    "tagTree",
    "setConfigBool",
    "cardsOfNote",
    // A mediasrv post handler in Anki (missing keys read as null); see Bridge::call.
    "getConfigJson",
    // Deck options: post handlers in Anki, a plain backend call there too. Saving
    // (updateDeckConfigs) is not a passthrough; see save_deck_configs.
    "getDeckConfigsForUpdate",
    // Anki 26.09.3 qt/aqt/mediasrv.py exposed_backend_list, in order.
    "latestProgress",
    "getCustomColours",
    "getDeckNames",
    "getDeck",
    "i18nResources",
    "getCsvMetadata",
    "getImportAnkiPackagePresets",
    "importCsv",
    "importAnkiPackage",
    "importJsonFile",
    "importJsonString",
    "getFieldNames",
    "getNote",
    "newNote",
    "noteFieldsCheck",
    "defaultsForAdding",
    "defaultDeckForNotetype",
    "addNote",
    "updateNotes",
    "updateNotetype",
    "getNotetype",
    "getNotetypeNames",
    "getChangeNotetypeInfo",
    "getClozeFieldOrds",
    "cardStats",
    "getReviewLogs",
    "graphs",
    "getGraphPreferences",
    "setGraphPreferences",
    "completeTag",
    "getImageForOcclusion",
    "addImageOcclusionNote",
    "getImageOcclusionNote",
    "updateImageOcclusionNote",
    "getImageOcclusionFields",
    "computeFsrsParams",
    "computeOptimalRetention",
    "setWantsAbort",
    "evaluateParamsLegacy",
    "getOptimalRetentionParameters",
    "simulateFsrsReview",
    "simulateFsrsWorkload",
    "getIgnoredBeforeCount",
    "getRetentionWorkload",
    "encodeIriPaths",
    "decodeIriPaths",
    "htmlToTextLine",
    "setConfigJson",
    "getConfigBool",
    "addMediaFile",
    "addMediaFromPath",
    "addMediaFromUrl",
    "getAbsoluteMediaPath",
    "extractMediaFiles",
    "getCard",
];

/// Calls the webview makes that Klaus's shell answers instead of the backend:
/// Anki pages' requests to their Qt host (mediasrv post_handler_list), plus
/// Klaus's own. The hook's reply (protobuf) is returned; none means 204, which
/// Anki's client reads as an empty (default) message.
const HOOKS: &[&str] = &[
    "importDone",
    "importDialogRequireClose",
    "searchInBrowser",
    "closeAddCards",
    "openFilePicker",
    "askUser",
    "showMessageBox",
    "openFieldsDialog",
    "openCardsDialog",
    "openLink",
    "openMedia",
    "showInMediaFolder",
    "recordAudio",
    "playFile",
    "readClipboard",
    "writeClipboard",
    "saveCustomColours",
    "klausImportPackage",
    "klausPaste",
    "deckOptionsReady",
    "deckOptionsRequireClose",
];

/// Anki host calls that are pure data, answered by the bridge itself.
const LOCAL: &[&str] = &[
    "getMetaJson",
    "setMetaJson",
    "getProfileConfigJson",
    "setProfileConfigJson",
    "convertPastedImage",
    "klausRenderCard",
    "klausSyncAccount",
    "klausAccountSignIn",
    "klausSyncSignOut",
    "klausSyncOutcome",
];

/// Klaus's sync calls that run in the background (see `start_sync`): the page
/// polls `klausSyncOutcome`, `latestProgress` and `mediaSyncStatus` meanwhile.
const BACKGROUND_SYNC: &[&str] = &["klausSync", "klausFullSync"];

/// Anki SvelteKit routes, served from Anki's build (its client router takes over).
const ANKI_PAGES: &[&str] = &[
    "card-info",
    "change-notetype",
    "congrats",
    "deck-options",
    "editor",
    "graphs",
    "image-occlusion",
    "import-anki-package",
    "import-csv",
    "import-page",
    "preferences",
];

/// What the shell does when the webview fires a [`HOOKS`] call: method and protobuf
/// input in, optional protobuf reply out. Runs on a blocking thread, so it may show
/// native dialogs.
pub type Hook = Arc<dyn Fn(&str, &[u8]) -> Option<Vec<u8>> + Send + Sync>;

#[derive(Debug, PartialEq)]
pub enum CallError {
    UnknownMethod,
    NotAllowed,
    /// The backend's error message, as Anki's pages expect to display it.
    Backend(String),
}

pub struct Bridge {
    backend: Backend,
    /// The open Collection's directory.
    dir: Mutex<Option<PathBuf>>,
    /// Anki keeps profile settings (Qt's pm.meta and pm.profile) outside the
    /// Collection; Klaus has one profile, so both live in `klaus-settings.json`.
    settings: Mutex<Value>,
    /// Where the AnkiWeb sync key lives: the macOS Keychain in the app.
    secrets: Box<dyn Secrets>,
    /// The latest sync (page-started or automatic), for `klausSyncOutcome`.
    sync_outcome: Mutex<klaus::SyncOutcome>,
    /// klaus.ink, where the Klaus Account signs in (ADR-0007).
    account_url: Mutex<String>,
    /// This bridge's own origin, for the sign-in redirect back to it.
    origin: Mutex<Option<String>>,
    /// The sign-in in progress: (state, PKCE verifier, redirect URI).
    pending_sign_in: Mutex<Option<(String, String, String)>>,
    /// When the page last did something (Unix ms); automatic sync waits for quiet.
    last_activity: std::sync::atomic::AtomicI64,
}

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

const SYNC_KEY: &str = "klaus-account-sync-key";
const DEFAULT_ACCOUNT_URL: &str = "https://klaus.ink";
const DEFAULT_SYNC_URL: &str = "https://sync.klaus.ink/";
/// Automatic sync starts only after this long without page activity: a sync holds
/// the Collection for its network round-trip, which would stall reviewing.
const QUIET_MS: i64 = 30_000;

fn now_ms() -> i64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_millis() as i64)
}

impl Bridge {
    pub fn new() -> Result<Self, String> {
        Self::with_secrets(Box::new(MemorySecrets::default()))
    }

    pub fn with_secrets(secrets: Box<dyn Secrets>) -> Result<Self, String> {
        let init = BackendInit {
            preferred_langs: vec!["en".into()],
            ..Default::default()
        };
        Ok(Self {
            backend: init_backend(&init.encode_to_vec())?,
            dir: Mutex::new(None),
            settings: Mutex::new(Value::Null),
            secrets,
            sync_outcome: Mutex::default(),
            account_url: Mutex::new(
                std::env::var("KLAUS_ACCOUNT_URL").unwrap_or_else(|_| DEFAULT_ACCOUNT_URL.into()),
            ),
            origin: Mutex::new(None),
            pending_sign_in: Mutex::new(None),
            last_activity: std::sync::atomic::AtomicI64::new(0),
        })
    }

    /// Opens (creating if needed) the Collection stored in `dir`, using Anki's
    /// profile layout so the files are interchangeable with Anki desktop's.
    pub fn open_collection(&self, dir: &Path) -> Result<(), CallError> {
        // Anki's profile manager creates the media folder; media sync and adding
        // files fail without it.
        std::fs::create_dir_all(dir.join("collection.media")).map_err(|e| CallError::Backend(e.to_string()))?;
        let req = OpenCollectionRequest {
            collection_path: path_str(&dir.join("collection.anki2")),
            media_folder_path: path_str(&dir.join("collection.media")),
            media_db_path: path_str(&dir.join("collection.media.db2")),
        };
        self.run("openCollection", &req.encode_to_vec())?;
        let settings = std::fs::read(dir.join(SETTINGS_FILE))
            .ok()
            .and_then(|bytes| serde_json::from_slice(&bytes).ok())
            .unwrap_or_else(|| serde_json::json!({}));
        *self.settings.lock().unwrap() = settings;
        *self.dir.lock().unwrap() = Some(dir.to_owned());
        Ok(())
    }

    /// The open Collection's media folder.
    pub fn media_dir(&self) -> Option<PathBuf> {
        self.dir.lock().unwrap().as_ref().map(|d| d.join("collection.media"))
    }

    pub fn close_collection(&self) -> Result<(), CallError> {
        let req = CloseCollectionRequest { downgrade_to_schema11: false };
        self.run("closeCollection", &req.encode_to_vec()).map(drop)
    }

    /// For calls the shell itself decides to make (and tests); not reachable
    /// from the webview.
    pub fn call_trusted(&self, method: &str, input: &[u8]) -> Result<Vec<u8>, CallError> {
        self.run(method, input)
    }

    /// What the webview reaches: allowlisted methods only.
    pub fn call(&self, method: &str, input: &[u8]) -> Result<Vec<u8>, CallError> {
        if LOCAL.contains(&method) {
            return self.local(method, input);
        }
        if !METHODS.iter().any(|(name, ..)| *name == method) {
            return Err(CallError::UnknownMethod);
        }
        if !ALLOWED.contains(&method) {
            return Err(CallError::NotAllowed);
        }
        match self.run_raw(method, input) {
            // Like Anki's mediasrv: an unset config key is null, not an error.
            Err(Some(e)) if method == "getConfigJson" && e.kind() == backend_error::Kind::NotFoundError => {
                Ok(generic::Json { json: b"null".to_vec() }.encode_to_vec())
            }
            other => other.map_err(backend_call_error),
        }
    }

    fn run(&self, method: &str, input: &[u8]) -> Result<Vec<u8>, CallError> {
        self.run_raw(method, input).map_err(backend_call_error)
    }

    /// `Err(None)`: unknown method; `Err(Some(_))`: the backend's error.
    fn run_raw(&self, method: &str, input: &[u8]) -> Result<Vec<u8>, Option<BackendError>> {
        let (_, service, idx) = METHODS.iter().find(|(name, ..)| *name == method).ok_or(None)?;
        self.backend.run_service_method(*service, *idx, input).map_err(|bytes| {
            Some(BackendError::decode(bytes.as_slice()).unwrap_or_else(|_| BackendError {
                message: "unreadable backend error".into(),
                ..Default::default()
            }))
        })
    }

    fn local(&self, method: &str, input: &[u8]) -> Result<Vec<u8>, CallError> {
        let bad = |e: prost::DecodeError| CallError::Backend(e.to_string());
        let section = if method.contains("Meta") { "meta" } else { "profile" };
        match method {
            "klausRenderCard" => {
                let req = klaus::RenderCardRequest::decode(input).map_err(bad)?;
                Ok(self.render_card(req.card_id, req.typed_answer.as_deref())?.encode_to_vec())
            }
            "convertPastedImage" => {
                let req = ConvertPastedImageRequest::decode(input).map_err(bad)?;
                let data = convert_image(&req.data, &req.ext)
                    .ok_or_else(|| CallError::Backend("KlausNote can't read this image format.".into()))?;
                Ok(ConvertPastedImageResponse { data }.encode_to_vec())
            }
            "klausSyncAccount" => Ok(self.sync_account().encode_to_vec()),
            "klausAccountSignIn" => Ok(generic::String { val: self.account_sign_in_url()? }.encode_to_vec()),
            "klausSyncSignOut" => {
                self.sync_sign_out()?;
                Ok(vec![])
            }
            "klausSyncOutcome" => Ok(self.sync_outcome.lock().unwrap().encode_to_vec()),
            "getMetaJson" | "getProfileConfigJson" => {
                let key = generic::String::decode(input).map_err(bad)?.val;
                let settings = self.settings.lock().unwrap();
                let value = settings.get(section).and_then(|s| s.get(&key)).unwrap_or(&Value::Null);
                Ok(generic::Json { json: serde_json::to_vec(value).unwrap() }.encode_to_vec())
            }
            _ => {
                let req = SetSettingJsonRequest::decode(input).map_err(bad)?;
                let value: Value = serde_json::from_slice(&req.value_json)
                    .map_err(|e| CallError::Backend(e.to_string()))?;
                self.set_setting(section, &req.key, value)?;
                Ok(vec![])
            }
        }
    }

    fn set_setting(&self, section: &str, key: &str, value: Value) -> Result<(), CallError> {
        let mut settings = self.settings.lock().unwrap();
        settings[section][key] = value;
        let dir = self.dir.lock().unwrap().clone().ok_or_else(|| CallError::Backend("no Collection open".into()))?;
        std::fs::write(dir.join(SETTINGS_FILE), serde_json::to_vec_pretty(&*settings).unwrap())
            .map_err(|e| CallError::Backend(e.to_string()))
    }

    fn profile(&self, key: &str) -> Value {
        self.settings.lock().unwrap()["profile"][key].clone()
    }
}

// Collection sync through the Klaus Account (ADR-0007; contract in
// docs/klaus-ink-sync.md). The protocol is Anki's, so sync itself is aqt/sync.py's
// flow; profile keys match Anki's where it has them (syncUser, autoSync, syncMedia).
impl Bridge {
    pub fn sync_account(&self) -> klaus::SyncAccount {
        let flag = |key: &str| self.profile(key).as_bool().unwrap_or(true);
        let signed_in = self.secrets.get(SYNC_KEY).is_some();
        klaus::SyncAccount {
            email: if signed_in { self.profile("syncUser").as_str().unwrap_or_default().into() } else { String::new() },
            auto_sync: flag("autoSync"),
            sync_media: flag("syncMedia"),
        }
    }

    /// Where klaus.ink is (tests and staging point it elsewhere).
    pub fn set_account_url(&self, url: &str) {
        *self.account_url.lock().unwrap() = url.trim_end_matches('/').to_owned();
    }

    fn sync_auth(&self) -> Option<anki_proto::sync::SyncAuth> {
        let endpoint = self.profile("syncUrl").as_str().unwrap_or(DEFAULT_SYNC_URL).to_owned();
        Some(anki_proto::sync::SyncAuth { hkey: self.secrets.get(SYNC_KEY)?, endpoint: Some(endpoint), io_timeout_secs: None })
    }

    /// Starts a browser sign-in (OAuth 2.0 code flow with PKCE, RFC 8252 loopback
    /// redirect to this bridge): returns the klaus.ink URL the page opens.
    pub fn account_sign_in_url(&self) -> Result<String, CallError> {
        use base64::Engine;
        use rand::Rng;
        let origin = self.origin.lock().unwrap().clone().ok_or_else(|| CallError::Backend("bridge not serving".into()))?;
        let b64 = base64::engine::general_purpose::URL_SAFE_NO_PAD;
        let state = b64.encode(rand::rng().random::<[u8; 16]>());
        let verifier = b64.encode(rand::rng().random::<[u8; 32]>());
        let challenge = b64.encode(<sha2::Sha256 as sha2::Digest>::digest(verifier.as_bytes()));
        let redirect = format!("{origin}/auth/callback");
        let url = format!(
            "{}/oauth/authorize?response_type=code&client_id=klaus-desktop&redirect_uri={}&code_challenge={challenge}&code_challenge_method=S256&state={state}",
            self.account_url.lock().unwrap(),
            form_encode(&redirect),
        );
        *self.pending_sign_in.lock().unwrap() = Some((state, verifier, redirect));
        Ok(url)
    }

    /// klaus.ink's redirect back: checks the state (one-shot), exchanges the code
    /// for the account's sync key, and stores it.
    async fn finish_sign_in(&self, code: &str, state: &str) -> Result<String, String> {
        let pending = self.pending_sign_in.lock().unwrap().take();
        let Some((expected, verifier, redirect)) = pending.filter(|(expected, ..)| expected == state) else {
            return Err("This sign-in link has expired. Start again from KlausNote.".into());
        };
        let _ = expected;
        #[derive(serde::Deserialize)]
        struct Token {
            access_token: String,
            email: String,
            sync_url: Option<String>,
        }
        let url = format!("{}/oauth/token", self.account_url.lock().unwrap());
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
        self.secrets.set(SYNC_KEY, &token.access_token)?;
        let set = |key: &str, value: Value| self.set_setting("profile", key, value).map_err(|e| format!("{e:?}"));
        set("syncUser", token.email.clone().into())?;
        set("syncUrl", token.sync_url.map_or(Value::Null, Value::from))?;
        Ok(token.email)
    }

    /// pm.clear_sync_auth.
    pub fn sync_sign_out(&self) -> Result<(), CallError> {
        self.secrets.delete(SYNC_KEY).map_err(CallError::Backend)?;
        self.set_setting("profile", "syncUser", Value::Null)?;
        self.set_setting("profile", "syncUrl", Value::Null)
    }

    fn failed(err: Option<BackendError>) -> klaus::SyncOutcome {
        let err = err.unwrap_or_else(|| BackendError { message: "unknown sync method".into(), ..Default::default() });
        klaus::SyncOutcome {
            state: klaus::sync_outcome::State::Done as i32,
            error: err.message,
            error_kind: err.kind,
            ..Default::default()
        }
    }

    fn not_signed_in() -> klaus::SyncOutcome {
        Self::failed(Some(BackendError {
            message: "Sign in to your Klaus account to sync.".into(),
            kind: backend_error::Kind::SyncAuthError as i32,
            ..Default::default()
        }))
    }

    /// Like failed(), but a revoked sign-in also signs out (Anki's handle_sync_error).
    fn sync_failed(&self, err: Option<BackendError>) -> klaus::SyncOutcome {
        let outcome = Self::failed(err);
        if outcome.error_kind == backend_error::Kind::SyncAuthError as i32 {
            let _ = self.sync_sign_out();
        }
        outcome
    }

    /// A normal sync (and media sync in the background when enabled). Blocks.
    pub fn sync(&self) -> klaus::SyncOutcome {
        let Some(auth) = self.sync_auth() else { return Self::not_signed_in() };
        let req = anki_proto::sync::SyncCollectionRequest { auth: Some(auth), sync_media: self.sync_account().sync_media };
        match self.run_raw("syncCollection", &req.encode_to_vec()) {
            Err(err) => self.sync_failed(err),
            Ok(bytes) => {
                let out = anki_proto::sync::SyncCollectionResponse::decode(bytes.as_slice()).unwrap_or_default();
                if let Some(endpoint) = &out.new_endpoint {
                    let _ = self.set_setting("profile", "syncUrl", endpoint.as_str().into());
                }
                klaus::SyncOutcome {
                    state: klaus::sync_outcome::State::Done as i32,
                    required: out.required,
                    server_media_usn: out.server_media_usn,
                    server_message: out.server_message,
                    ..Default::default()
                }
            }
        }
    }

    /// Resolves a full sync. A download first backs the Collection up (Anki's
    /// create_backup_now), since it replaces everything here.
    pub fn full_sync(&self, upload: bool, server_media_usn: Option<i32>) -> klaus::SyncOutcome {
        let Some(auth) = self.sync_auth() else { return Self::not_signed_in() };
        let mut backup_folder = String::new();
        if !upload {
            let Some(dir) = self.dir.lock().unwrap().clone() else { return Self::failed(None) };
            if let Err(err) = std::fs::create_dir_all(dir.join("backups")) {
                return Self::failed(Some(BackendError { message: err.to_string(), ..Default::default() }));
            }
            let folder = path_str(&dir.join("backups"));
            let backup = anki_proto::collection::CreateBackupRequest { backup_folder: folder.clone(), force: true, wait_for_completion: true };
            if let Err(err) = self.run_raw("createBackup", &backup.encode_to_vec()) {
                return Self::failed(err);
            }
            backup_folder = folder;
        }
        let media_usn = server_media_usn.filter(|_| self.sync_account().sync_media);
        let req = anki_proto::sync::FullUploadOrDownloadRequest { auth: Some(auth), upload, server_usn: media_usn };
        match self.run_raw("fullUploadOrDownload", &req.encode_to_vec()) {
            Err(err) => self.sync_failed(err),
            Ok(_) => klaus::SyncOutcome { state: klaus::sync_outcome::State::Done as i32, backup_folder, ..Default::default() },
        }
    }

    /// Marks a sync as running (false if one already is), numbered for the page.
    fn begin_sync(&self, background: bool) -> Option<u32> {
        let mut outcome = self.sync_outcome.lock().unwrap();
        if outcome.state() == klaus::sync_outcome::State::Running {
            return None;
        }
        let id = outcome.id + 1;
        *outcome = klaus::SyncOutcome { state: klaus::sync_outcome::State::Running as i32, id, background, ..Default::default() };
        Some(id)
    }

    fn end_sync(&self, id: u32, background: bool, result: klaus::SyncOutcome) {
        *self.sync_outcome.lock().unwrap() = klaus::SyncOutcome { id, background, finished_ms: now_ms(), ..result };
    }

    pub fn sync_running(&self) -> bool {
        self.sync_outcome.lock().unwrap().state() == klaus::sync_outcome::State::Running
    }

    /// Starts klausSync / klausFullSync on its own thread and returns at once: a
    /// sync can take minutes, longer than a request should stay open.
    fn start_sync(self: &Arc<Self>, method: &str, input: &[u8]) -> Result<(), CallError> {
        let full = if method == "klausFullSync" {
            Some(klaus::FullSyncRequest::decode(input).map_err(|e| CallError::Backend(e.to_string()))?)
        } else {
            None
        };
        let id = self.begin_sync(false).ok_or_else(|| CallError::Backend("A sync is already running.".into()))?;
        let bridge = Arc::clone(self);
        std::thread::spawn(move || {
            let result = match full {
                Some(req) => bridge.full_sync(req.upload, req.server_media_usn),
                None => bridge.sync(),
            };
            bridge.end_sync(id, false, result);
        });
        Ok(())
    }

    /// Notes page activity; automatic sync waits for the app to be quiet.
    fn touch(&self) {
        self.last_activity.store(now_ms(), std::sync::atomic::Ordering::Relaxed);
    }

    /// One step of automatic sync, run about once a minute: when signed in, with
    /// auto sync on, nothing running, the page quiet, and Anki's syncStatus saying
    /// there's something to sync (local changes, checked for free; server changes,
    /// asked at most every 5 minutes). A full sync it finds is left for the page to
    /// ask about. Returns whether it synced.
    pub fn auto_sync_tick(&self) -> bool {
        let account = self.sync_account();
        let quiet = now_ms() - self.last_activity.load(std::sync::atomic::Ordering::Relaxed) >= QUIET_MS;
        let Some(auth) = self.sync_auth() else { return false };
        if account.email.is_empty() || !account.auto_sync || !quiet {
            return false;
        }
        let pending_full = {
            let outcome = self.sync_outcome.lock().unwrap();
            outcome.state() == klaus::sync_outcome::State::Done
                && outcome.error.is_empty()
                && outcome.required >= anki_proto::sync::sync_collection_response::ChangesRequired::FullSync as i32
        };
        let Ok(status) = self.rpc::<_, anki_proto::sync::SyncStatusResponse>("syncStatus", auth) else { return false };
        use anki_proto::sync::sync_status_response::Required;
        if status.required() == Required::NoChanges || (status.required() == Required::FullSync && pending_full) {
            return false;
        }
        let Some(id) = self.begin_sync(true) else { return false };
        let result = self.sync();
        self.end_sync(id, true, result);
        true
    }

    /// Syncs now on a background thread (on open, Anki's sync when the profile
    /// loads); the page sees it through klausSyncOutcome.
    pub fn sync_in_background(self: &Arc<Self>) {
        if self.sync_account().email.is_empty() {
            return;
        }
        let Some(id) = self.begin_sync(true) else { return };
        let bridge = Arc::clone(self);
        std::thread::spawn(move || {
            let result = bridge.sync();
            bridge.end_sync(id, true, result);
        });
    }

    /// Runs automatic sync for the life of the app.
    pub fn start_auto_sync(self: &Arc<Self>) {
        let bridge = Arc::clone(self);
        std::thread::spawn(move || loop {
            std::thread::sleep(std::time::Duration::from_secs(60));
            bridge.auto_sync_tick();
        });
    }

    /// Anki's sync on close: waits for a running sync, syncs, then waits for media
    /// sync, all within `limit`; past it, the sync in progress is aborted so
    /// quitting never hangs. A full sync is left for next time (it needs a choice).
    pub fn sync_before_quit(self: &Arc<Self>, limit: std::time::Duration) {
        use std::sync::atomic::{AtomicBool, Ordering};
        let deadline = std::time::Instant::now() + limit;
        let done = Arc::new(AtomicBool::new(false));
        let watchdog = {
            let (bridge, done) = (Arc::clone(self), Arc::clone(&done));
            std::thread::spawn(move || {
                while !done.load(Ordering::SeqCst) {
                    if std::time::Instant::now() >= deadline {
                        let _ = bridge.call_trusted("abortSync", &[]);
                        let _ = bridge.call_trusted("abortMediaSync", &[]);
                        return;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(100));
                }
            })
        };
        // Claim the sync slot, waiting out a sync already running (the watchdog
        // aborts it at the deadline).
        let id = loop {
            if let Some(id) = self.begin_sync(true) {
                break Some(id);
            }
            if std::time::Instant::now() >= deadline {
                break None;
            }
            std::thread::sleep(std::time::Duration::from_millis(200));
        };
        if let Some(id) = id {
            let result = self.sync();
            self.end_sync(id, true, result);
        }
        while std::time::Instant::now() < deadline && self.media_sync_active() {
            std::thread::sleep(std::time::Duration::from_millis(500));
        }
        done.store(true, Ordering::SeqCst);
        let _ = watchdog.join();
    }

    fn media_sync_active(&self) -> bool {
        self.rpc::<_, anki_proto::sync::MediaSyncStatusResponse>("mediaSyncStatus", anki_proto::generic::Empty {})
            .is_ok_and(|status| status.active)
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

impl Bridge {
    /// Calls a backend method with typed messages (shell/bridge-internal).
    fn rpc<I: Message, O: Message + Default>(&self, method: &str, input: I) -> Result<O, CallError> {
        let out = self.run(method, &input.encode_to_vec())?;
        O::decode(out.as_slice()).map_err(|e| CallError::Backend(e.to_string()))
    }

    /// A card's question and answer HTML as Anki's desktop reviewer shows it. Mirrors
    /// pylib's TemplateRenderContext.render (without add-on filters), the latex
    /// card_did_render hook, aqt's prepare_card_text_for_display, and the reviewer's
    /// type-answer filters. `typed`: the type-in answer, once revealed.
    fn render_card(&self, card_id: i64, typed: Option<&str>) -> Result<klaus::RenderCardResponse, CallError> {
        use anki_proto::card_rendering::{
            rendered_template_node::Value, CompareAnswerRequest, ExtractAvTagsRequest, ExtractAvTagsResponse,
            ExtractClozeForTypingRequest, ExtractLatexRequest, ExtractLatexResponse, RenderCardResponse,
            RenderExistingCardRequest, RenderedTemplateNode,
        };
        let rendered: RenderCardResponse = self.rpc(
            "renderExistingCard",
            RenderExistingCardRequest { card_id, browser: false, partial_render: true },
        )?;
        let join = |nodes: &[RenderedTemplateNode], front_side: Option<&str>| -> String {
            nodes
                .iter()
                .filter_map(|n| n.value.as_ref())
                .map(|v| match v {
                    Value::Text(t) => t.as_str(),
                    Value::Replacement(r) if r.field_name == "FrontSide" => front_side.unwrap_or(&r.current_text),
                    Value::Replacement(r) => &r.current_text,
                })
                .collect()
        };
        let av = |text: String, question_side: bool| -> Result<String, CallError> {
            let out: ExtractAvTagsResponse = self.rpc("extractAvTags", ExtractAvTagsRequest { text, question_side })?;
            Ok(out.text)
        };
        let question = av(join(&rendered.question_nodes, None), true)?;
        let answer = av(join(&rendered.answer_nodes, Some(&question)), false)?;

        let display = |text: String| -> Result<String, CallError> {
            let latex: ExtractLatexResponse =
                self.rpc("extractLatex", ExtractLatexRequest { text, svg: rendered.latex_svg, expand_clozes: false })?;
            let escaped: generic::String = self.rpc("encodeIriPaths", generic::String { val: latex.text })?;
            let hide_buttons: generic::Bool = self.rpc(
                "getConfigBool",
                anki_proto::config::GetConfigBoolRequest {
                    key: anki_proto::config::config_key::Bool::HideAudioPlayButtons as i32,
                },
            )?;
            Ok(play_buttons(&escaped.val, hide_buttons.val))
        };
        let (question, answer) = (display(question)?, display(answer)?);

        // Type-in answers (aqt/reviewer.py typeAnsQuestionFilter / typeAnsAnswerFilter).
        let type_re = regex::Regex::new(r"\[\[type:(.+?)\]\]").unwrap();
        let Some(spec) = type_re.captures(&question).map(|c| c[1].to_string()) else {
            return Ok(klaus::RenderCardResponse { question: css(&rendered.css, question), answer: css(&rendered.css, answer) });
        };
        let card: anki_proto::cards::Card = self.rpc("getCard", anki_proto::cards::CardId { cid: card_id })?;
        let note: anki_proto::notes::Note = self.rpc("getNote", anki_proto::notes::NoteId { nid: card.note_id })?;
        let notetype: anki_proto::notetypes::Notetype =
            self.rpc("getNotetype", anki_proto::notetypes::NotetypeId { ntid: note.notetype_id })?;
        let mut field = spec.as_str();
        let cloze = field.strip_prefix("cloze:").inspect(|f| field = f).is_some();
        let combining = field.strip_prefix("nc:").inspect(|f| field = f).is_none();
        let found = notetype.fields.iter().zip(&note.fields).find(|(f, _)| f.name == field);
        let mut expected = found.map(|(_, text)| text.clone());
        if cloze {
            if let Some(text) = expected.take() {
                let out: generic::String = self.rpc(
                    "extractClozeForTyping",
                    ExtractClozeForTypingRequest { text, ordinal: card.template_idx + 1 },
                )?;
                expected = Some(out.val).filter(|v| !v.is_empty());
            }
        }
        let (font, size) = found
            .and_then(|(f, _)| f.config.as_ref())
            .map(|c| (c.font_name.clone(), c.font_size))
            .unwrap_or_default();
        let question = match &expected {
            None if cloze => type_re.replace_all(&question, "Please run Tools>Empty Cards").into_owned(),
            None => type_re.replace_all(&question, format!("Type answer: unknown field {field}")).into_owned(),
            Some(e) if e.is_empty() => type_re.replace_all(&question, "").into_owned(),
            Some(_) => type_re
                .replace_all(
                    &question,
                    format!(
                        "\n<center>\n<input type=text id=typeans onkeypress=\"_typeAnsPress();\"\n   style=\"font-family: '{font}'; font-size: {size}px;\">\n</center>\n"
                    ),
                )
                .into_owned(),
        };
        let answer = match (expected.filter(|e| !e.is_empty()), typed) {
            (Some(expected), Some(provided)) => {
                let without_hr = answer.replace("<hr id=answer>", "");
                let had_hr = without_hr.len() != answer.len();
                if had_hr && !type_re.is_match(&without_hr) {
                    answer
                } else {
                    let compared: generic::String = self.rpc(
                        "compareAnswer",
                        CompareAnswerRequest { expected, provided: provided.into(), combining },
                    )?;
                    let hr = if had_hr { "<hr id=answer>" } else { "" };
                    let div = format!("{hr}\n<div style=\"font-family: '{font}'; font-size: {size}px\">{}</div>", compared.val);
                    type_re.replace_all(&without_hr, regex::NoExpand(&div)).into_owned()
                }
            }
            _ => type_re.replace_all(&answer, "").into_owned(),
        };
        Ok(klaus::RenderCardResponse { question: css(&rendered.css, question), answer: css(&rendered.css, answer) })
    }
}

/// pylib TemplateRenderOutput.question_and_style.
fn css(css: &str, html: String) -> String {
    format!("<style>{css}</style>{html}")
}

/// aqt.sound.av_refs_to_play_icons (or strip_av_refs when play buttons are hidden).
fn play_buttons(text: &str, hide: bool) -> String {
    let av_ref = regex::Regex::new(r"\[anki:(play:(.):(\d+))\]").unwrap();
    av_ref
        .replace_all(text, |c: &regex::Captures| {
            if hide {
                return String::new();
            }
            format!(
                r#"
<a class="replay-button soundLink" href=# onclick="pycmd('{}'); return false;" draggable="false">
    <svg class="playImage" viewBox="0 0 64 64" version="1.1">
        <circle cx="32" cy="32" r="29" />
        <path d="M56.502,32.301l-37.502,20.101l0.329,-40.804l37.173,20.703Z" />
    </svg>
</a>"#,
                &c[1]
            )
        })
        .into_owned()
}

const SETTINGS_FILE: &str = "klaus-settings.json";

/// Largest `/_anki` request body: big media pasted or dropped into the editor.
const MAX_BODY: usize = 256 * 1024 * 1024;

/// Re-encodes a pasted image as the format the editor named it with (`png` or `jpg`),
/// as Anki's Qt host does, so a file's bytes always match its extension. None if the
/// input can't be decoded: better to refuse the paste than store mismatched bytes.
fn convert_image(data: &[u8], ext: &str) -> Option<Vec<u8>> {
    use image::codecs::jpeg::JpegEncoder;
    let img = image::load_from_memory(data).ok()?;
    let mut out = Vec::new();
    if ext == "png" {
        img.write_to(&mut std::io::Cursor::new(&mut out), image::ImageFormat::Png).ok()?;
    } else {
        // Same quality Anki uses for jpg; JPEG has no alpha.
        img.to_rgb8().write_with_encoder(JpegEncoder::new_with_quality(&mut out, 80)).ok()?;
    }
    Some(out)
}

fn backend_call_error(err: Option<BackendError>) -> CallError {
    match err {
        None => CallError::UnknownMethod,
        Some(e) => CallError::Backend(e.message),
    }
}

impl Drop for Bridge {
    fn drop(&mut self) {
        // Flush and close cleanly; harmless if no Collection is open.
        let _ = self.close_collection();
    }
}

fn path_str(p: &Path) -> String {
    p.to_string_lossy().into_owned()
}

/// A fresh per-launch secret. The webview is opened at `/?t=<token>`, which sets an
/// HttpOnly cookie and redirects to a token-free URL (so page scripts never see the
/// token); `/_anki` calls without the cookie are refused, so other local processes,
/// web pages and card JS can't drive the Collection.
pub fn new_token() -> String {
    use rand::Rng;
    let bytes: [u8; 16] = rand::rng().random();
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

#[derive(Clone)]
struct AppState {
    bridge: Arc<Bridge>,
    token: Arc<str>,
    /// `klaus_<port>=<token>`. Cookies aren't scoped by port, so the name carries it:
    /// two running instances must not overwrite each other's cookie.
    cookie: Arc<str>,
    hook: Hook,
    anki_dir: Arc<PathBuf>,
    /// `http://127.0.0.1:<port>`, for path-scoped CSP sources.
    origin: Arc<str>,
}

/// Where the two frontends live on disk.
pub struct WebDirs {
    /// Klaus's SvelteKit build (SPA fallback to its index.html).
    pub klaus: PathBuf,
    /// Anki's SvelteKit build (`vendor/anki/out/sveltekit`).
    pub anki: PathBuf,
    /// Anki's reviewer assets and MathJax (`vendor/anki/out/klaus`), served at
    /// `/_anki/js` and `/_anki/css` as Anki's Qt app serves its web folder.
    pub anki_static: PathBuf,
}

/// Binds 127.0.0.1 on a free port and returns the address plus the server future.
pub async fn serve(
    bridge: Arc<Bridge>,
    web: WebDirs,
    token: String,
    hook: Hook,
) -> std::io::Result<(SocketAddr, impl std::future::Future<Output = std::io::Result<()>>)> {
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0)).await?;
    let addr = listener.local_addr()?;
    let cookie = format!("klaus_{}={token}", addr.port()).into();
    let origin: Arc<str> = format!("http://127.0.0.1:{}", addr.port()).into();
    *bridge.origin.lock().unwrap() = Some(origin.to_string());
    let state = AppState { bridge, token: token.into(), cookie, hook, anki_dir: web.anki.clone().into(), origin };
    let klaus = ServeDir::new(&web.klaus).fallback(ServeFile::new(web.klaus.join("index.html")));
    let klaus_dir: Arc<PathBuf> = web.klaus.clone().into();
    let mut app = Router::new()
        // Axum's default 2 MiB cap would reject pasted photos (convertPastedImage,
        // addMediaFile carry the bytes); the caller is already cookie-authenticated.
        .route("/_anki/{method}", post(anki_method).layer(DefaultBodyLimit::max(MAX_BODY)))
        // klaus.ink's sign-in redirect, from the system browser: no session cookie
        // there, the one-shot OAuth state is the check.
        .route("/auth/callback", get(auth_callback))
        .nest_service("/_app", ServeDir::new(web.anki.join("_app")))
        .merge(anki_static(&web.anki_static));
    for page in ANKI_PAGES {
        let page_route = get(move |state: State<AppState>| anki_page(state, page));
        app = app
            .route(&format!("/{page}"), page_route.clone())
            .route(&format!("/{page}/"), page_route)
            .route(
                &format!("/{page}/{{*rest}}"),
                get(move |state: State<AppState>, rest: UrlPath<(String,)>, req: Request| {
                    anki_page_or_media(state, rest, req, page)
                }),
            );
    }
    let app = app
        .fallback(move |state: State<AppState>, req: Request| root_or_media(state, req, klaus.clone(), klaus_dir.clone()))
        .layer(middleware::from_fn_with_state(state.clone(), grant_cookie))
        .with_state(state);
    Ok((addr, async move { axum::serve(listener, app).await }))
}

/// Static reviewer assets. Cards render in a sandboxed (opaque-origin) frame, so
/// every load from it is cross-origin; MathJax's fonts are CORS-gated, hence the
/// header. Static files only: `/_anki/<method>` calls must stay unreachable from cards.
fn anki_static(dir: &Path) -> Router<AppState> {
    Router::new()
        .nest_service("/_anki/js", ServeDir::new(dir.join("_anki/js")))
        .nest_service("/_anki/css", ServeDir::new(dir.join("_anki/css")))
        .layer(axum::middleware::map_response(|mut res: Response| async move {
            res.headers_mut().insert(header::ACCESS_CONTROL_ALLOW_ORIGIN, "*".parse().unwrap());
            res
        }))
}

/// aqt/mediasrv.py UNTRUSTED_MEDIA_CSP, verbatim.
const UNTRUSTED_MEDIA_CSP: &str = "default-src 'none'; script-src 'none'; connect-src 'none'; \
    object-src 'none'; frame-src 'none'; child-src 'none'; base-uri 'none'; form-action 'none'; \
    style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; media-src 'self'; \
    sandbox allow-same-origin";

/// Anki's SvelteKit shell, with what Anki's Qt webview would provide: the host
/// script (`bridgeCommand`) before any page script runs, and base styling. Sent with
/// the response CSP Anki's mediasrv sends in place of the build's meta tag: the
/// pages that show note HTML (editor, image-occlusion) only run Anki's and Klaus's
/// own scripts and can't submit forms. Pages are never framed by other origins; the
/// editor may be framed by Klaus's own pages (the browser's side editor).
async fn anki_page(State(state): State<AppState>, page: &'static str) -> Response {
    let Ok(html) = tokio::fs::read_to_string(state.anki_dir.join("index.html")).await else {
        return StatusCode::NOT_FOUND.into_response();
    };
    // SvelteKit's `<meta http-equiv="content-security-policy" content="script-src 'self' 'sha256-…'">`.
    const META: &str = r#"<meta http-equiv="content-security-policy" content="script-src 'self' "#;
    let mut hash = String::new();
    let mut html = html;
    if let Some(start) = html.find(META) {
        if let Some(len) = html[start..].find('>') {
            hash = html[start + META.len()..start + len].trim_end_matches('"').to_owned();
            html.replace_range(start..=start + len, "");
        }
    }
    let html = html.replacen(
        "<head>",
        r#"<head><link rel="stylesheet" href="/anki-host.css"><script src="/native-dialogs.js"></script><script src="/anki-host.js"></script>"#,
        1,
    );
    // Only Klaus's same-origin pages can frame the editor: the card frame is an
    // opaque origin and media is sandboxed, so neither matches 'self'.
    let ancestors = if page == "editor" { "'self'" } else { "'none'" };
    let csp = if matches!(page, "editor" | "image-occlusion") {
        let o = &state.origin;
        format!("script-src {o}/_anki/ {o}/_app/ {o}/native-dialogs.js {o}/anki-host.js {hash}; form-action 'none'; frame-ancestors {ancestors}")
    } else {
        format!("frame-ancestors {ancestors}")
    };
    ([(header::CONTENT_SECURITY_POLICY, csp)], Html(html)).into_response()
}

/// Anki pages load media by relative URL (`<img src="foo.png">`), which resolves to
/// `/editor/foo.png` or `/foo.png` depending on the page URL's trailing slash, so a
/// bare filename there is served from the Collection's media folder.
async fn media(state: &AppState, name: &str, req: Request) -> Result<Response, Request> {
    let plain_name = !name.is_empty() && !name.contains(['/', '\\']) && name != "..";
    let Some(file) = plain_name.then(|| state.bridge.media_dir()).flatten().map(|d| d.join(name)) else {
        return Err(req);
    };
    if !file.is_file() {
        return Err(req);
    }
    let mut res = ServeFile::new(file).oneshot(req).await.into_response();
    // As Anki does for media: never run user-provided HTML/SVG as a document.
    res.headers_mut()
        .insert(header::CONTENT_SECURITY_POLICY, HeaderValue::from_static(UNTRUSTED_MEDIA_CSP));
    Ok(res)
}

async fn anki_page_or_media(
    State(state): State<AppState>,
    UrlPath((rest,)): UrlPath<(String,)>,
    req: Request,
    page: &'static str,
) -> Response {
    match media(&state, &rest, req).await {
        Ok(res) => res,
        Err(_) => anki_page(State(state), page).await,
    }
}

/// Klaus's own files first (a deck's media must never shadow, say, anki-host.js),
/// then media files at the root, else Klaus's SPA.
async fn root_or_media(
    State(state): State<AppState>,
    req: Request,
    klaus: ServeDir<ServeFile>,
    klaus_dir: Arc<PathBuf>,
) -> Response {
    let name = percent_decode(req.uri().path().trim_start_matches('/'));
    if name.is_empty() || klaus_dir.join(&name).is_file() {
        return klaus.oneshot(req).await.into_response();
    }
    match media(&state, &name, req).await {
        Ok(res) => res,
        Err(req) => klaus.oneshot(req).await.into_response(),
    }
}

fn percent_decode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        let hex = bytes.get(i + 1..i + 3).and_then(|h| u8::from_str_radix(std::str::from_utf8(h).ok()?, 16).ok());
        match (bytes[i], hex) {
            (b'%', Some(b)) => {
                out.push(b);
                i += 3;
            }
            (b, _) => {
                out.push(b);
                i += 1;
            }
        }
    }
    String::from_utf8_lossy(&out).into_owned()
}

async fn grant_cookie(State(state): State<AppState>, req: Request, next: Next) -> Response {
    let grant = req
        .uri()
        .query()
        .is_some_and(|q| q.split('&').any(|kv| kv == format!("t={}", state.token)));
    if !grant {
        return next.run(req).await;
    }
    let cookie = format!("{}; HttpOnly; SameSite=Strict; Path=/", state.cookie);
    // Same URL without the token (other query parameters, e.g. ?deck=, kept).
    let token_param = format!("t={}", state.token);
    let rest: Vec<&str> = req.uri().query().unwrap_or_default().split('&').filter(|kv| *kv != token_param).collect();
    let location = match rest.join("&") {
        q if q.is_empty() => req.uri().path().to_owned(),
        q => format!("{}?{q}", req.uri().path()),
    };
    (StatusCode::SEE_OTHER, [(header::SET_COOKIE, cookie), (header::LOCATION, location)]).into_response()
}

/// aqt/mediasrv.py update_deck_configs. A save can take minutes (FSRS recomputes
/// memory states; "Optimize all presets" fits every preset), longer than a request
/// should stay open, so reply at once and save in the background. Then, as in Anki,
/// the page closes (`deckOptionsRequireClose`) unless it was an optimise-all, which
/// reloads itself; a failure is shown with `showMessageBox`.
fn save_deck_configs(state: AppState, body: Bytes) -> Response {
    use anki_proto::deck_config::{UpdateDeckConfigsMode, UpdateDeckConfigsRequest};
    let Ok(req) = UpdateDeckConfigsRequest::decode(body.as_ref()) else {
        return (StatusCode::INTERNAL_SERVER_ERROR, "invalid updateDeckConfigs request").into_response();
    };
    let compute_all = req.mode() == UpdateDeckConfigsMode::ComputeAllParams;
    // ponytail: no progress window during the save (Anki shows one); the page's own
    // Optimize button has progress. Add an overlay polling latestProgress if saves drag.
    tokio::task::spawn_blocking(move || match state.bridge.call_trusted("updateDeckConfigs", &body) {
        Ok(_) if !compute_all => {
            (state.hook)("deckOptionsRequireClose", &[]);
        }
        Ok(_) => {}
        Err(err) => {
            let text = match err {
                CallError::Backend(msg) => msg,
                other => format!("{other:?}"),
            };
            let msg = frontend::ShowMessageBoxRequest { text, r#type: 2, title: None };
            (state.hook)("showMessageBox", &msg.encode_to_vec());
        }
    });
    StatusCode::NO_CONTENT.into_response()
}

#[derive(serde::Deserialize)]
struct CallbackQuery {
    code: Option<String>,
    state: Option<String>,
    error: Option<String>,
}

async fn auth_callback(State(state): State<AppState>, Query(query): Query<CallbackQuery>) -> Response {
    let result = match (query.code, query.state, query.error) {
        (Some(code), Some(oauth_state), None) => state.bridge.finish_sign_in(&code, &oauth_state).await,
        (_, _, Some(_)) => Err("Sign-in was cancelled.".into()),
        _ => Err("This sign-in link is incomplete.".into()),
    };
    let (status, title, detail) = match result {
        Ok(email) => (StatusCode::OK, "Signed in to KlausNote".to_owned(), format!("Signed in as {email}. You can close this tab and return to KlausNote.")),
        Err(err) => (StatusCode::BAD_REQUEST, "Couldn't sign in".to_owned(), err),
    };
    let escape = |s: &str| s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;");
    let page = format!(
        "<!doctype html><meta charset=utf-8><title>{t}</title><meta name=color-scheme content=\"light dark\">\
         <body style=\"font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem\"><h1>{t}</h1><p>{d}</p>",
        t = escape(&title),
        d = escape(&detail)
    );
    (status, Html(page)).into_response()
}

async fn anki_method(
    State(state): State<AppState>,
    UrlPath(method): UrlPath<String>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    let has_token = headers
        .get_all(header::COOKIE)
        .iter()
        .filter_map(|v| v.to_str().ok())
        .flat_map(|v| v.split(';'))
        .any(|c| c.trim() == &*state.cookie);
    // Same check as Anki's mediasrv: forces a CORS preflight for cross-origin callers.
    let binary = headers.get(header::CONTENT_TYPE).is_some_and(|v| v == "application/binary");
    if !has_token || !binary {
        return StatusCode::FORBIDDEN.into_response();
    }
    if HOOKS.contains(&method.as_str()) {
        let hook = state.hook.clone();
        return match tokio::task::spawn_blocking(move || hook(&method, &body)).await {
            Ok(Some(out)) if !out.is_empty() => ([(header::CONTENT_TYPE, "application/binary")], out).into_response(),
            Ok(_) => StatusCode::NO_CONTENT.into_response(),
            Err(join) => (StatusCode::INTERNAL_SERVER_ERROR, join.to_string()).into_response(),
        };
    }
    if method == "updateDeckConfigs" {
        return save_deck_configs(state, body);
    }
    // Polls don't count as activity, or the app would never look quiet to auto sync.
    if !matches!(method.as_str(), "klausSyncOutcome" | "latestProgress" | "mediaSyncStatus" | "klausSyncAccount") {
        state.bridge.touch();
    }
    if BACKGROUND_SYNC.contains(&method.as_str()) {
        return match state.bridge.start_sync(&method, &body) {
            Ok(()) => StatusCode::NO_CONTENT.into_response(),
            Err(CallError::Backend(msg)) => (StatusCode::INTERNAL_SERVER_ERROR, msg).into_response(),
            Err(_) => StatusCode::NOT_FOUND.into_response(),
        };
    }
    let bridge = state.bridge.clone();
    let result = tokio::task::spawn_blocking(move || bridge.call(&method, &body)).await;
    match result {
        Ok(Ok(out)) if out.is_empty() => StatusCode::NO_CONTENT.into_response(),
        Ok(Ok(out)) => ([(header::CONTENT_TYPE, "application/binary")], out).into_response(),
        Ok(Err(CallError::UnknownMethod)) => StatusCode::NOT_FOUND.into_response(),
        Ok(Err(CallError::NotAllowed)) => StatusCode::FORBIDDEN.into_response(),
        Ok(Err(CallError::Backend(msg))) => (StatusCode::INTERNAL_SERVER_ERROR, msg).into_response(),
        Err(join) => (StatusCode::INTERNAL_SERVER_ERROR, join.to_string()).into_response(),
    }
}
