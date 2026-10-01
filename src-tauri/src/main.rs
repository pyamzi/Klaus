// Prevents an extra console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Arc;

use anki_proto::generic;
use klaus_bridge::frontend::{AskUserRequest, OpenFilePickerRequest, ShowMessageBoxRequest};
use klaus_bridge::{new_token, serve, Bridge, Hook, WebDirs};
use prost::Message;
use tauri::{AppHandle, Manager, RunEvent, Theme, Url, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let dir = app.path().app_data_dir()?;
            // Dev only: a scratch Collection (e.g. a test fixture) instead of the real one.
            #[cfg(debug_assertions)]
            let dir = std::env::var_os("KLAUS_DATA_DIR").map(std::path::PathBuf::from).unwrap_or(dir);
            std::fs::create_dir_all(&dir)?;
            let bridge = Arc::new(Bridge::new()?);
            bridge.open_collection(&dir).map_err(|e| format!("could not open Collection: {e:?}"))?;
            app.manage(bridge.clone());

            // Both frontends are served by the bridge (same origin as /_anki), not
            // Tauri's asset protocol, because Anki's client fetches root-relative URLs.
            let res = app.path().resource_dir()?;
            let web = WebDirs { klaus: res.join("web"), anki: res.join("anki-web"), anki_static: res.join("anki-static") };
            let token = new_token();
            let handle = app.handle().clone();
            let hook: Hook = Arc::new(move |method: &str, input: &[u8]| on_hook(&handle, method, input));
            let (addr, server) = tauri::async_runtime::block_on(serve(bridge, web, token.clone(), hook))?;
            tauri::async_runtime::spawn(server);
            println!("Klaus bridge listening on {addr}");

            let base: Url = format!("http://{addr}/").parse()?;
            app.manage(base.clone());
            let mut url = base.clone();
            // Dev only: open a page directly (e.g. KLAUS_OPEN="review?deck=1").
            #[cfg(debug_assertions)]
            if let Ok(open) = std::env::var("KLAUS_OPEN") {
                url = base.join(&open)?;
            }
            let query = url.query().map(|q| format!("{q}&")).unwrap_or_default();
            url.set_query(Some(&format!("{query}t={token}")));
            // Lets a dev browser drive the same pages; never in release builds.
            #[cfg(debug_assertions)]
            println!("Klaus dev URL: {url}");
            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                .title("Klaus")
                .inner_size(1100.0, 750.0)
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Klaus");

    app.run(|app, event| {
        if let RunEvent::Exit = event {
            let _ = app.state::<Arc<Bridge>>().close_collection();
        }
    });
}

/// Requests the webview makes to its host (see klaus_bridge::HOOKS); the reply is
/// the protobuf the page expects, or None for an empty one.
fn on_hook(app: &AppHandle, method: &str, input: &[u8]) -> Option<Vec<u8>> {
    match method {
        "klausImportPackage" => {
            let picked = app.dialog().file().add_filter("Anki deck package", &["apkg"]).blocking_pick_file();
            if let Some(path) = picked.and_then(|p| p.into_path().ok()) {
                // Same URL shape as Anki's import dialog: <page>/<quoted path>.
                navigate(app, &format!("import-anki-package/{}", quote(&path.to_string_lossy())));
            }
            None
        }
        // The import page's Close button, and deck options after a save or a
        // confirmed discard; the deck list reloads its counts.
        "importDialogRequireClose" | "deckOptionsRequireClose" => {
            navigate(app, "");
            None
        }
        // The editor's Close; `true` means fields have content (Anki asks before discarding).
        "closeAddCards" => {
            let has_input = generic::Bool::decode(input).ok()?.val;
            if !has_input || confirm(app, "Discard current input?", None, MessageDialogKind::Warning) {
                navigate(app, "");
            }
            None
        }
        "askUser" => {
            let req = AskUserRequest::decode(input).ok()?;
            let yes = confirm(app, &req.text, req.title.as_deref(), MessageDialogKind::Info);
            Some(generic::Bool { val: yes }.encode_to_vec())
        }
        "showMessageBox" => {
            let req = ShowMessageBoxRequest::decode(input).ok()?;
            let kind = match req.r#type {
                1 => MessageDialogKind::Warning,
                2 => MessageDialogKind::Error,
                _ => MessageDialogKind::Info,
            };
            let mut dialog = app.dialog().message(req.text).kind(kind);
            if let Some(title) = req.title {
                dialog = dialog.title(title);
            }
            dialog.blocking_show();
            None
        }
        "openFilePicker" => {
            let req = OpenFilePickerRequest::decode(input).ok()?;
            let extensions: Vec<&str> = req.extensions.iter().map(String::as_str).collect();
            let picked = app
                .dialog()
                .file()
                .set_title(req.title)
                .add_filter(req.filter_description, &extensions)
                .blocking_pick_file()
                .and_then(|p| p.into_path().ok());
            let val = picked.map(|p| p.to_string_lossy().into_owned()).unwrap_or_default();
            Some(generic::String { val }.encode_to_vec())
        }
        "klausPaste" => {
            paste(app);
            None
        }
        // Not wired yet: the browser (#11), note type dialogs (#16), recording/playback,
        // clipboard reads, external links. Anki pages treat the empty reply as cancel.
        _ => None,
    }
}

/// The native Edit > Paste action on the focused webview, as Anki's Qt host
/// triggers its page action: a real paste event with the clipboard's data.
#[cfg(target_os = "macos")]
fn paste(app: &AppHandle) {
    let _ = app.run_on_main_thread(|| unsafe {
        use objc2::runtime::{AnyClass, AnyObject, Sel};
        use objc2::{msg_send, sel};
        let Some(class) = AnyClass::get(c"NSApplication") else { return };
        let ns_app: *mut AnyObject = msg_send![class, sharedApplication];
        let nothing: *mut AnyObject = std::ptr::null_mut();
        let action: Sel = sel!(paste:);
        let _: bool = msg_send![ns_app, sendAction: action, to: nothing, from: nothing];
    });
}

// ponytail: context-menu Paste is macOS-only; keyboard paste works everywhere.
// Windows/Linux need their webview's native paste (WebView2 has no API for it).
#[cfg(not(target_os = "macos"))]
fn paste(_app: &AppHandle) {}

fn confirm(app: &AppHandle, text: &str, title: Option<&str>, kind: MessageDialogKind) -> bool {
    let mut dialog = app.dialog().message(text).kind(kind).buttons(MessageDialogButtons::OkCancel);
    if let Some(title) = title {
        dialog = dialog.title(title);
    }
    dialog.blocking_show()
}

/// Points the main window at a page on the bridge, telling Anki pages about dark mode
/// the way Anki does (`#night`).
fn navigate(app: &AppHandle, path: &str) {
    let Some(window) = app.get_webview_window("main") else { return };
    let mut url = app.state::<Url>().join(path).expect("valid page path");
    if window.theme().is_ok_and(|t| t == Theme::Dark) {
        url.set_fragment(Some("night"));
    }
    let _ = window.navigate(url);
}

/// Python's urllib.parse.quote: percent-encode everything but unreserved characters and '/'.
fn quote(s: &str) -> String {
    s.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'_' | b'.' | b'-' | b'~' | b'/' => (b as char).to_string(),
            _ => format!("%{b:02X}"),
        })
        .collect()
}
