//! The Backend Bridge: the one seam between Klaus's webview and Anki's rslib.
//!
//! It speaks the contract Anki's generated TypeScript client already uses
//! (`POST /_anki/<camelCaseMethod>`, protobuf bytes in and out), so Anki's own
//! pages and client run unmodified.

use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use anki::backend::{init_backend, Backend};
use anki_proto::backend::{BackendError, BackendInit};
use anki_proto::collection::{CloseCollectionRequest, OpenCollectionRequest};
use axum::body::Bytes;
use axum::extract::{Path as UrlPath, Request, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use axum::Router;
use prost::Message;
use tower_http::services::{ServeDir, ServeFile};

include!(concat!(env!("OUT_DIR"), "/methods.rs"));

/// Methods the webview may call. Anki's mediasrv allowlist plus what Klaus's own
/// screens need; grow it per feature. Card HTML can carry arbitrary JS, so the
/// webview never gets the whole backend.
const ALLOWED: &[&str] = &[
    "deckTree",
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
/// Klaus's own. Each is acknowledged with 204 and handed to the shell's hook.
const HOOKS: &[&str] = &[
    "importDone",
    "importDialogRequireClose",
    "searchInBrowser",
    "klausImportPackage",
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

/// What the shell does when the webview fires a [`HOOKS`] call.
pub type Hook = Arc<dyn Fn(&str, &[u8]) + Send + Sync>;

#[derive(Debug, PartialEq)]
pub enum CallError {
    UnknownMethod,
    NotAllowed,
    /// The backend's error message, as Anki's pages expect to display it.
    Backend(String),
}

pub struct Bridge {
    backend: Backend,
}

impl Bridge {
    pub fn new() -> Result<Self, String> {
        let init = BackendInit {
            preferred_langs: vec!["en".into()],
            ..Default::default()
        };
        Ok(Self { backend: init_backend(&init.encode_to_vec())? })
    }

    /// Opens (creating if needed) the Collection stored in `dir`, using Anki's
    /// profile layout so the files are interchangeable with Anki desktop's.
    pub fn open_collection(&self, dir: &Path) -> Result<(), CallError> {
        let req = OpenCollectionRequest {
            collection_path: path_str(&dir.join("collection.anki2")),
            media_folder_path: path_str(&dir.join("collection.media")),
            media_db_path: path_str(&dir.join("collection.media.db2")),
        };
        self.run("openCollection", &req.encode_to_vec()).map(drop)
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
        if !METHODS.iter().any(|(name, ..)| *name == method) {
            return Err(CallError::UnknownMethod);
        }
        if !ALLOWED.contains(&method) {
            return Err(CallError::NotAllowed);
        }
        self.run(method, input)
    }

    fn run(&self, method: &str, input: &[u8]) -> Result<Vec<u8>, CallError> {
        let (_, service, idx) = METHODS
            .iter()
            .find(|(name, ..)| *name == method)
            .ok_or(CallError::UnknownMethod)?;
        self.backend
            .run_service_method(*service, *idx, input)
            .map_err(|bytes| {
                CallError::Backend(
                    BackendError::decode(bytes.as_slice())
                        .map(|e| e.message)
                        .unwrap_or_else(|_| "unreadable backend error".into()),
                )
            })
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
    let state = AppState { bridge, token: token.into(), cookie, hook };
    let klaus = ServeDir::new(&web.klaus).fallback(ServeFile::new(web.klaus.join("index.html")));
    let mut app = Router::new()
        .route("/_anki/{method}", post(anki_method))
        .nest_service("/_app", ServeDir::new(web.anki.join("_app")));
    let anki_index = ServeFile::new(web.anki.join("index.html"));
    for page in ANKI_PAGES {
        app = app
            .route_service(&format!("/{page}"), anki_index.clone())
            .route_service(&format!("/{page}/{{*rest}}"), anki_index.clone());
    }
    let app = app
        .fallback_service(klaus)
        .layer(middleware::from_fn_with_state(state.clone(), grant_cookie))
        .with_state(state);
    Ok((addr, async move { axum::serve(listener, app).await }))
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
        tokio::task::spawn_blocking(move || hook(&method, &body));
        return StatusCode::NO_CONTENT.into_response();
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
