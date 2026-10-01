//! Drives the Backend Bridge exactly as the webview does: method name + protobuf
//! bytes in, protobuf bytes out, against a real Collection in a temp dir.

use std::path::Path;
use std::sync::{Arc, Mutex};

use anki_proto::collection::OpChangesWithId;
use anki_proto::decks::{Deck, DeckTreeNode, DeckTreeRequest};
use anki_proto::generic::Empty;
use anki_proto::import_export::{
    export_limit, ExportAnkiPackageOptions, ExportAnkiPackageRequest, ExportLimit,
    ImportAnkiPackageOptions, ImportAnkiPackageRequest, ImportResponse,
};
use anki_proto::notes::{AddNoteRequest, Note, NoteId};
use anki_proto::notetypes::{NotetypeId, NotetypeNames};
use klaus_bridge::{new_token, serve, Bridge, CallError, Hook, WebDirs};
use prost::Message;

fn now() -> i64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs() as i64
}

fn open_temp() -> (tempfile::TempDir, Bridge) {
    let dir = tempfile::tempdir().unwrap();
    let bridge = Bridge::new().unwrap();
    bridge.open_collection(dir.path()).unwrap();
    (dir, bridge)
}

fn deck_tree(bridge: &Bridge) -> DeckTreeNode {
    let out = bridge.call("deckTree", &DeckTreeRequest { now: now() }.encode_to_vec()).unwrap();
    DeckTreeNode::decode(out.as_slice()).unwrap()
}

#[test]
fn new_collection_has_default_deck_with_counts() {
    let (dir, bridge) = open_temp();
    assert!(dir.path().join("collection.anki2").exists());
    let tree = deck_tree(&bridge);
    let names: Vec<_> = tree.children.iter().map(|d| d.name.as_str()).collect();
    assert_eq!(names, ["Default"]);
    let default = &tree.children[0];
    assert_eq!((default.new_count, default.learn_count, default.review_count), (0, 0, 0));
}

#[test]
fn collection_survives_close_and_reopen() {
    let dir = tempfile::tempdir().unwrap();
    {
        let bridge = Bridge::new().unwrap();
        bridge.open_collection(dir.path()).unwrap();
        bridge.close_collection().unwrap();
    }
    let bridge = Bridge::new().unwrap();
    bridge.open_collection(dir.path()).unwrap();
    assert_eq!(deck_tree(&bridge).children.len(), 1);
}

#[test]
fn rejects_unknown_and_unlisted_methods() {
    let (_dir, bridge) = open_temp();
    assert_eq!(bridge.call("noSuchMethod", &[]), Err(CallError::UnknownMethod));
    // Real backend method, but the webview must never close the Collection.
    assert_eq!(bridge.call("closeCollection", &[]), Err(CallError::NotAllowed));
}

#[test]
fn backend_errors_come_back_as_messages() {
    let (_dir, bridge) = open_temp();
    match bridge.call("getNote", &NoteId { nid: 42 }.encode_to_vec()) {
        Err(CallError::Backend(msg)) => assert!(!msg.is_empty()),
        other => panic!("expected backend error, got {other:?}"),
    }
}

fn call<T: Message + Default>(bridge: &Bridge, method: &str, input: impl Message) -> T {
    T::decode(bridge.call(method, &input.encode_to_vec()).unwrap().as_slice()).unwrap()
}

/// Builds a real .apkg: a Collection with one Basic note in a "Biology" deck, exported
/// the way Anki exports (a shell-initiated call, so not via the webview allowlist).
fn make_apkg(out: &Path) {
    let (_dir, bridge) = open_temp();
    let mut deck: Deck = Deck::decode(bridge.call_trusted("newDeck", &[]).unwrap().as_slice()).unwrap();
    deck.name = "Biology".into();
    let deck_id = OpChangesWithId::decode(bridge.call_trusted("addDeck", &deck.encode_to_vec()).unwrap().as_slice())
        .unwrap()
        .id;
    let names: NotetypeNames = call(&bridge, "getNotetypeNames", Empty {});
    let basic = names.entries.iter().find(|n| n.name == "Basic").unwrap();
    let mut note: Note = call(&bridge, "newNote", NotetypeId { ntid: basic.id });
    note.fields = vec!["Loop of Henle".into(), "Countercurrent multiplier".into()];
    let _: anki_proto::notes::AddNoteResponse = call(&bridge, "addNote", AddNoteRequest { note: Some(note), deck_id });
    let req = ExportAnkiPackageRequest {
        out_path: out.to_string_lossy().into(),
        options: Some(ExportAnkiPackageOptions { with_scheduling: true, with_media: true, ..Default::default() }),
        limit: Some(ExportLimit { limit: Some(export_limit::Limit::WholeCollection(Empty {})) }),
    };
    bridge.call_trusted("exportAnkiPackage", &req.encode_to_vec()).unwrap();
}

#[test]
fn imports_apkg_and_deck_list_shows_it() {
    let pkg = tempfile::tempdir().unwrap();
    let apkg = pkg.path().join("biology.apkg");
    make_apkg(&apkg);

    let (_dir, bridge) = open_temp();
    // Exactly the calls Anki's import-anki-package page makes.
    let options: ImportAnkiPackageOptions = call(&bridge, "getImportAnkiPackagePresets", Empty {});
    let res: ImportResponse = call(
        &bridge,
        "importAnkiPackage",
        ImportAnkiPackageRequest { package_path: apkg.to_string_lossy().into(), options: Some(options) },
    );
    assert_eq!(res.log.unwrap().new.len(), 1);

    let tree = deck_tree(&bridge);
    let biology = tree.children.iter().find(|d| d.name == "Biology").expect("imported deck");
    assert_eq!((biology.new_count, biology.learn_count, biology.review_count), (1, 0, 0));
}

#[tokio::test]
async fn http_contract_matches_ankis_post_ts() {
    let (_dir, bridge) = open_temp();
    let klaus_dir = tempfile::tempdir().unwrap();
    std::fs::write(klaus_dir.path().join("index.html"), "<p>klaus</p>").unwrap();
    let anki_dir = tempfile::tempdir().unwrap();
    std::fs::write(anki_dir.path().join("index.html"), "<html><head></head><p>anki</p></html>").unwrap();
    std::fs::create_dir(anki_dir.path().join("_app")).unwrap();
    std::fs::write(anki_dir.path().join("_app/start.mjs"), "// anki").unwrap();
    let hooked = Arc::new(Mutex::new(Vec::new()));
    let hook: Hook = {
        let hooked = hooked.clone();
        Arc::new(move |method: &str, _: &[u8]| hooked.lock().unwrap().push(method.to_owned()))
    };
    let token = new_token();
    let web = WebDirs { klaus: klaus_dir.path().into(), anki: anki_dir.path().into() };
    let (addr, server) = serve(Arc::new(bridge), web, token.clone(), hook).await.unwrap();
    tokio::spawn(server);
    let base = format!("http://{addr}");
    let client = reqwest::Client::builder().redirect(reqwest::redirect::Policy::none()).build().unwrap();
    let body = DeckTreeRequest { now: now() }.encode_to_vec();
    let post = |cookie: Option<&str>, ctype: &str| {
        let mut req = client.post(format!("{base}/_anki/deckTree")).header("Content-Type", ctype).body(body.clone());
        if let Some(c) = cookie {
            req = req.header("Cookie", c);
        }
        req.send()
    };

    // Opening the page with the token grants the cookie and redirects to a
    // token-free URL, so page scripts can't read the token from location.
    let grant = client.get(format!("{base}/?t={token}")).send().await.unwrap();
    assert_eq!(grant.status(), 303);
    assert_eq!(grant.headers()["location"], "/");
    let cookie = grant.headers()["set-cookie"].to_str().unwrap().split(';').next().unwrap().to_owned();
    assert_eq!(cookie, format!("klaus_{}={token}", addr.port()));
    assert_eq!(client.get(format!("{base}/")).send().await.unwrap().text().await.unwrap(), "<p>klaus</p>");

    let ok = post(Some(&cookie), "application/binary").await.unwrap();
    assert_eq!(ok.status(), 200);
    let tree = DeckTreeNode::decode(ok.bytes().await.unwrap()).unwrap();
    assert_eq!(tree.children[0].name, "Default");

    assert_eq!(post(None, "application/binary").await.unwrap().status(), 403);
    assert_eq!(post(Some(&cookie), "text/plain").await.unwrap().status(), 403);
    let missing = client
        .post(format!("{base}/_anki/noSuchMethod"))
        .header("Content-Type", "application/binary")
        .header("Cookie", &cookie)
        .send()
        .await
        .unwrap();
    assert_eq!(missing.status(), 404);

    let raw = |method: &str, body: Vec<u8>| {
        client
            .post(format!("{base}/_anki/{method}"))
            .header("Content-Type", "application/binary")
            .header("Cookie", &cookie)
            .body(body)
            .send()
    };
    // Empty output (generic.Empty) comes back as 204, like Anki's mediasrv.
    assert_eq!(raw("setWantsAbort", vec![]).await.unwrap().status(), 204);
    // Backend errors are 500 with the message as plain text, which post.ts shows.
    let err = raw("getNote", NoteId { nid: 42 }.encode_to_vec()).await.unwrap();
    assert_eq!(err.status(), 500);
    assert!(!err.text().await.unwrap().is_empty());

    // Calls Anki pages make to their Qt host go to the shell's hook instead.
    let done = client
        .post(format!("{base}/_anki/importDone"))
        .header("Content-Type", "application/binary")
        .header("Cookie", &cookie)
        .send()
        .await
        .unwrap();
    assert_eq!(done.status(), 204);
    for _ in 0..50 {
        if !hooked.lock().unwrap().is_empty() {
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
    assert_eq!(*hooked.lock().unwrap(), ["importDone"]);

    // Anki's routes and assets come from Anki's build; everything else from Klaus's.
    let get = |path: &str| {
        let url = format!("{base}{path}");
        let client = client.clone();
        async move { client.get(url).send().await.unwrap().text().await.unwrap() }
    };
    // Anki pages get Klaus's host script and base styles before their own scripts.
    let anki_page = r#"<html><head><link rel="stylesheet" href="/anki-host.css"><script src="/anki-host.js"></script></head><p>anki</p></html>"#;
    assert_eq!(get("/import-anki-package/Users/me/biology.apkg").await, anki_page);
    assert_eq!(get("/import-page/").await, anki_page);
    assert_eq!(get("/_app/start.mjs").await, "// anki");
    assert_eq!(get("/decks").await, "<p>klaus</p>");
}
