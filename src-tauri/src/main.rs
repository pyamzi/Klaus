// Prevents an extra console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Arc;

use klaus_bridge::{new_token, serve, Bridge};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

fn main() {
    let app = tauri::Builder::default()
        .setup(|app| {
            let dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&dir)?;
            let bridge = Arc::new(Bridge::new()?);
            bridge.open_collection(&dir).map_err(|e| format!("could not open Collection: {e:?}"))?;
            app.manage(bridge.clone());

            // The frontend is served by the bridge (same origin as /_anki), not Tauri's
            // asset protocol, because Anki's client fetches root-relative URLs.
            let web = app.path().resource_dir()?.join("web");
            let token = new_token();
            let (addr, server) = tauri::async_runtime::block_on(serve(bridge, web, token.clone()))?;
            tauri::async_runtime::spawn(server);
            println!("Klaus bridge listening on {addr}");

            let url = format!("http://{addr}/?t={token}").parse()?;
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
