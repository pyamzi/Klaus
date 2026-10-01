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
use axum::extract::{DefaultBodyLimit, Path as UrlPath, Request, State};
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
    // A mediasrv post handler in Anki (missing keys read as null); see Bridge::call.
    "getConfigJson",
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
];

/// Anki host calls that are pure data, answered by the bridge itself.
const LOCAL: &[&str] = &[
    "getMetaJson",
    "setMetaJson",
    "getProfileConfigJson",
    "setProfileConfigJson",
    "convertPastedImage",
];

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
}

impl Bridge {
    pub fn new() -> Result<Self, String> {
        let init = BackendInit {
            preferred_langs: vec!["en".into()],
            ..Default::default()
        };
        Ok(Self {
            backend: init_backend(&init.encode_to_vec())?,
            dir: Mutex::new(None),
            settings: Mutex::new(Value::Null),
        })
    }

    /// Opens (creating if needed) the Collection stored in `dir`, using Anki's
    /// profile layout so the files are interchangeable with Anki desktop's.
    pub fn open_collection(&self, dir: &Path) -> Result<(), CallError> {
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
            "convertPastedImage" => {
                let req = ConvertPastedImageRequest::decode(input).map_err(bad)?;
                let data = convert_image(&req.data, &req.ext)
                    .ok_or_else(|| CallError::Backend("Klaus can't read this image format.".into()))?;
                Ok(ConvertPastedImageResponse { data }.encode_to_vec())
            }
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
                let mut settings = self.settings.lock().unwrap();
                settings[section][req.key] = value;
                let dir = self.dir.lock().unwrap().clone().ok_or_else(|| CallError::Backend("no Collection open".into()))?;
                std::fs::write(dir.join(SETTINGS_FILE), serde_json::to_vec_pretty(&*settings).unwrap())
                    .map_err(|e| CallError::Backend(e.to_string()))?;
                Ok(vec![])
            }
        }
    }
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
    let origin = format!("http://127.0.0.1:{}", addr.port()).into();
    let state = AppState { bridge, token: token.into(), cookie, hook, anki_dir: web.anki.clone().into(), origin };
    let klaus = ServeDir::new(&web.klaus).fallback(ServeFile::new(web.klaus.join("index.html")));
    let klaus_dir: Arc<PathBuf> = web.klaus.clone().into();
    let mut app = Router::new()
        // Axum's default 2 MiB cap would reject pasted photos (convertPastedImage,
        // addMediaFile carry the bytes); the caller is already cookie-authenticated.
        .route("/_anki/{method}", post(anki_method).layer(DefaultBodyLimit::max(MAX_BODY)))
        .nest_service("/_app", ServeDir::new(web.anki.join("_app")));
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

/// Anki's SvelteKit shell, with what Anki's Qt webview would provide: the host
/// script (`bridgeCommand`) before any page script runs, and base styling.
/// aqt/mediasrv.py UNTRUSTED_MEDIA_CSP, verbatim.
const UNTRUSTED_MEDIA_CSP: &str = "default-src 'none'; script-src 'none'; connect-src 'none'; \
    object-src 'none'; frame-src 'none'; child-src 'none'; base-uri 'none'; form-action 'none'; \
    style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; media-src 'self'; \
    sandbox allow-same-origin";

/// Serves an Anki page shell with Klaus's host script, and the response CSP Anki's
/// mediasrv sends in place of the build's meta tag: pages are never framed, and the
/// pages that show note HTML (editor, image-occlusion) only run Anki's and Klaus's
/// own scripts and can't submit forms.
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
        r#"<head><link rel="stylesheet" href="/anki-host.css"><script src="/anki-host.js"></script>"#,
        1,
    );
    let csp = if matches!(page, "editor" | "image-occlusion") {
        let o = &state.origin;
        format!("script-src {o}/_anki/ {o}/_app/ {o}/anki-host.js {hash}; form-action 'none'; frame-ancestors 'none'")
    } else {
        "frame-ancestors 'none'".to_owned()
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
    let location = req.uri().path().to_owned();
    (StatusCode::SEE_OTHER, [(header::SET_COOKIE, cookie), (header::LOCATION, location)]).into_response()
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
