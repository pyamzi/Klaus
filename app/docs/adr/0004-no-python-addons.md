# No Anki Python add-ons in Klaus

Klaus does not embed a Python interpreter or run Anki's Python/Qt add-ons (AMBOSS, AnkiHub, the Klaus Addon itself). Anything users need becomes built in; a JavaScript/Svelte plugin system may come after v1. Recorded so nobody tries to make `aqt` add-ons load inside a Tauri app.
