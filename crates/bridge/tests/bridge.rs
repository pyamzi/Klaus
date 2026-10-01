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
use anki_proto::notetypes::{NotetypeId, NotetypeNames};
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
    let untrusted = format!(
        "script-src {o}/_anki/ {o}/_app/ {o}/native-dialogs.js {o}/anki-host.js 'sha256-abc='; form-action 'none'; frame-ancestors 'none'"
    );
    assert_eq!(csp("/editor/?mode=add").await, untrusted);
    assert_eq!(csp("/image-occlusion/Users/me/a.png").await, untrusted);
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
