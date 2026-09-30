---
name: anki-qt-dev
description: Build, debug, package, or port Anki desktop add-ons (aqt, anki module, gui_hooks, QueryOp/CollectionOp, webviews, .ankiaddon) and write Qt 6 code (Qt Core/Qt GUI concepts, PyQt via aqt.qt, or C++).
---

# Anki add-ons and Qt 6

Two knowledge bases in one skill:

- **Anki add-ons:** the full official add-on docs (https://addon-docs.ankiweb.net/, source https://github.com/ankitects/addon-docs, read 2026-09-27), the two forum porting posts they link to, and Anki's hook definition files.
- **Qt 6:** the Qt Core and Qt GUI docs for Qt 6.11 (https://doc.qt.io/qt-6/, read 2026-09-26). These are written for C++. Anki add-ons use PyQt, so apply the concepts (ownership, signals, threads, painting) but translate the syntax to Python and import everything from `aqt.qt`.

Every rule below links to its source. Lines in the references marked "(unverified, not from fetched docs)" were not confirmed in the docs: check the linked page before relying on them, and tell the user when it matters.

## Which reference to load

Load only the file that matches the task. If the `references/` folder is not installed alongside this file, fetch the source pages linked in the rules instead.

| Task | Reference |
|---|---|
| Anything about writing an Anki add-on: folders, the `anki` module, collection access, background ops, webviews, reviewer JS, config, debugging, sharing, porting | `references/anki/addon-docs-guide.md` |
| Finding the right Anki hook or filter, and its arguments | `references/anki/hooks-index.md` |
| QObject, parent/child ownership, signals/slots, events, timers, properties | `references/qt/object-model.md` |
| QThread, thread affinity, mutexes, QFuture, Qt Concurrent | `references/qt/threads.md` |
| QString, containers, implicit sharing, JSON, regex, dates, logging | `references/qt/strings-containers-data.md` |
| Files, QSettings, QProcess, IPC, plugins, permissions, translations, animation, QTimer | `references/qt/io-and-platform.md` |
| Item models, roles, proxy models | `references/qt/model-view.md` |
| QPainter, QImage/QPixmap, colors, fonts, QTextDocument, PDF output | `references/qt/gui-painting.md` |
| QWindow, screens, high DPI, OpenGL/Vulkan/QRhi, input events, shortcuts, clipboard | `references/qt/gui-windowing-input.md` |
| CMake builds, Qt 5 to Qt 6 porting (C++) | `references/qt/build-and-porting.md` |
| "Which Qt class does X?" | `references/qt/class-index.md` |

If a reference is missing or out of date, read the source: Anki hooks in https://github.com/ankitects/anki/blob/main/qt/tools/genhooks_gui.py and https://github.com/ankitects/anki/blob/main/pylib/tools/genhooks.py, Qt classes at `https://doc.qt.io/qt-6/<classname-lowercase>.html`. The hook index was generated from Anki's `main` branch, which can be ahead of the released version the user targets.

## Anki add-on rules

**Structure**

- An add-on is a folder in `addons21` containing `__init__.py`. Use only a-z and 0-9 in the folder name. Source: https://addon-docs.ankiweb.net/addon-folders.html
- Add-ons load at startup before any profile or collection exists. Never touch `mw.col` at import time: do it in an action or a hook such as `main_window_did_init` or `profile_did_open`. Source: https://addon-docs.ankiweb.net/the-anki-module.html, `references/anki/hooks-index.md`
- Never store user data in the add-on folder, since upgrades delete it. Use `config.json` with `mw.addonManager.getConfig/writeConfig(__name__)`, or the `user_files/` folder. Source: https://addon-docs.ankiweb.net/addon-config.html

**Connecting to Anki**

- Use new-style hooks (`from aqt import gui_hooks`, `gui_hooks.<name>.append(fn)`). A filter must return its first argument. Monkey patching is a fragile last resort; if you must, use `anki.hooks.wrap`. Source: https://addon-docs.ankiweb.net/hooks-and-filters.html, https://addon-docs.ankiweb.net/monkey-patching.html
- Type-hint hook callbacks and run mypy against `aqt[qt6]` to catch wrong signatures. Source: https://addon-docs.ankiweb.net/mypy.html

**Collection access**

- Use pylib methods (`col.get_note`, `col.update_note`, `col.find_cards`, `col.decks`, `col.models`) instead of raw SQL. They mark changes for sync and block some invalid data. Raw `col.db` writes don't sync, and never change the schema. Source: https://addon-docs.ankiweb.net/the-anki-module.html
- `card.flush()`, `note.flush()`, `col.save()`, `col.autosave()` and `col.checkpoint()` are obsolete. Source: https://forums.ankiweb.net/t/porting-tips-for-anki-23-10/35916

**Threads (Anki's own tools come first)**

- Slow work goes in `QueryOp` (reads, network) or `CollectionOp` (undoable writes). Never call Qt/UI code inside the op: gather UI values first, update the UI in `success`, and use `mw.taskman.run_on_main()` for progress updates. Source: https://addon-docs.ankiweb.net/background-ops.html
- Ops are serialized by default. Call `.without_collection()` for work that doesn't touch the collection (such as API calls) so it doesn't block other ops. Source: https://addon-docs.ankiweb.net/background-ops.html

**Qt inside Anki**

- Import Qt from `aqt.qt`, never from `PyQt6`/`PyQt5` directly, and use fully scoped enums. Source: https://addon-docs.ankiweb.net/qt.html, https://forums.ankiweb.net/t/porting-tips-for-anki-23-10/35916
- Keep a reference to parentless top-level widgets (for example `mw.myWidget = widget`), or Python garbage-collects them. Source: https://addon-docs.ankiweb.net/qt.html

**Webviews**

- Inject HTML/CSS/JS with `webview_will_set_content`, serve files with `mw.addonManager.setWebExports()` under `/_addons/<package>/`, and receive messages from JS's `pycmd()` with `webview_did_receive_js_message`. Source: https://addon-docs.ankiweb.net/hooks-and-filters.html
- JS evaluation is asynchronous; use `evalWithCallback()` when you need a result. Source: https://addon-docs.ankiweb.net/porting2.0.html
- For card HTML use the `card_will_show` filter, and run DOM code in `onUpdateHook`/`onShownHook`, because cards fade in. Source: https://addon-docs.ankiweb.net/reviewer-javascript.html

**Debugging and shipping**

- stderr output pops up an error for the user; `assert` is off in release builds. Debug webviews with `QTWEBENGINE_REMOTE_DEBUGGING=8080`. Source: https://addon-docs.ankiweb.net/debugging.html
- Third-party packages must be bundled (C extensions per platform). Source: https://addon-docs.ankiweb.net/python-modules.html
- Package with `cd myaddon && zip -r ../myaddon.ankiaddon *` (no top-level folder, no `__pycache__`). Outside AnkiWeb, add `manifest.json` with `package` and `name`. Source: https://addon-docs.ankiweb.net/sharing.html

## Qt 6 rules

**Objects and ownership**

- QObject is an identity, not a value: copy constructor and assignment are disabled. Store and pass QObjects by pointer, never by value. Source: https://doc.qt.io/qt-6/object.html
- A QObject created with a parent is deleted when the parent is deleted. For stack objects (C++), create the parent before the child, or the parent will delete a stack object and cause a double delete. Source: https://doc.qt.io/qt-6/objecttrees.html
- In C++, any class that declares signals, slots, or properties needs the `Q_OBJECT` macro and moc (AUTOMOC, which `qt_standard_project_setup()` enables). Source: https://doc.qt.io/qt-6/metaobjects.html, https://doc.qt.io/qt-6/qt-standard-project-setup.html

**Signals and slots**

- In C++, prefer the function-pointer `connect()` syntax: it is checked at compile time. The string-based `SIGNAL()`/`SLOT()` form is only checked at run time. Source: https://doc.qt.io/qt-6/signalsandslots-syntaxes.html
- When connecting to a lambda, pass a context object so the connection is removed when that object is destroyed, and the lambda runs in the context object's event loop. Source: https://doc.qt.io/qt-6/qobject.html

**Threads**

- A QObject lives in the thread where it was created. `moveToThread()` changes that for the object and its children, and an object with a parent cannot be moved. Source: https://doc.qt.io/qt-6/threads-qobject.html
- Do not delete a QObject from a thread other than the one it lives in: use `deleteLater()`. Source: https://doc.qt.io/qt-6/threads-qobject.html
- `Qt::AutoConnection` acts as a direct connection within one thread and a queued connection across threads. Source: https://doc.qt.io/qt-6/threads-qobject.html
- GUI classes (notably QWidget and its subclasses) can only be used from the main thread. Painting with QPainter on a QImage can be done in another thread. Source: https://doc.qt.io/qt-6/threads-qobject.html, https://doc.qt.io/qt-6/qimage.html

**Strings and containers (C++)**

- Qt containers are implicitly shared (copy-on-write); non-const access can trigger a detach. Source: https://doc.qt.io/qt-6/implicit-sharing.html, https://doc.qt.io/qt-6/containers.html
- `QStringView` and `QAnyStringView` do not own their data: never let them outlive the string they view. Source: https://doc.qt.io/qt-6/qstringview.html

**Painting**

- When the paint device is a widget, QPainter can only be used inside `paintEvent()`. Keep `save()`/`restore()` balanced; `QPainterStateGuard` (Qt 6.9+) does this with RAII. Source: https://doc.qt.io/qt-6/qpainter.html, https://doc.qt.io/qt-6/qpainterstateguard.html
- QImage is designed for I/O and pixel access, QPixmap for showing images on screen. Source: https://doc.qt.io/qt-6/qimage.html
- High-DPI scaling is on by default in Qt 6 (the porting guide says "always enabled"; the high-DPI page documents `QT_ENABLE_HIGHDPI_SCALING=0` to disable it on some platforms). Code works in device-independent pixels. Source: https://doc.qt.io/qt-6/highdpi.html, https://doc.qt.io/qt-6/portingguide.html

## Known gaps

- Anki's docs say they are "not a comprehensive guide"; much of the API is only in Anki's source (`pylib/anki`, `qt/aqt`). Source: https://addon-docs.ankiweb.net/support.html
- The Qt references were built from summaries of doc pages, not verbatim copies; check exact signatures on the class page. Qt Widgets, Qt WebEngine and Qt Quick are not covered, and PyQt-specific APIs are not documented here.
- The Qt class index lists 277 Qt Core and 208 Qt GUI classes (nested types left out).
- Links not checked because they block automated fetching: the anki-addons demo folders on GitHub, the PyQt6 docs, and ankiweb.net add-on pages.
- Two Anki doc code samples contain typos (noted in the guide). The undo-queue limit of 30 comes from a 2021 post and may be outdated.
