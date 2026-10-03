# Klaus Note Website board

<!-- Source of truth for all agent work. State changes (claim/move/comment)
     MUST go through board/board.py so they are serialized by its lockfile.
     Direct edits to this file: card *body* prose only, by the orchestrator
     or designer. See klaus-note/addon/context/ROLES.md. -->

## Backlog

## Ready

## Doing

## Review

## Done

### KW-001: Rename 'Klaus Addon' to 'Klaus Note for Anki' in site copy and wordmark
owner: claude-website
priority: P2
created: 2026-10-02
claimed: 2026-10-02

The add-on package and UI are renamed (Addon dde58f3). The site still says 'Klaus Addon' in +page.svelte, privacy, ReviewCard and Wordmark.svelte (whose 'for Anki' suffix would double up). Needs a design pass, not a find-and-replace.

#### Comments
- [2026-10-02 claude-website] Done in 62b6063, live on klausnote.com: app is KlausNote; add-on lockup is KlausNote + Anki tag (reads 'KlausNote for Anki'); copy says 'KlausNote for Anki'; og.png re-rendered.
