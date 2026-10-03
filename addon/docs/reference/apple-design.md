# Apple design application

Applied from the user-supplied apple-design skill on 2026-09-19.

## Direction

Keep the study material central. Use system typography, restrained accent color,
quiet secondary actions and predictable native navigation. Students should see
common tasks first and technical controls through a labeled disclosure.

## Surface coverage

| Surface | Application |
| --- | --- |
| Preferences and addon dialogs | Neutral utility buttons; explicit default action; 600-weight page headings; 12px descriptions; grouped labels; reserved focus borders. |
| Local models | Quiet Advanced disclosure with direction indicator and accessible name; basic student tasks stay visible. |
| Library and constellation map | Preserve full-width selection, splitter behavior, semantic retention colors and direct map manipulation; shared viewer controls receive the same focus treatment. |
| Native PDF panel and find bar | Immediate pressed states and visible keyboard focus without a changing border width. |
| PDF web viewer | Floating annotation material, solid fallback, increased contrast and keyboard focus; preserve document typography and annotation coordinates. |
| Dashboard editing | Immediate control feedback; honor both Anki reduced motion and the OS preference; solid material for reduced transparency or increased contrast. |
| Heatmap controls | Shared press and keyboard focus behavior; preserve activity color meanings. |
| Top, bottom and reviewer toolbars | Shared scoped focus rings, press feedback and increased contrast; preserve review scheduling colors. |
| Add Cards and Browse editor | Native utility hierarchy and scoped web-toolbar feedback; never restyle user-authored card content. |
| Statistics | Preserve graph semantics and the existing shared structural palette; native window controls use the same utility hierarchy. |

## Interaction rules

- Press feedback starts on pointer-down through `:active` or Qt `:pressed`.
- Native scrolling, docking, splitters and sliders keep native direct manipulation.
- No input lock or artificial timing delay is introduced.
- Dashboard drag remains attached to the pointer; no decorative spring is added.
- Reduced motion keeps status and focus feedback while suppressing dashboard jiggle.
- Web translucency belongs only to floating controls with content behind them.
- Qt surfaces remain opaque: QSS does not provide a portable backdrop blur.
- Keep transparent borders reserved at rest where focus recolors the border.

## Verification

The new contract suite is `tests/test_apple_design.py`. Existing theme, settings,
dashboard and PDF suites cover the shared implementation. Actual Anki is restarted
after each production edit round for visual and interaction checks. Run results
and live screenshots are recorded in the task's verification report.

## Transcription boundary

The visual design does not change the transcription backend. Klaus currently uses
whisper.cpp. Ollama lists Gemma 4 E2B/E4B with audio input, so a shared Ollama model
workflow is possible, but needs an adapter and real audio validation before it can
replace the current backend. See [Ollama's model specification](https://ollama.com/library/gemma4).
