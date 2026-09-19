# Handoff: local-model reversion completed locally

Updated 2026-09-19. D1-D6 implementation and their task/plan reviews are complete.
The final integration documentation and package evidence are in the
[completion report](../reports/2026-09-19-local-model-reversion.md). This is local
work, not a merge, push, publication or live Anki/Desktop verification.

## Current checkout

Work in `/Users/pyamzi/Documents/Github/Klaus/Klaus Addon` on
`claude/repo-root-casing`. The former KlausMate-Context paths are historical.
The Anki add-on symlink resolves to this checkout's `klausmate/`; the final
recursive compile gate verifies both paths. The package includes the combined
checkout with separately requested, unstaged logo changes. Board and logo files
remain outside the final documentation commit.

## Completed work

- D1-D3: subscription service, reasoning judge and embedded assistant removed;
  demolition reviewed over `a1d56fd..125450f`.
- D6: local whisper.cpp adapter, recorder and settings, including configured-shell
  discovery fix, completed through `348f071`.
- D4: managed Ollama, local embeddings, config migration and Preferences controls,
  including lifecycle and automatic-port persistence fixes, through `b3633cf`.
- D5: private discovery, standalone stdio bridge, active-page text/image tool and
  Preferences copy configuration, including publication race, Windows API and
  UTF-8 fixes, through `63e11ce`.
- Integration: guidance inversion `e84663d` and `93bd7b1`; final actual-state
  user/agent documentation, aggregate checks and local package are documented in
  the completion report. Whole-project review and scoped re-review approved final
  feature code `eff3f9e`, including failed-PDF viewer-context cleanup; no blocking
  findings remain. Only review-status documentation changed afterward.

## Installation verification next

Install the local archive using Tools → Add-ons → Install from file, then restart
Anki. Follow [the setup guide](../../../README.md): configure Local models, explicitly
install/start Ollama and Pull an embedding model, select and Save; configure a
whisper.cpp executable/model/language for recording. Use disposable data for live
verification. No runtime/model download or microphone test was performed in the
final integration task.

For an external client, install a separate Python 3.9+ and use External clients →
Copy configuration. Merge the copied entry into the client's configuration yourself,
restart the client and keep Anki's profile open. Check read-only current_page first;
then verify Anki approval for writes with disposable notes. The client may send
requested context to its provider. Klaus did not alter external-client settings.

Remaining native checks: Anki UI and microphone lifecycle, real Desktop interaction,
Windows discovery-file ACL privacy, native Linux runtime extraction/converters and
installation behavior. Automated coverage and spike evidence do not establish those.
See the completion report for all evidence and limits.

## Recovery evidence and retained rules

Read the ignored `.superpowers/sdd/` progress ledgers and task reports for the
2026-09-18 demolition and 2026-09-19 transcription, Ollama, external-MCP and
integration plans. The completion report preserves the deduplicated decision log,
including the Task 6 deletion-order correction and honest historical test attribution.
Historical spec bodies remain unchanged and their dated supersession notices remain.

Keep every test-file run independent and aggregate failures without an early break.
Use scratch fixtures, never real `user_files/`, `meta.json`, collection or microphone.
Use the board CLI for coordination and stage only owned files. Do not push or merge.

Retain this handoff and the ignored recovery workspaces until the entire project is
merged. The original handoff's deletion condition has not been met.
