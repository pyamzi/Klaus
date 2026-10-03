//! Drives the Backend Bridge exactly as the webview does: method name + protobuf
//! bytes in, protobuf bytes out, against a real Collection in a temp dir.

use std::path::Path;
use std::sync::{Arc, Mutex};

use anki_proto::collection::{OpChanges, OpChangesWithId};
use anki_proto::config::Preferences;
use anki_proto::deck_config::{DeckConfigsForUpdate, UpdateDeckConfigsRequest};
use anki_proto::scheduler::{GetQueuedCardsRequest, QueuedCards, SchedTimingTodayResponse};
use anki_proto::decks::{Deck, DeckId, DeckTreeNode, DeckTreeRequest};
use anki_proto::generic::{self, Empty};
use anki_proto::import_export::{
    export_limit, ExportAnkiPackageOptions, ExportAnkiPackageRequest, ExportLimit,
    ImportAnkiPackageOptions, ImportAnkiPackageRequest, ImportResponse,
};
use anki_proto::media::AddMediaFileRequest;
use anki_proto::notes::{
    note_fields_check_response::State, AddNoteRequest, AddNoteResponse, DeckAndNotetype, DefaultsForAddingRequest, Note,
    NoteFieldsCheckResponse, NoteId,
};
use anki_proto::notetypes::{ChangeNotetypeInfo, GetChangeNotetypeInfoRequest, NotetypeId, NotetypeNames};
use klaus_bridge::frontend::{ConvertPastedImageRequest, ConvertPastedImageResponse, SetSettingJsonRequest};
use klaus_bridge::klaus::{RenderCardRequest, RenderCardResponse};
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

/// The calls Anki's editor page makes in add mode (NoteEditor.svelte), in order.
#[test]
fn adds_a_note_the_way_the_editor_does() {
    let (dir, bridge) = open_temp();
    let defaults: DeckAndNotetype =
        call(&bridge, "defaultsForAdding", DefaultsForAddingRequest { home_deck_of_current_review_card: 0 });
    let mut note: Note = call(&bridge, "newNote", NotetypeId { ntid: defaults.notetype_id });

    // A pasted image: convertPastedImage (re-encoded to the editor's chosen jpg), then
    // addMediaFile, then an <img> in the field.
    let mut png = Vec::new();
    image::RgbaImage::from_pixel(4, 4, image::Rgba([225, 29, 72, 255]))
        .write_to(&mut std::io::Cursor::new(&mut png), image::ImageFormat::Png)
        .unwrap();
    let converted: ConvertPastedImageResponse =
        call(&bridge, "convertPastedImage", ConvertPastedImageRequest { data: png, ext: "jpg".into() });
    assert_eq!(image::guess_format(&converted.data).unwrap(), image::ImageFormat::Jpeg);
    let name: generic::String = call(
        &bridge,
        "addMediaFile",
        AddMediaFileRequest { desired_name: "paste-1.jpg".into(), data: converted.data.clone() },
    );
    assert_eq!(std::fs::read(dir.path().join("collection.media").join(&name.val)).unwrap(), converted.data);
    // Formats browsers paste besides png/jpg are converted too; unreadable bytes are
    // refused rather than stored under a mismatched extension.
    let mut gif = Vec::new();
    image::RgbaImage::from_pixel(2, 2, image::Rgba([0, 0, 255, 255]))
        .write_to(&mut std::io::Cursor::new(&mut gif), image::ImageFormat::Gif)
        .unwrap();
    let from_gif: ConvertPastedImageResponse =
        call(&bridge, "convertPastedImage", ConvertPastedImageRequest { data: gif, ext: "png".into() });
    assert_eq!(image::guess_format(&from_gif.data).unwrap(), image::ImageFormat::Png);
    let junk = ConvertPastedImageRequest { data: b"<svg/>".to_vec(), ext: "png".into() };
    assert!(matches!(bridge.call("convertPastedImage", &junk.encode_to_vec()), Err(CallError::Backend(_))));

    note.fields = vec![format!("Loop of Henle <img src=\"{}\">", name.val), "Countercurrent multiplier".into()];
    note.tags = vec!["renal".into()];
    let check: NoteFieldsCheckResponse = call(&bridge, "noteFieldsCheck", note.clone());
    assert_eq!(check.state(), State::Normal);
    let added: anki_proto::notes::AddNoteResponse =
        call(&bridge, "addNote", AddNoteRequest { note: Some(note.clone()), deck_id: defaults.deck_id });

    let saved: Note = call(&bridge, "getNote", NoteId { nid: added.note_id });
    assert_eq!(saved.tags, ["renal"]);
    assert_eq!(deck_tree(&bridge).children[0].new_count, 1);
    // Same first field again: the editor flags it as a duplicate.
    let dupe: NoteFieldsCheckResponse = call(&bridge, "noteFieldsCheck", note);
    assert_eq!(dupe.state(), State::Duplicate);
}

/// Adds a note of the named notetype to the Default deck; returns its first card's id.
fn add_note(bridge: &Bridge, notetype: &str, fields: &[&str]) -> i64 {
    let names: NotetypeNames = call(bridge, "getNotetypeNames", Empty {});
    let ntid = names.entries.iter().find(|n| n.name == notetype).unwrap().id;
    let mut note: Note = call(bridge, "newNote", NotetypeId { ntid });
    note.fields = fields.iter().map(|f| f.to_string()).collect();
    let added: anki_proto::notes::AddNoteResponse =
        call(bridge, "addNote", AddNoteRequest { note: Some(note), deck_id: 1 });
    let cards: anki_proto::cards::CardIds = Message::decode(
        bridge.call_trusted("cardsOfNote", &NoteId { nid: added.note_id }.encode_to_vec()).unwrap().as_slice(),
    )
    .unwrap();
    cards.cids[0]
}

fn queue(bridge: &Bridge) -> anki_proto::scheduler::QueuedCards {
    call(bridge, "getQueuedCards", anki_proto::scheduler::GetQueuedCardsRequest { fetch_limit: 1, intraday_learning_only: false })
}

/// #7's acceptance sequence, as Klaus's review screen drives it (Anki's reviewer.py).
#[test]
fn reviews_a_card_like_ankis_reviewer() {
    use anki_proto::scheduler::{card_answer::Rating, CardAnswer, CongratsInfoResponse};
    let (_dir, bridge) = open_temp();
    add_note(&bridge, "Basic", &["Loop of Henle", "Countercurrent multiplier"]);
    let _: anki_proto::collection::OpChanges = call(&bridge, "setCurrentDeck", anki_proto::decks::DeckId { did: 1 });

    let q = queue(&bridge);
    assert_eq!((q.new_count, q.learning_count, q.review_count, q.cards.len()), (1, 0, 0, 1));
    let top = q.cards[0].clone();
    let states = top.states.clone().unwrap();
    let labels: generic::StringList = call(&bridge, "describeNextStates", states.clone());
    assert_eq!(labels.vals.len(), 4, "a label for each of Again/Hard/Good/Easy");
    assert!(labels.vals.iter().all(|l| !l.is_empty()));

    let card_id = top.card.unwrap().id;
    let answer = CardAnswer {
        card_id,
        current_state: states.current.clone(),
        new_state: states.easy.clone(),
        rating: Rating::Easy as i32,
        answered_at_millis: now() * 1000,
        milliseconds_taken: 4_000,
    };
    let _: anki_proto::collection::OpChanges = call(&bridge, "answerCard", answer);
    assert!(queue(&bridge).cards.is_empty(), "Easy graduates the only card");
    let _: CongratsInfoResponse = call(&bridge, "congratsInfo", Empty {});

    // Undo puts the card back on top of the queue.
    let _: anki_proto::collection::OpChangesAfterUndo = call(&bridge, "undo", Empty {});
    let again = queue(&bridge);
    assert_eq!(again.new_count, 1);
    assert_eq!(again.cards[0].card.as_ref().unwrap().id, card_id);
}

fn render(bridge: &Bridge, card_id: i64, typed: Option<&str>) -> RenderCardResponse {
    call(bridge, "klausRenderCard", RenderCardRequest { card_id, typed_answer: typed.map(Into::into) })
}

/// The card HTML Klaus shows must be what Anki's desktop reviewer shows.
#[test]
fn renders_cards_like_ankis_reviewer() {
    let (_dir, bridge) = open_temp();
    let front = r#"[sound:heart.mp3] \(x^2\) [$]e^x[/$] <img src="my pic.png">"#;
    let basic = add_note(&bridge, "Basic", &[front, "Back side"]);
    let card = render(&bridge, basic, None);
    assert!(card.question.starts_with("<style>"), "notetype CSS first: {}", card.question);
    assert!(card.question.contains(r#"onclick="pycmd('play:q:0'); return false;""#), "{}", card.question);
    assert!(card.question.contains(r"\(x^2\)"), "MathJax left for the page");
    assert!(card.question.contains(r#"<img class=latex alt="#) && card.question.contains(r#"src="latex-"#), "[$]…[/$] becomes a LaTeX image");
    assert!(card.question.contains("my%20pic.png"), "media filenames escaped");
    // {{FrontSide}} reuses the question's tags, so its sound stays a question tag.
    assert!(card.answer.contains("play:q:0") && !card.answer.contains("play:a:"), "{}", card.answer);
    assert!(card.answer.contains("<hr id=answer>") && card.answer.contains("Back side"));

    let typed = add_note(&bridge, "Basic (type in the answer)", &["Loop of Henle", "Countercurrent"]);
    let card = render(&bridge, typed, None);
    assert!(card.question.contains(r#"<input type=text id=typeans onkeypress="_typeAnsPress();""#), "{}", card.question);
    assert!(!card.answer.contains("[[type:"), "no typed answer yet: marker removed");
    let revealed = render(&bridge, typed, Some("Counter"));
    assert!(revealed.answer.contains("typeGood") && revealed.answer.contains("typeMissed"), "{}", revealed.answer);
    assert!(!revealed.answer.contains("[[type:"));
}

/// Profile settings Anki keeps in Qt (pm.meta / pm.profile) and collection config.
#[test]
fn settings_round_trip_and_persist() {
    let dir = tempfile::tempdir().unwrap();
    let get = |bridge: &Bridge, method: &str, key: &str| -> String {
        let out: generic::Json = call(bridge, method, generic::String { val: key.into() });
        String::from_utf8(out.json).unwrap()
    };
    {
        let bridge = Bridge::new().unwrap();
        bridge.open_collection(dir.path()).unwrap();
        assert_eq!(get(&bridge, "getMetaJson", "addTagsCollapsed"), "null");
        assert_eq!(get(&bridge, "getConfigJson", "noSuchKey"), "null");
        let set = SetSettingJsonRequest { key: "addTagsCollapsed".into(), value_json: b"true".to_vec() };
        bridge.call("setMetaJson", &set.encode_to_vec()).unwrap();
        let set = SetSettingJsonRequest { key: "lastColour".into(), value_json: b"\"#ff0000\"".to_vec() };
        bridge.call("setProfileConfigJson", &set.encode_to_vec()).unwrap();
    }
    let bridge = Bridge::new().unwrap();
    bridge.open_collection(dir.path()).unwrap();
    assert_eq!(get(&bridge, "getMetaJson", "addTagsCollapsed"), "true");
    assert_eq!(get(&bridge, "getProfileConfigJson", "lastColour"), "\"#ff0000\"");
    assert_eq!(get(&bridge, "getMetaJson", "lastColour"), "null");
}

#[tokio::test]
async fn change_notetype_saves_and_closes_only_on_success() {
    let (_dir, bridge) = open_temp();
    let names: NotetypeNames = call(&bridge, "getNotetypeNames", Empty {});
    let basic = names.entries.iter().find(|n| n.name == "Basic").unwrap().id;
    let reversed = names.entries.iter().find(|n| n.name == "Basic (and reversed card)").unwrap().id;
    let mut note: Note = call(&bridge, "newNote", NotetypeId { ntid: basic });
    note.fields = vec!["Front".into(), "Back".into()];
    let added: AddNoteResponse = call(&bridge, "addNote", AddNoteRequest { note: Some(note.clone()), deck_id: 1 });
    let also_added: AddNoteResponse = call(&bridge, "addNote", AddNoteRequest { note: Some(note.clone()), deck_id: 1 });
    let untouched: AddNoteResponse = call(&bridge, "addNote", AddNoteRequest { note: Some(note), deck_id: 1 });
    let info: ChangeNotetypeInfo = call(
        &bridge,
        "getChangeNotetypeInfo",
        GetChangeNotetypeInfoRequest { old_notetype_id: basic, new_notetype_id: reversed },
    );
    let mut change = info.input.unwrap();
    change.new_fields = vec![1, 0];
    let bridge = Arc::new(bridge);
    let web_dir = tempfile::tempdir().unwrap();
    let web = WebDirs {
        klaus: web_dir.path().into(),
        anki: web_dir.path().into(),
        anki_static: web_dir.path().into(),
    };
    let (tx, mut hooks) = tokio::sync::mpsc::unbounded_channel();
    let hook: Hook = Arc::new(move |method, input| {
        tx.send((method.to_owned(), input.to_vec())).unwrap();
        None
    });
    let token = new_token();
    let (addr, server) = serve(bridge.clone(), web, token.clone(), hook).await.unwrap();
    tokio::spawn(server);
    let client = reqwest::Client::builder().redirect(reqwest::redirect::Policy::none()).build().unwrap();
    let base = format!("http://{addr}");
    let grant = client.get(format!("{base}/?t={token}")).send().await.unwrap();
    let cookie = grant.headers()["set-cookie"].to_str().unwrap().split(';').next().unwrap();
    let post = |method: &str, body: Vec<u8>| {
        client
            .post(format!("{base}/_anki/{method}"))
            .header("Content-Type", "application/binary")
            .header("Cookie", cookie)
            .header("Referer", format!("{base}/change-notetype/{basic}?nid={}&nid={}", added.note_id, also_added.note_id))
            .body(body)
            .send()
    };
    for method in ["changeNotetype", "closeEditCurrent"] {
        let denied = client
            .post(format!("{base}/_anki/{method}"))
            .header("Content-Type", "application/binary")
            .body(change.encode_to_vec())
            .send()
            .await
            .unwrap();
        assert_eq!(denied.status(), 403);
        let denied = client
            .post(format!("{base}/_anki/{method}"))
            .header("Cookie", cookie)
            .body(change.encode_to_vec())
            .send()
            .await
            .unwrap();
        assert_eq!(denied.status(), 403);
    }
    assert_eq!(post("changeNotetype", vec![0xff]).await.unwrap().status(), 500);
    // A page without Qt's selected-note context must not silently save nothing.
    for page in [
        format!("{base}/change-notetype/{basic}"),
        format!("{base}/change-notetype/{basic}?nid=invalid"),
        format!("{base}/change-notetype/{basic}?nid=-1"),
        format!("{base}/editor/?nid={}", added.note_id),
        format!("http://example.invalid/change-notetype/{basic}?nid={}", added.note_id),
    ] {
        let response = client
            .post(format!("{base}/_anki/changeNotetype"))
            .header("Content-Type", "application/binary")
            .header("Cookie", cookie)
            .header("Referer", page)
            .body(change.encode_to_vec())
            .send()
            .await
            .unwrap();
        assert_eq!(response.status(), 400);
    }
    assert!(hooks.try_recv().is_err());
    // The unmodified Anki page sends no IDs; its URL supplies the selection.
    assert!(change.note_ids.is_empty());
    assert_eq!(post("changeNotetype", change.encode_to_vec()).await.unwrap().status(), 204);
    let (method, input) = tokio::time::timeout(std::time::Duration::from_secs(5), hooks.recv()).await.unwrap().unwrap();
    assert_eq!(method, "closeEditCurrent");
    assert!(input.is_empty());
    for nid in [added.note_id, also_added.note_id] {
        let saved: Note = call(&bridge, "getNote", NoteId { nid });
        assert_eq!(saved.notetype_id, reversed);
        assert_eq!(saved.fields, ["Back", "Front"]);
    }
    let saved: Note = call(&bridge, "getNote", NoteId { nid: untouched.note_id });
    assert_eq!(saved.notetype_id, basic);
    assert_eq!(saved.fields, ["Front", "Back"]);

    change.new_notetype_id = 0;
    change.note_ids = vec![added.note_id];
    assert_eq!(post("changeNotetype", change.encode_to_vec()).await.unwrap().status(), 204);
    let (method, input) = tokio::time::timeout(std::time::Duration::from_secs(5), hooks.recv()).await.unwrap().unwrap();
    assert_eq!(method, "showMessageBox");
    let error = klaus_bridge::frontend::ShowMessageBoxRequest::decode(input.as_slice()).unwrap();
    assert_eq!(error.r#type, 2);
    assert!(!error.text.is_empty());
    assert!(hooks.try_recv().is_err());
    let saved: Note = call(&bridge, "getNote", NoteId { nid: added.note_id });
    assert_eq!(saved.notetype_id, reversed);
    assert_eq!(saved.fields, ["Back", "Front"]);

    assert_eq!(post("closeEditCurrent", vec![]).await.unwrap().status(), 204);
    let (method, input) = hooks.recv().await.unwrap();
    assert_eq!(method, "closeEditCurrent");
    assert!(input.is_empty());
}

#[tokio::test]
async fn http_contract_matches_ankis_post_ts() {
    let (col_dir, bridge) = open_temp();
    std::fs::create_dir_all(col_dir.path().join("collection.media")).unwrap();
    std::fs::write(col_dir.path().join("collection.media/heart.png"), "png bytes").unwrap();
    std::fs::write(col_dir.path().join("collection.media/evil.svg"), "<svg onload=alert(1)/>").unwrap();
    let klaus_dir = tempfile::tempdir().unwrap();
    std::fs::write(klaus_dir.path().join("index.html"), "<p>klaus</p>").unwrap();
    std::fs::write(klaus_dir.path().join("anki-host.js"), "// klaus host").unwrap();
    std::fs::write(col_dir.path().join("collection.media/anki-host.js"), "// from a deck").unwrap();
    let anki_dir = tempfile::tempdir().unwrap();
    std::fs::write(
        anki_dir.path().join("index.html"),
        r#"<html><head><meta http-equiv="content-security-policy" content="script-src 'self' 'sha256-abc='"></head><p>anki</p></html>"#,
    )
    .unwrap();
    std::fs::create_dir(anki_dir.path().join("_app")).unwrap();
    std::fs::write(anki_dir.path().join("_app/start.mjs"), "// anki").unwrap();
    let hooked = Arc::new(Mutex::new(Vec::new()));
    let hook: Hook = {
        let hooked = hooked.clone();
        Arc::new(move |method: &str, input: &[u8]| {
            hooked.lock().unwrap().push(method.to_owned());
            // A hook that answers, like askUser: echo the input back.
            (method == "askUser").then(|| input.to_vec())
        })
    };
    let token = new_token();
    let static_dir = tempfile::tempdir().unwrap();
    std::fs::create_dir_all(static_dir.path().join("_anki/js")).unwrap();
    std::fs::write(static_dir.path().join("_anki/js/reviewer.js"), "// reviewer").unwrap();
    let web = WebDirs {
        klaus: klaus_dir.path().into(),
        anki: anki_dir.path().into(),
        anki_static: static_dir.path().into(),
    };
    let save = deck_options_save(&bridge, |r| r.configs[0].config.as_mut().unwrap().new_per_day = 9);
    let bad_save = deck_options_save(&bridge, |r| r.configs.clear());
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
    let deep = client.get(format!("{base}/review?deck=5&t={token}")).send().await.unwrap();
    assert_eq!(deep.headers()["location"], "/review?deck=5", "only the token is dropped");

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
    // A hook's reply is returned to the page as the protobuf response.
    let asked = raw("askUser", b"question".to_vec()).await.unwrap();
    assert_eq!(asked.status(), 200);
    assert_eq!(&asked.bytes().await.unwrap()[..], b"question");

    // Deck options' Save returns at once and saves in the background, then the shell
    // closes the page (Anki's update_deck_configs); a failed save is shown instead.
    let wait_for_hook = |name: &'static str| {
        let hooked = hooked.clone();
        async move {
            for _ in 0..200 {
                if hooked.lock().unwrap().iter().any(|m| m == name) {
                    return;
                }
                tokio::time::sleep(std::time::Duration::from_millis(10)).await;
            }
            panic!("{name} never fired");
        }
    };
    assert_eq!(raw("updateDeckConfigs", save.encode_to_vec()).await.unwrap().status(), 204);
    wait_for_hook("deckOptionsRequireClose").await;
    let saved = raw("getDeckConfigsForUpdate", DeckId { did: 1 }.encode_to_vec()).await.unwrap();
    let saved = DeckConfigsForUpdate::decode(saved.bytes().await.unwrap()).unwrap();
    assert_eq!(saved.all_config[0].config.as_ref().unwrap().config.as_ref().unwrap().new_per_day, 9);
    assert_eq!(raw("updateDeckConfigs", bad_save.encode_to_vec()).await.unwrap().status(), 204);
    wait_for_hook("showMessageBox").await;

    // Anki's routes and assets come from Anki's build; everything else from Klaus's.
    let get = |path: &str| {
        let url = format!("{base}{path}");
        let client = client.clone();
        async move { client.get(url).send().await.unwrap().text().await.unwrap() }
    };
    // Anki pages get the host script (bridgeCommand) and base styles before their own scripts.
    let anki_page = r#"<html><head><link rel="stylesheet" href="/anki-host.css"><script src="/native-dialogs.js"></script><script src="/anki-host.js"></script></head><p>anki</p></html>"#;
    assert_eq!(get("/import-anki-package/Users/me/biology.apkg").await, anki_page);
    assert_eq!(get("/editor/?mode=add").await, anki_page);
    // The editor's relative media URLs come from the Collection's media folder.
    assert_eq!(get("/editor/heart.png").await, "png bytes");
    assert_eq!(get("/heart.png").await, "png bytes");
    assert_eq!(get("/anki-host.js").await, "// klaus host");
    // Media (e.g. a deck's SVG/HTML) must never run as a same-origin document.
    for path in ["/evil.svg", "/editor/evil.svg"] {
        let res = client.get(format!("{base}{path}")).send().await.unwrap();
        let csp = res.headers()["content-security-policy"].to_str().unwrap();
        for d in ["script-src 'none'", "form-action 'none'", "base-uri 'none'", "img-src 'self'", "sandbox allow-same-origin"] {
            assert!(csp.contains(d), "{path}: {csp}");
        }
    }
    // Anki's response CSP replaces the build's meta tag: pages showing note HTML only
    // run Anki's and Klaus's scripts (path-scoped, so not a deck's media) and can't post forms.
    let csp = |path: &str| {
        let url = format!("{base}{path}");
        let client = client.clone();
        async move { client.get(url).send().await.unwrap().headers()["content-security-policy"].to_str().unwrap().to_owned() }
    };
    let o = &base;
    let untrusted = |ancestors: &str| {
        format!("script-src {o}/_anki/ {o}/_app/ {o}/native-dialogs.js {o}/anki-host.js 'sha256-abc='; form-action 'none'; frame-ancestors {ancestors}")
    };
    // Only the editor may be framed, by Klaus's own pages (the browser's side editor).
    assert_eq!(csp("/editor/?mode=add").await, untrusted("'self'"));
    assert_eq!(csp("/image-occlusion/Users/me/a.png").await, untrusted("'none'"));
    assert_eq!(csp("/deck-options/1").await, "frame-ancestors 'none'");

    // Reviewer assets are served for the card frame, readable cross-origin (fonts)…
    let js = client.get(format!("{base}/_anki/js/reviewer.js")).send().await.unwrap();
    assert_eq!(js.headers()["access-control-allow-origin"], "*");
    assert_eq!(js.text().await.unwrap(), "// reviewer");
    // …but backend calls never are.
    let call = raw("deckTree", DeckTreeRequest { now: now() }.encode_to_vec()).await.unwrap();
    assert!(call.headers().get("access-control-allow-origin").is_none());

    // Large bodies (pasted photos) get past the default 2 MiB cap.
    let big = ConvertPastedImageRequest { data: vec![0; 3 * 1024 * 1024], ext: "png".into() };
    let res = raw("convertPastedImage", big.encode_to_vec()).await.unwrap();
    assert_eq!(res.status(), 500, "reaches the handler (and is refused as unreadable), not 413");
    assert_eq!(get("/..%2Fcollection.anki2").await, "<p>klaus</p>");
    assert_eq!(get("/_app/start.mjs").await, "// anki");
    assert_eq!(get("/decks").await, "<p>klaus</p>");
}

fn trusted<T: Message + Default>(bridge: &Bridge, method: &str, input: impl Message) -> T {
    T::decode(bridge.call_trusted(method, &input.encode_to_vec()).unwrap().as_slice()).unwrap()
}

/// What the deck options page sends on Save: the deck's current state with `edit`
/// applied (as UpdateDeckConfigsRequest, built the way DeckOptionsState.dataForSaving does).
fn deck_options_save(
    bridge: &Bridge,
    edit: impl FnOnce(&mut UpdateDeckConfigsRequest),
) -> UpdateDeckConfigsRequest {
    let current: DeckConfigsForUpdate = call(bridge, "getDeckConfigsForUpdate", DeckId { did: 1 });
    let deck = current.current_deck.unwrap();
    let config = current.all_config.into_iter().find(|c| c.config.as_ref().unwrap().id == deck.config_id).unwrap();
    let mut req = UpdateDeckConfigsRequest {
        target_deck_id: 1,
        configs: vec![config.config.unwrap()],
        limits: deck.limits,
        new_cards_ignore_review_limit: current.new_cards_ignore_review_limit,
        fsrs: current.fsrs,
        apply_all_parent_limits: current.apply_all_parent_limits,
        ..Default::default()
    };
    edit(&mut req);
    req
}

#[test]
fn deck_options_save_and_reload() {
    let dir = tempfile::tempdir().unwrap();
    let bridge = Bridge::new().unwrap();
    bridge.open_collection(dir.path()).unwrap();
    let req = deck_options_save(&bridge, |r| {
        let c = r.configs[0].config.as_mut().unwrap();
        c.new_per_day = 7;
        c.learn_steps = vec![2.0, 30.0];
        c.bury_new = true;
        c.desired_retention = 0.85;
        r.fsrs = true;
    });
    let _: OpChanges = trusted(&bridge, "updateDeckConfigs", req);
    bridge.close_collection().unwrap();
    bridge.open_collection(dir.path()).unwrap();

    let reloaded: DeckConfigsForUpdate = call(&bridge, "getDeckConfigsForUpdate", DeckId { did: 1 });
    let c = reloaded.all_config[0].config.as_ref().unwrap().config.as_ref().unwrap();
    assert_eq!((c.new_per_day, c.learn_steps.clone(), c.bury_new), (7, vec![2.0, 30.0], true));
    assert_eq!(c.desired_retention, 0.85);
    assert!(reloaded.fsrs);
}

#[test]
fn fsrs_on_and_off_schedule_the_same_answer_differently() {
    let (_dir, bridge) = open_temp();
    let defaults: DeckAndNotetype =
        call(&bridge, "defaultsForAdding", DefaultsForAddingRequest { home_deck_of_current_review_card: 0 });
    let mut note: Note = call(&bridge, "newNote", NotetypeId { ntid: defaults.notetype_id });
    note.fields = vec!["front".into(), "back".into()];
    let _: AddNoteResponse =
        trusted(&bridge, "addNote", AddNoteRequest { note: Some(note), deck_id: defaults.deck_id });
    // The interval each answer would give the new card, as the reviewer's buttons show.
    let labels = |bridge: &Bridge| {
        let queued: QueuedCards =
            trusted(bridge, "getQueuedCards", GetQueuedCardsRequest { fetch_limit: 1, intraday_learning_only: false });
        let states = queued.cards[0].states.clone().unwrap();
        trusted::<generic::StringList>(bridge, "describeNextStates", states).vals
    };
    let sm2 = labels(&bridge);
    let _: OpChanges = trusted(&bridge, "updateDeckConfigs", deck_options_save(&bridge, |r| r.fsrs = true));
    let fsrs = labels(&bridge);
    // Easy graduates a new card: SM-2 uses the preset's easy interval, FSRS its
    // initial stability for Easy.
    assert_ne!(sm2[3], fsrs[3], "{sm2:?} vs {fsrs:?}");
}

#[test]
fn day_rollover_hour_sets_when_the_day_ends() {
    let (_dir, bridge) = open_temp();
    let next_day_at = |rollover: u32| {
        let mut prefs: Preferences = trusted(&bridge, "getPreferences", Empty {});
        prefs.scheduling.as_mut().unwrap().rollover = rollover;
        let _: OpChanges = trusted(&bridge, "setPreferences", prefs);
        trusted::<SchedTimingTodayResponse>(&bridge, "schedTimingToday", Empty {}).next_day_at
    };
    // Due counts are taken against this cutoff: moving "next day starts at" from
    // 4:00 to 20:00 moves it by 16 hours (modulo a day).
    let (four, twenty) = (next_day_at(4), next_day_at(20));
    assert_eq!((twenty - four).rem_euclid(86_400), 16 * 3600);
}

fn find_deck<'a>(node: &'a DeckTreeNode, name: &str) -> Option<&'a DeckTreeNode> {
    if node.name == name {
        return Some(node);
    }
    node.children.iter().find_map(|c| find_deck(c, name))
}

fn create_deck(bridge: &Bridge, name: &str) -> i64 {
    let mut deck: Deck = call(bridge, "newDeck", Empty {});
    deck.name = name.into();
    call::<OpChangesWithId>(bridge, "addDeck", deck).id
}

/// #10, as the deck list drives it: create, rename (which also nests), collapse,
/// delete and undo.
#[test]
fn manages_decks_from_the_deck_list() {
    use anki_proto::decks::{set_deck_collapsed_request::Scope, DeckIds, RenameDeckRequest, SetDeckCollapsedRequest};
    let dir = tempfile::tempdir().unwrap();
    let bridge = Bridge::new().unwrap();
    bridge.open_collection(dir.path()).unwrap();

    let bio = create_deck(&bridge, "Biology");
    let cells = create_deck(&bridge, "Cells");
    add_note(&bridge, "Basic", &["front", "back"]);
    let _: OpChanges = call(&bridge, "renameDeck", RenameDeckRequest { deck_id: cells, new_name: "Biology::Cell biology".into() });
    let tree = deck_tree(&bridge);
    let parent = find_deck(&tree, "Biology").unwrap();
    assert_eq!((parent.deck_id, parent.children[0].name.as_str()), (bio, "Cell biology"));
    assert!(find_deck(&tree, "Cells").is_none());

    // Collapsing persists in the Collection.
    let collapse = SetDeckCollapsedRequest { deck_id: bio, collapsed: true, scope: Scope::Reviewer as i32 };
    let _: OpChanges = call(&bridge, "setDeckCollapsed", collapse);
    bridge.close_collection().unwrap();
    bridge.open_collection(dir.path()).unwrap();
    assert!(find_deck(&deck_tree(&bridge), "Biology").unwrap().collapsed);

    // Deleting a parent deletes its children; undo brings both back.
    let removed: anki_proto::collection::OpChangesWithCount = call(&bridge, "removeDecks", DeckIds { dids: vec![bio] });
    assert_eq!(removed.count, 0, "no cards in Biology");
    assert!(find_deck(&deck_tree(&bridge), "Biology").is_none());
    let _: anki_proto::collection::OpChangesAfterUndo = call(&bridge, "undo", Empty {});
    let tree = deck_tree(&bridge);
    assert_eq!(find_deck(&tree, "Biology").unwrap().children.len(), 1);
}

#[test]
fn builds_rebuilds_and_empties_filtered_decks() {
    use anki_proto::decks::FilteredDeckForUpdate;
    let (_dir, bridge) = open_temp();
    add_note(&bridge, "Basic", &["one", "1"]);
    add_note(&bridge, "Basic", &["two", "2"]);
    // An empty Default deck is hidden from the tree.
    let in_default = |bridge: &Bridge| find_deck(&deck_tree(bridge), "Default").map_or(0, |d| d.total_in_deck);
    assert_eq!(in_default(&bridge), 2);

    // The filtered deck dialog: defaults for a new deck (id 0), edited, then saved,
    // which builds it.
    let mut filtered: FilteredDeckForUpdate = call(&bridge, "getOrCreateFilteredDeck", DeckId { did: 0 });
    assert_eq!(filtered.id, 0);
    filtered.name = "Cram".into();
    // Without the second filter enabled, the dialog saves only the first term.
    filtered.config.as_mut().unwrap().search_terms.truncate(1);
    let term = &mut filtered.config.as_mut().unwrap().search_terms[0];
    term.search = "deck:Default".into();
    term.limit = 1;
    let id = call::<OpChangesWithId>(&bridge, "addOrUpdateFilteredDeck", filtered).id;
    let cram = |bridge: &Bridge| find_deck(&deck_tree(bridge), "Cram").unwrap().total_in_deck;
    assert!(find_deck(&deck_tree(&bridge), "Cram").unwrap().filtered);
    assert_eq!((cram(&bridge), in_default(&bridge)), (1, 1));

    // Editing reopens the saved settings.
    let saved: FilteredDeckForUpdate = call(&bridge, "getOrCreateFilteredDeck", DeckId { did: id });
    assert_eq!(saved.config.unwrap().search_terms[0].search, "deck:Default");

    let _: OpChanges = call(&bridge, "emptyFilteredDeck", DeckId { did: id });
    assert_eq!((cram(&bridge), in_default(&bridge)), (0, 2));
    let rebuilt: anki_proto::collection::OpChangesWithCount = call(&bridge, "rebuildFilteredDeck", DeckId { did: id });
    assert_eq!((rebuilt.count, cram(&bridge)), (1, 1));
}

/// Adds a Basic note to `deck` with `tags`; returns (note id, card id).
fn add_tagged(bridge: &Bridge, deck: i64, fields: [&str; 2], tags: &[&str]) -> (i64, i64) {
    let names: NotetypeNames = call(bridge, "getNotetypeNames", Empty {});
    let ntid = names.entries.iter().find(|n| n.name == "Basic").unwrap().id;
    let mut note: Note = call(bridge, "newNote", NotetypeId { ntid });
    note.fields = fields.iter().map(|f| f.to_string()).collect();
    note.tags = tags.iter().map(|t| t.to_string()).collect();
    let added: AddNoteResponse = call(bridge, "addNote", AddNoteRequest { note: Some(note), deck_id: deck });
    let cards: anki_proto::cards::CardIds = call(bridge, "cardsOfNote", NoteId { nid: added.note_id });
    (added.note_id, cards.cids[0])
}

/// #11: the browser's searches, sorting and rows, as Klaus's browser makes them.
#[test]
fn browser_searches_and_rows() {
    use anki_proto::search::{search_node, sort_order, BrowserRow, SearchNode, SearchRequest, SearchResponse, SortOrder};
    let (_dir, bridge) = open_temp();
    let cells = create_deck(&bridge, "Biology::Cells");
    let (heart_nid, heart) = add_tagged(&bridge, 1, ["Heart", "pumps blood"], &["cardio"]);
    let (_, mito) = add_tagged(&bridge, cells, ["Mitochondria", "ATP"], &["cell::organelle"]);
    let search = |s: &str| -> Vec<i64> {
        let req = SearchRequest { search: s.into(), order: Some(SortOrder { value: Some(sort_order::Value::None(Empty {})) }) };
        let mut ids = call::<SearchResponse>(&bridge, "searchCards", req).ids;
        ids.sort();
        ids
    };
    let mut both = vec![heart, mito];
    both.sort();
    // Anki's search syntax: decks (with children), tags (hierarchical), state,
    // properties, regex, and fields.
    assert_eq!(search("deck:Biology"), [mito]);
    assert_eq!(search("tag:cell"), [mito]);
    assert_eq!(search("tag:cardio"), [heart]);
    assert_eq!(search("is:new"), both);
    assert_eq!(search("is:due"), Vec::<i64>::new());
    assert_eq!(search("prop:ivl=0"), both);
    assert_eq!(search("re:^mito"), [mito]);
    assert_eq!(search("back:ATP"), [mito]);
    // Sidebar clicks build searches with Anki's escaping.
    let node = SearchNode { filter: Some(search_node::Filter::Deck("Biology::Cells".into())) };
    let built: generic::String = call(&bridge, "buildSearchString", node);
    assert_eq!(search(&built.val), [mito]);

    // Sorting by a column, as a header click does.
    let sorted = |reverse: bool| {
        let order = SortOrder { value: Some(sort_order::Value::Builtin(sort_order::Builtin { column: "noteFld".into(), reverse })) };
        call::<SearchResponse>(&bridge, "searchCards", SearchRequest { search: "".into(), order: Some(order) }).ids
    };
    assert_eq!((sorted(false), sorted(true)), (vec![heart, mito], vec![mito, heart]));

    // Rows hold the active columns' cells.
    let cols = generic::StringList { vals: vec!["noteFld".into(), "deck".into(), "noteTags".into()] };
    let _: Empty = call(&bridge, "setActiveBrowserColumns", cols);
    let row: BrowserRow = call(&bridge, "browserRowForId", generic::Int64 { val: mito });
    let texts: Vec<_> = row.cells.iter().map(|c| c.text.as_str()).collect();
    assert_eq!(texts, ["Mitochondria", "Biology::Cells", "cell::organelle"]);

    // Notes mode: the same search returns notes, and rows are per note.
    use anki_proto::config::{config_key, SetConfigBoolRequest};
    let notes_mode = SetConfigBoolRequest { key: config_key::Bool::BrowserTableShowNotesMode as i32, value: true, undoable: false };
    let _: OpChanges = call(&bridge, "setConfigBool", notes_mode);
    let req = SearchRequest { search: "tag:cardio".into(), order: None };
    assert_eq!(call::<SearchResponse>(&bridge, "searchNotes", req).ids, [heart_nid]);
    let row: BrowserRow = call(&bridge, "browserRowForId", generic::Int64 { val: heart_nid });
    assert_eq!(row.cells[0].text, "Heart");

    // The sidebar's tag tree and columns list.
    let tags: anki_proto::tags::TagTreeNode = call(&bridge, "tagTree", Empty {});
    let names: Vec<_> = tags.children.iter().map(|t| t.name.as_str()).collect();
    assert_eq!(names, ["cardio", "cell"]);
    let columns: anki_proto::search::BrowserColumns = call(&bridge, "allBrowserColumns", Empty {});
    assert!(columns.columns.iter().any(|c| c.key == "cardDue"));
}

// ---- Sync (ADR-0007): Klaus Account sign-in against a fake klaus.ink, and sync
// against rslib's own sync server, both started in-process. ----

use anki_proto::sync::sync_collection_response::ChangesRequired;
use klaus_bridge::klaus::{sync_outcome::State as SyncState, SyncAccount, SyncOutcome};

/// One runtime for the test servers (sync server, fake klaus.ink, bridges).
fn runtime() -> &'static tokio::runtime::Runtime {
    static RT: std::sync::OnceLock<tokio::runtime::Runtime> = std::sync::OnceLock::new();
    RT.get_or_init(|| tokio::runtime::Builder::new_multi_thread().enable_all().build().unwrap())
}

/// One local sync server for the whole test binary, with a user per test so
/// parallel tests don't share a server-side Collection.
fn sync_server() -> String {
    use anki::sync::http_server::{default_ip_header, SimpleServer, SyncServerConfig};
    static URL: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    URL.get_or_init(|| {
        std::env::set_var("SYNC_USER1", "normal:secret");
        std::env::set_var("SYNC_USER2", "conflict:secret");
        std::env::set_var("SYNC_USER3", "auto:secret");
        let base_folder = tempfile::tempdir().unwrap().keep();
        runtime().block_on(async move {
            let config = SyncServerConfig { host: "127.0.0.1".parse().unwrap(), port: 0, base_folder, ip_header: default_ip_header() };
            let (addr, server) = SimpleServer::make_server(config).await.unwrap();
            tokio::spawn(server);
            format!("http://{addr}/")
        })
    })
    .clone()
}

/// A fake klaus.ink (docs/klaus-ink-sync.md) whose account `user` maps to the
/// local sync server: /oauth/authorize signs in at once and redirects back with a
/// code; /oauth/token checks the code and PKCE and returns the sync key.
fn fake_klaus_ink(user: &str) -> String {
    use axum::extract::{Form, Query, State};
    use axum::response::Redirect;
    use base64::Engine;
    use std::collections::HashMap;
    type Pending = Arc<Mutex<Option<(String, String)>>>; // (code_challenge, redirect_uri)
    // The account's sync key, as the sync server issues it.
    let (_dir, login) = open_temp();
    let req = anki_proto::sync::SyncLoginRequest { username: user.into(), password: "secret".into(), endpoint: Some(sync_server()) };
    let hkey = anki_proto::sync::SyncAuth::decode(login.call_trusted("syncLogin", &req.encode_to_vec()).unwrap().as_slice()).unwrap().hkey;
    let (email, sync_url) = (format!("{user}@example.com"), sync_server());
    let pending: Pending = Arc::default();
    let app = axum::Router::new()
        .route(
            "/oauth/authorize",
            axum::routing::get(|State(p): State<Pending>, Query(q): Query<HashMap<String, String>>| async move {
                assert_eq!((q["response_type"].as_str(), q["code_challenge_method"].as_str()), ("code", "S256"));
                *p.lock().unwrap() = Some((q["code_challenge"].clone(), q["redirect_uri"].clone()));
                Redirect::to(&format!("{}?code=the-code&state={}", q["redirect_uri"], q["state"]))
            }),
        )
        .route(
            "/oauth/token",
            axum::routing::post(move |State(p): State<Pending>, Form(f): Form<HashMap<String, String>>| async move {
                let (challenge, redirect) = p.lock().unwrap().take().expect("authorize first");
                let proof = base64::engine::general_purpose::URL_SAFE_NO_PAD
                    .encode(<sha2::Sha256 as sha2::Digest>::digest(f["code_verifier"].as_bytes()));
                assert_eq!((f["grant_type"].as_str(), f["code"].as_str()), ("authorization_code", "the-code"));
                assert_eq!((proof, f["redirect_uri"].clone()), (challenge, redirect), "PKCE proof and redirect");
                axum::Json(serde_json::json!({ "access_token": hkey, "token_type": "Bearer", "email": email, "sync_url": sync_url }))
            }),
        )
        .with_state(pending);
    runtime().block_on(async move {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move { axum::serve(listener, app).await });
        format!("http://{addr}")
    })
}

/// A served bridge (its sign-in redirect needs an origin): (base URL, token).
fn serve_bridge(bridge: Arc<Bridge>) -> (String, String) {
    let (dirs, web) = empty_web_dirs();
    let token = new_token();
    let base = runtime().block_on({
        let token = token.clone();
        async move {
            let hook: Hook = Arc::new(|_: &str, _: &[u8]| None);
            let (addr, server) = serve(bridge, web, token, hook).await.unwrap();
            tokio::spawn(async move {
                let _keep = dirs;
                server.await
            });
            format!("http://{addr}")
        }
    });
    (base, token)
}

/// The page's view of a served bridge: POST /_anki/<method> with its session cookie.
struct Page {
    base: String,
    cookie: String,
    client: reqwest::Client,
}

impl Page {
    fn open(bridge: Arc<Bridge>) -> Self {
        let (base, token) = serve_bridge(bridge);
        let client = reqwest::Client::builder().redirect(reqwest::redirect::Policy::none()).build().unwrap();
        let grant = runtime().block_on(client.get(format!("{base}/?t={token}")).send()).unwrap();
        let cookie = grant.headers()["set-cookie"].to_str().unwrap().split(';').next().unwrap().to_owned();
        Page { base, cookie, client }
    }

    fn post(&self, method: &str, body: Vec<u8>) -> (u16, Vec<u8>) {
        runtime().block_on(async {
            let res = self
                .client
                .post(format!("{}/_anki/{method}", self.base))
                .header("Content-Type", "application/binary")
                .header("Cookie", &self.cookie)
                .body(body)
                .send()
                .await
                .unwrap();
            (res.status().as_u16(), res.bytes().await.unwrap().to_vec())
        })
    }
}

/// A Klaus Collection signed in to the fake klaus.ink as `user`, the browser way:
/// open the sign-in URL and follow klaus.ink's redirect back to the bridge.
fn signed_in(user: &str) -> (tempfile::TempDir, Arc<Bridge>) {
    let (dir, bridge) = open_temp();
    let bridge = Arc::new(bridge);
    bridge.set_account_url(&fake_klaus_ink(user));
    serve_bridge(bridge.clone());
    let url: generic::String = call(&bridge, "klausAccountSignIn", Empty {});
    let page = runtime().block_on(async { reqwest::get(url.val).await.unwrap() });
    assert_eq!(page.status(), 200);
    (dir, bridge)
}

fn wait_for_media(bridge: &Bridge) {
    for _ in 0..200 {
        let status: anki_proto::sync::MediaSyncStatusResponse = call(bridge, "mediaSyncStatus", Empty {});
        if !status.active {
            return;
        }
        std::thread::sleep(std::time::Duration::from_millis(50));
    }
    panic!("media sync didn't finish");
}

fn cards_in(bridge: &Bridge) -> u32 {
    deck_tree(bridge).children.iter().map(|d| d.total_including_children).sum()
}

/// A finished sync without error.
fn done(outcome: &SyncOutcome) {
    assert_eq!((outcome.state(), outcome.error.as_str()), (SyncState::Done, ""), "{outcome:?}");
}

/// …and what the server required.
fn ok(outcome: &SyncOutcome) -> ChangesRequired {
    done(outcome);
    ChangesRequired::try_from(outcome.required).unwrap()
}

/// Klaus's and Anki's web dirs, empty (for tests that only call /_anki).
fn empty_web_dirs() -> ([tempfile::TempDir; 3], WebDirs) {
    let dirs = [tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap()];
    let web = WebDirs { klaus: dirs[0].path().into(), anki: dirs[1].path().into(), anki_static: dirs[2].path().into() };
    (dirs, web)
}

/// ADR-0007: browser sign-in (key kept out of files, forged redirects refused),
/// first upload, first-run download on a second device, normal sync both ways,
/// media, and the page's background sync path.
#[test]
fn signs_in_with_a_klaus_account_and_syncs() {
    let (dir_a, a) = signed_in("normal");
    let account: SyncAccount = call(&a, "klausSyncAccount", Empty {});
    assert_eq!(account.email, "normal@example.com");
    assert!(account.auto_sync && account.sync_media);
    // The sync key lives in the secret store, never in klaus-settings.json.
    let settings = std::fs::read_to_string(dir_a.path().join("klaus-settings.json")).unwrap();
    let profile: serde_json::Value = serde_json::from_str(&settings).unwrap();
    let keys: Vec<_> = profile["profile"].as_object().unwrap().keys().cloned().collect();
    assert_eq!(keys, ["syncUrl", "syncUser"], "{settings}");
    // A redirect that wasn't started from Klaus (wrong or reused state) is refused.
    let (_dir_x, x) = open_temp();
    let x = Arc::new(x);
    x.set_account_url(&fake_klaus_ink("normal"));
    let (base, _) = serve_bridge(x.clone());
    let _: generic::String = call(&x, "klausAccountSignIn", Empty {});
    let forged = runtime().block_on(async { reqwest::get(format!("{base}/auth/callback?code=the-code&state=forged")).await.unwrap() });
    assert_eq!(forged.status(), 400);
    assert_eq!(call::<SyncAccount>(&x, "klausSyncAccount", Empty {}).email, "");

    // Device A has a note and an image; a new account's first sync uploads it.
    add_tagged(&a, 1, ["Heart", "<img src=heart.png>"], &[]);
    let _: generic::String = call(&a, "addMediaFile", AddMediaFileRequest { desired_name: "heart.png".into(), data: b"png".to_vec() });
    let out = a.sync();
    assert!(matches!(ok(&out), ChangesRequired::FullUpload | ChangesRequired::FullSync), "{out:?}");
    done(&a.full_sync(true, Some(out.server_media_usn)));
    wait_for_media(&a);

    // Device B (empty) downloads it all on its first sync, backing itself up first.
    let (dir_b, b) = signed_in("normal");
    let out = b.sync();
    assert_eq!(ok(&out), ChangesRequired::FullDownload);
    let full = b.full_sync(false, Some(out.server_media_usn));
    done(&full);
    assert!(std::path::Path::new(&full.backup_folder).read_dir().unwrap().next().is_some(), "backup written");
    wait_for_media(&b);
    assert_eq!(cards_in(&b), 1);
    assert_eq!(std::fs::read(dir_b.path().join("collection.media/heart.png")).unwrap(), b"png");

    // A normal sync carries B's new note up…
    add_tagged(&b, 1, ["Lung", "gas exchange"], &[]);
    assert_eq!(ok(&b.sync()), ChangesRequired::NoChanges);

    // …and A pulls it down the page's way: klausSync returns at once (204), then
    // the outcome is polled until this sync's id is done.
    let page = Page::open(a.clone());
    let before = SyncOutcome::decode(page.post("klausSyncOutcome", vec![]).1.as_slice()).unwrap().id;
    assert_eq!(page.post("klausSync", vec![]).0, 204);
    let outcome = loop {
        let outcome = SyncOutcome::decode(page.post("klausSyncOutcome", vec![]).1.as_slice()).unwrap();
        if outcome.id > before && outcome.state() == SyncState::Done {
            break outcome;
        }
        std::thread::sleep(std::time::Duration::from_millis(50));
    };
    assert_eq!(ok(&outcome), ChangesRequired::NoChanges);
    assert!(!outcome.background && outcome.finished_ms > 0);
    assert_eq!(cards_in(&a), 2, "A has B's note");
}

fn notetype_names(bridge: &Bridge) -> Vec<String> {
    let mut names: Vec<_> = call::<NotetypeNames>(bridge, "getNotetypeNames", Empty {}).entries.into_iter().map(|n| n.name).collect();
    names.sort();
    names
}

/// Removes an unused notetype: a schema change, so the next sync can't merge.
fn change_schema(bridge: &Bridge, name: &str) {
    let names: NotetypeNames = call(bridge, "getNotetypeNames", Empty {});
    let ntid = names.entries.iter().find(|n| n.name == name).unwrap().id;
    let _: anki_proto::collection::OpChanges =
        Message::decode(bridge.call_trusted("removeNotetype", &NotetypeId { ntid }.encode_to_vec()).unwrap().as_slice()).unwrap();
}

/// Both devices change the schema, so the second to sync gets a real conflict
/// (FULL_SYNC: choose a side). Resolved once by downloading, once by uploading.
#[test]
fn full_sync_conflicts_resolve_in_both_directions() {
    let (_dir_a, a) = signed_in("conflict");
    let (_dir_b, b) = signed_in("conflict");
    let out = a.sync();
    done(&a.full_sync(true, Some(out.server_media_usn)));
    let out = b.sync();
    done(&b.full_sync(false, Some(out.server_media_usn)));

    // Download: B discards its own change and takes the server's (A's) version.
    change_schema(&a, "Cloze");
    add_tagged(&a, 1, ["only on A", "a"], &[]);
    change_schema(&b, "Basic (type in the answer)");
    add_tagged(&b, 1, ["only on B", "b"], &[]);
    let out = a.sync();
    assert_eq!(ok(&out), ChangesRequired::FullUpload, "only A's side changed so far");
    done(&a.full_sync(true, Some(out.server_media_usn)));
    let out = b.sync();
    assert_eq!(ok(&out), ChangesRequired::FullSync);
    done(&b.full_sync(false, Some(out.server_media_usn)));
    assert_eq!(notetype_names(&b), notetype_names(&a));
    assert_eq!(cards_in(&b), 1, "B's note gone, A's note here");

    // Upload: B keeps its own change and overwrites the server; A then takes B's version.
    change_schema(&a, "Basic (and reversed card)");
    change_schema(&b, "Basic (optional reversed card)");
    let out = a.sync();
    done(&a.full_sync(true, Some(out.server_media_usn)));
    let out = b.sync();
    assert_eq!(ok(&out), ChangesRequired::FullSync);
    done(&b.full_sync(true, Some(out.server_media_usn)));
    let out = a.sync();
    assert!(matches!(ok(&out), ChangesRequired::FullDownload | ChangesRequired::FullSync), "{out:?}");
    done(&a.full_sync(false, Some(out.server_media_usn)));
    assert_eq!(notetype_names(&a), notetype_names(&b));
    assert!(notetype_names(&a).contains(&"Basic (and reversed card)".to_string()), "A's change was overwritten");
}

/// Automatic sync: a quiet app with local changes syncs on its own; an active one
/// waits; nothing to sync means no sync; a full sync is found but left for the user.
#[test]
fn syncs_automatically_when_quiet() {
    let (_dir_a, a) = signed_in("auto");
    let (_dir_b, b) = signed_in("auto");
    let out = a.sync();
    done(&a.full_sync(true, Some(out.server_media_usn)));
    let out = b.sync();
    done(&b.full_sync(false, Some(out.server_media_usn)));

    assert!(!a.auto_sync_tick(), "nothing to sync");
    // A changed and nobody has touched the app: it syncs up on its own…
    add_tagged(&a, 1, ["auto", "synced"], &[]);
    assert!(a.auto_sync_tick());
    let out: SyncOutcome = call(&a, "klausSyncOutcome", Empty {});
    assert!(out.background && ok(&out) == ChangesRequired::NoChanges, "{out:?}");
    // B learns of it from the server, which rslib asks at most every 5 minutes
    // (B just synced, so not yet); a sync then brings it down.
    assert!(!b.auto_sync_tick(), "server checked at most every 5 minutes");
    assert_eq!(ok(&b.sync()), ChangesRequired::NoChanges);
    assert_eq!(cards_in(&b), 1);

    // While the page is in use, it waits.
    add_tagged(&a, 1, ["later", "x"], &[]);
    let page = Page::open(a.clone());
    assert_eq!(page.post("deckTree", DeckTreeRequest { now: now() }.encode_to_vec()).0, 200);
    assert!(!a.auto_sync_tick(), "app in use");
    // Quitting syncs it anyway, and finishes well within its limit.
    let started = std::time::Instant::now();
    a.sync_before_quit(std::time::Duration::from_secs(30));
    assert!(started.elapsed() < std::time::Duration::from_secs(30));
    let out: SyncOutcome = call(&a, "klausSyncOutcome", Empty {});
    assert_eq!(ok(&out), ChangesRequired::NoChanges);
    assert!(!a.auto_sync_tick(), "nothing left to sync");

    // A full sync is found once and left for the user to choose.
    change_schema(&b, "Cloze");
    assert!(b.auto_sync_tick());
    let out: SyncOutcome = call(&b, "klausSyncOutcome", Empty {});
    assert!(matches!(ok(&out), ChangesRequired::FullUpload | ChangesRequired::FullSync), "{out:?}");
    assert!(!b.auto_sync_tick(), "not asked again while it waits");
}
