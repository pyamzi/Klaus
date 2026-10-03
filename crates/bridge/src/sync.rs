//! Collection sync through the Klaus Account (ADR-0007; contract in
//! docs/klaus-ink-sync.md). The protocol is Anki's, so sync itself is aqt/sync.py's
//! flow; profile keys match Anki's where it has them (syncUser, autoSync, syncMedia).
//! One rule, [`Bridge::should_auto_sync`] (Anki's can_auto_sync), gates every
//! unattended sync: on open, the minute tick and quit.

use std::sync::{Arc, Mutex};

use anki_proto::backend::{backend_error, BackendError};
use prost::Message;

use crate::{klaus, path_str, Bridge, CallError};

const DEFAULT_SYNC_URL: &str = "https://sync.klaus.ink/";
/// Automatic sync starts only after this long without page activity: a sync holds
/// the Collection for its network round-trip, which would stall reviewing.
const QUIET_MS: i64 = 30_000;

pub(crate) fn now_ms() -> i64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_millis() as i64)
}

/// The sync half of [`Bridge`].
#[derive(Default)]
pub(crate) struct Sync {
    /// The latest sync (page-started or automatic), for `klausSyncOutcome`.
    pub(crate) outcome: Mutex<klaus::SyncOutcome>,
    /// When the page last did something (Unix ms); automatic sync waits for quiet.
    pub(crate) last_activity: std::sync::atomic::AtomicI64,
}

impl Bridge {
    pub fn sync_account(&self) -> klaus::SyncAccount {
        let flag = |key: &str| self.profile(key).as_bool().unwrap_or(true);
        let signed_in = self.account.sync_key().is_some();
        klaus::SyncAccount {
            email: if signed_in { self.profile("syncUser").as_str().unwrap_or_default().into() } else { String::new() },
            auto_sync: flag("autoSync"),
            sync_media: flag("syncMedia"),
        }
    }

    /// Anki's can_auto_sync: whether unattended syncs (open, tick, quit) may run.
    pub fn should_auto_sync(&self) -> bool {
        let account = self.sync_account();
        !account.email.is_empty() && account.auto_sync
    }

    fn sync_auth(&self) -> Option<anki_proto::sync::SyncAuth> {
        let endpoint = self.profile("syncUrl").as_str().unwrap_or(DEFAULT_SYNC_URL).to_owned();
        Some(anki_proto::sync::SyncAuth { hkey: self.account.sync_key()?, endpoint: Some(endpoint), io_timeout_secs: None })
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
            message: "Sign in to your Klaus Account to sync.".into(),
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
        let mut outcome = self.sync.outcome.lock().unwrap();
        if outcome.state() == klaus::sync_outcome::State::Running {
            return None;
        }
        let id = outcome.id + 1;
        *outcome = klaus::SyncOutcome { state: klaus::sync_outcome::State::Running as i32, id, background, ..Default::default() };
        Some(id)
    }

    fn end_sync(&self, id: u32, background: bool, result: klaus::SyncOutcome) {
        *self.sync.outcome.lock().unwrap() = klaus::SyncOutcome { id, background, finished_ms: now_ms(), ..result };
    }

    pub fn sync_running(&self) -> bool {
        self.sync.outcome.lock().unwrap().state() == klaus::sync_outcome::State::Running
    }

    /// Starts klausSync / klausFullSync on its own thread and returns at once: a
    /// sync can take minutes, longer than a request should stay open.
    pub(crate) fn start_sync(self: &Arc<Self>, method: &str, input: &[u8]) -> Result<(), CallError> {
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
    pub(crate) fn touch(&self) {
        self.sync.last_activity.store(now_ms(), std::sync::atomic::Ordering::Relaxed);
    }

    /// One step of automatic sync, run about once a minute: when signed in, with
    /// auto sync on, nothing running, the page quiet, and Anki's syncStatus saying
    /// there's something to sync (local changes, checked for free; server changes,
    /// asked at most every 5 minutes). A full sync it finds is left for the page to
    /// ask about. Returns whether it synced.
    pub fn auto_sync_tick(&self) -> bool {
        let quiet = now_ms() - self.sync.last_activity.load(std::sync::atomic::Ordering::Relaxed) >= QUIET_MS;
        let Some(auth) = self.sync_auth() else { return false };
        if !self.should_auto_sync() || !quiet {
            return false;
        }
        let pending_full = {
            let outcome = self.sync.outcome.lock().unwrap();
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
    /// loads); the page sees it through klausSyncOutcome. Returns whether one started.
    pub fn sync_in_background(self: &Arc<Self>) -> bool {
        if !self.should_auto_sync() {
            return false;
        }
        let Some(id) = self.begin_sync(true) else { return false };
        let bridge = Arc::clone(self);
        std::thread::spawn(move || {
            let result = bridge.sync();
            bridge.end_sync(id, true, result);
        });
        true
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
        if !self.should_auto_sync() {
            return;
        }
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
