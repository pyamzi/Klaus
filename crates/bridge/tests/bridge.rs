//! Drives the Backend Bridge exactly as the webview does: method name + protobuf
//! bytes in, protobuf bytes out, against a real Collection in a temp dir.

use std::sync::Arc;

use anki_proto::decks::{DeckTreeNode, DeckTreeRequest};
use anki_proto::notes::NoteId;
use klaus_bridge::{new_token, serve, Bridge, CallError};
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

#[tokio::test]
async fn http_contract_matches_ankis_post_ts() {
    let (_dir, bridge) = open_temp();
    let static_dir = tempfile::tempdir().unwrap();
    std::fs::write(static_dir.path().join("index.html"), "<p>klaus</p>").unwrap();
    let token = new_token();
    let (addr, server) = serve(Arc::new(bridge), static_dir.path().into(), token.clone()).await.unwrap();
    tokio::spawn(server);
    let base = format!("http://{addr}");
    let client = reqwest::Client::new();
    let body = DeckTreeRequest { now: now() }.encode_to_vec();
    let post = |cookie: Option<&str>, ctype: &str| {
        let mut req = client.post(format!("{base}/_anki/deckTree")).header("Content-Type", ctype).body(body.clone());
        if let Some(c) = cookie {
            req = req.header("Cookie", c);
        }
        req.send()
    };

    // Opening the page with the token grants the cookie.
    let page = client.get(format!("{base}/?t={token}")).send().await.unwrap();
    let cookie = page.headers()["set-cookie"].to_str().unwrap().split(';').next().unwrap().to_owned();
    assert_eq!(page.text().await.unwrap(), "<p>klaus</p>");

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
}
