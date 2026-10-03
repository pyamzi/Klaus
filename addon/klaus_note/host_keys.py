"""Keyboard scoping for the single window (spec
docs/superpowers/specs/2026-09-30-single-window-design.md, "Keyboard").

Anki's review / overview / deck-list keys are window-scoped QShortcuts on
the main window (``mw.stateShortcuts``, set through ``setStateShortcuts``).
Once Browse and the editors live in that window, two things go wrong: an
action of Browse's that shares a key with a review shortcut makes Qt fire
NEITHER (an ambiguous shortcut is a dead key), and space or a letter typed
into an Add field would answer the current card.

Two mechanisms, both public-API only:

- ``Recorder``: the keys of the current state, taken from
  ``state_shortcuts_will_change``; ``suspend``/``resume`` disable and
  re-enable every QShortcut in ``mw.stateShortcuts`` when the tab changes
  (never ``clearStateShortcuts``/``setStateShortcuts`` — re-setting re-fires
  the hook, and an add-on appending there would append again every time);
  ``apply`` re-disables the fresh shortcuts a state change installs while
  the Browse tab is active.
- ``OverrideFilter``: an application-level ``ShortcutOverride`` filter;
  while focus is inside the right dock, a key in the recorded set is
  accepted, so it reaches the editor as typing and never the shortcut map.
"""
from __future__ import annotations

from collections.abc import Callable

from aqt.qt import QEvent, QKeySequence, QObject, Qt

_PORTABLE = QKeySequence.SequenceFormat.PortableText


def normalize(key) -> str:
    """One spelling per key: ``" "`` → ``"Space"``, ``Qt.Key`` members and
    strings alike through ``QKeySequence``."""
    if key == " ":
        return "Space"
    if isinstance(key, Qt.Key):
        return QKeySequence(int(key)).toString(_PORTABLE)
    return QKeySequence(str(key)).toString(_PORTABLE)


def event_key(event) -> str:
    return QKeySequence(event.keyCombination()).toString(_PORTABLE)


class Recorder:
    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.suspended = False

    def record(self, state: str, shortcuts: list) -> None:
        keys = set()
        for entry in shortcuts:
            try:
                keys.add(normalize(entry[0]))
            except Exception:  # noqa: BLE001
                continue
        self.keys = keys

    def apply(self, mw) -> None:
        for scut in getattr(mw, "stateShortcuts", None) or []:
            try:
                scut.setEnabled(not self.suspended)
            except RuntimeError:
                pass

    def suspend(self, mw) -> None:
        self.suspended = True
        self.apply(mw)

    def resume(self, mw) -> None:
        self.suspended = False
        self.apply(mw)


class OverrideFilter(QObject):
    def __init__(self, recorder: Recorder, focus_in_dock: Callable[[], bool]) -> None:
        super().__init__()
        self._recorder = recorder
        self._focus_in_dock = focus_in_dock

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        try:
            if event.type() != QEvent.Type.ShortcutOverride:
                return False
            if self._recorder.suspended or not self._focus_in_dock():
                return False
            if event_key(event) in self._recorder.keys:
                event.accept()
                return True
        except Exception:  # noqa: BLE001
            return False
        return False


def setup(mw, focus_in_dock: Callable[[], bool]) -> Recorder:
    from aqt import gui_hooks
    from aqt.qt import QApplication

    recorder = Recorder()
    gui_hooks.state_shortcuts_will_change.append(recorder.record)
    gui_hooks.state_did_change.append(lambda new, old: recorder.apply(mw))
    flt = OverrideFilter(recorder, focus_in_dock)
    app = QApplication.instance()
    if app is not None:
        app.installEventFilter(flt)
    recorder.filter = flt  # keep the filter alive with the recorder
    return recorder
