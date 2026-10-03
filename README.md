# KlausNote

Anki + PDF editor + Obsidian in one note-taking tool. AGPL-3.0.

| Folder | What |
| --- | --- |
| [`app/`](app) | KlausNote desktop (Tauri 2, Rust, SvelteKit on Anki's rslib) and KlausNote Web (note.klaus.so) |
| [`addon/`](addon) | KlausNote for Anki, the add-on (package `klaus_note`) |
| [`website/`](website) | klaus.so, the marketing and SEO site |
| [`auth/`](auth) | The Klaus account, an OIDC provider at app.klaus.so (no code yet) |

Each folder keeps its own README, build and tests. Issues for every folder live here; add-on issues carry the `addon` label. Release tags are prefixed by folder: `app-v*`, `addon-v*`.

Secrets and production config never go in this repository; hosted-only parts live in the private `klaus-infra` repo.
