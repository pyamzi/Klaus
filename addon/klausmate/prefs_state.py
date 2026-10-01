"""The Preferences dialog's value state — one aqt-free machine.

Spec: docs/superpowers/specs/2026-09-30-prefs-state-design.md.

Interface: ``PrefsState.from_config(cfg)`` seeds a baseline from the
stored config (normalised); ``set(key, value)`` is the user's edit (an
edit equal to the baseline drops the pending value); ``reseed(key,
value)`` is a stored value that changed underneath (the baseline moves,
nothing counts as an edit); ``get``/``view``/``pending``/``dirty`` read;
``discard()`` drops every pending value; ``commit()`` returns the
``Commit(patch, effects)`` the shell writes and runs, and moves the
baseline. ``dirty`` is a fact — ``view() != baseline`` — never a flag.

Effects are a pure function of (baseline, view), in ONE fixed order:
``("index_sweep", prev_signature)``, ``("threshold_changed", old,
new)``, ``("anki_theme", value)``, ``("appearance",)``. A clean commit is ``Commit({}, [])``.

The shell (manage_models.py) owns the widgets, the prompts, the live
preview and the operations; this module knows nothing of Qt.
"""
from __future__ import annotations

import copy
from typing import Any, Callable, NamedTuple

from . import background, dashboard, embeddings, theme

DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
# retention.DEFAULT_THRESHOLD, spelled here because retention imports aqt;
# tests/test_prefs_state.py pins the two equal.
DEFAULT_THRESHOLD = 0.45
_SPEC_FIELDS = ("mode", "color", "image", "fit", "blur", "wash", "grad_x", "grad_y", "grad_size", "gradients")
_REVIEWER_FIELDS = tuple(f for f in _SPEC_FIELDS if f != "blur")  # the study screen has no blur
_INT_FIELDS = ("blur", "wash", "grad_x", "grad_y", "grad_size")


class Commit(NamedTuple):
    patch: dict
    effects: list


def _endpoint(value: Any) -> str:
    return str(value or "").strip() or DEFAULT_ENDPOINT


def _model(value: Any) -> str:
    return str(value or "").strip()


def _threshold(value: Any) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD


def _accent(value: Any) -> str:
    name = str(value or "ocean")
    return name if name in theme.COLOR_THEMES or name == theme.CUSTOM_THEME else "ocean"


def _custom_colour(value: Any) -> str:
    value = str(value or "")
    return value if theme.is_hex_colour(value) else theme.DEFAULT_CUSTOM_COLOR


def _spec(prefix: str) -> Callable[[Any], dict]:
    def norm(value: Any) -> dict:
        # A spec is a VALUE: validated once at seed (background.resolve in
        # from_config) and deep-copied on every set. Re-validating an edit
        # here rewrote "image with no image yet" to theme the instant the
        # user picked Image, so Choose Image… could never appear (review,
        # 2026-10-01); the painters resolve an empty image to theme anyway.
        return copy.deepcopy(dict(value or {}))
    return norm


def _anki_theme(value: Any) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return 0
    return v if v in (0, 1, 2) else 0


def _bool(default: bool) -> Callable[[Any], bool]:
    def norm(value: Any) -> bool:
        return default if value is None else bool(value)
    return norm


# key -> (default, normaliser)
_SPEC: dict[str, tuple[Any, Callable[[Any], Any]]] = {
    "image_crop_enabled": (True, _bool(True)),
    "endpoint": (DEFAULT_ENDPOINT, _endpoint),
    "embedding_model": ("", _model),
    "runtime_auto_setup": (True, _bool(True)),
    "pdf_match_threshold": (DEFAULT_THRESHOLD, _threshold),
    # Appearance: the two background specs are VALUES (equality-compared
    # dicts) so dirty has one source of truth; anki_theme is a pseudo-key
    # the shell seeds from mw.pm.theme() and never reaches the patch.
    "klausbook_design": (False, lambda v: v is True),  # corrupt reads OFF (background.design_enabled's rule)
    "color_theme": ("ocean", _accent),
    "color_theme_custom": (theme.DEFAULT_CUSTOM_COLOR, _custom_colour),
    "background": (None, _spec("background")),
    "reviewer_background": (None, _spec("reviewer_background")),
    "anki_theme": (0, _anki_theme),
    # Bar size: previewed live like the rest of Appearance (the bars are
    # judged by eye), so it rides the appearance preview and effect.
    "bar_scale": (dashboard.BAR_SCALE_DEFAULT, lambda v: dashboard.bar_scale_from_cfg({"bar_scale": v})),
}
KEYS: tuple[str, ...] = tuple(_SPEC)
APPEARANCE_KEYS: tuple[str, ...] = ("klausbook_design", "color_theme", "color_theme_custom",
                                    "background", "reviewer_background", "anki_theme", "bar_scale")
PSEUDO_KEYS: tuple[str, ...] = ("anki_theme",)


def flatten_appearance(view: dict) -> dict:
    """The ``background_*`` / ``reviewer_background_*`` keys plus the
    accent pair, the design gate and ``bar_scale``, exactly as the dialog
    writes them (and as its live preview reads them): ``int()`` on
    blur/wash and the gradient geometry for BOTH screens, no reviewer
    blur, never ``heatmap_enabled`` or ``color2``."""
    out: dict = {}
    for prefix, fields in (("background", _SPEC_FIELDS), ("reviewer_background", _REVIEWER_FIELDS)):
        spec = view.get(prefix) or {}
        for f in fields:
            v = spec.get(f)
            if f == "gradients":
                v = [dict(g) for g in (v or [])]
            elif f in _INT_FIELDS:
                v = int(v or 0)
            out[f"{prefix}_{f}"] = v
    out["color_theme"] = view.get("color_theme", "ocean")
    out["color_theme_custom"] = view.get("color_theme_custom", theme.DEFAULT_CUSTOM_COLOR)
    out["klausbook_design"] = bool(view.get("klausbook_design"))
    out["bar_scale"] = dashboard.bar_scale_from_cfg(view)
    return out


class PrefsState:
    def __init__(self, baseline: dict) -> None:
        self._baseline: dict = {k: baseline[k] for k in KEYS}
        self._pending: dict = {}

    @classmethod
    def from_config(cls, cfg: dict) -> "PrefsState":
        cfg = cfg or {}
        base = {}
        for key, (default, norm) in _SPEC.items():
            if key in ("background", "reviewer_background"):
                base[key] = background.resolve(cfg, prefix=key)
            else:
                base[key] = norm(cfg[key]) if key in cfg else default
        return cls(base)

    # ── reads ──
    def get(self, key: str) -> Any:
        self._known(key)
        return copy.deepcopy(self._pending[key] if key in self._pending else self._baseline[key])

    def view(self) -> dict:
        out = dict(self._baseline)
        out.update(self._pending)
        return copy.deepcopy(out)

    def pending(self) -> dict:
        return copy.deepcopy(self._pending)

    @property
    def dirty(self) -> bool:
        return bool(self._pending)

    # ── writes ──
    def set(self, key: str, value: Any) -> None:
        """The user's edit."""
        self._known(key)
        value = _SPEC[key][1](value)
        if value == self._baseline[key]:
            self._pending.pop(key, None)
        else:
            self._pending[key] = copy.deepcopy(value)

    def reseed(self, key: str, value: Any) -> None:
        """A stored value that changed underneath: the baseline moves and
        a pending edit equal to it is no longer an edit."""
        self._known(key)
        self._baseline[key] = _SPEC[key][1](value)
        if key in self._pending and self._pending[key] == self._baseline[key]:
            del self._pending[key]

    def discard(self) -> None:
        self._pending.clear()

    def commit(self) -> Commit:
        before, after = dict(self._baseline), self.view()
        patch = dict(self._pending)
        effects: list = []
        if embeddings.index_signature(before) != embeddings.index_signature(after):
            effects.append(("index_sweep", embeddings.index_signature(before)))
        if "pdf_match_threshold" in patch:
            patch["_threshold_user_set"] = True
            effects.append(("threshold_changed", before["pdf_match_threshold"], after["pdf_match_threshold"]))
        if "anki_theme" in patch:
            effects.append(("anki_theme", after["anki_theme"]))
        if any(k in patch for k in APPEARANCE_KEYS if k not in PSEUDO_KEYS):
            flat = flatten_appearance(after)
            for key in ("background", "reviewer_background"):
                if key in patch:
                    del patch[key]
                    patch.update({k: v for k, v in flat.items() if k.startswith(key + "_")})
            effects.append(("appearance",))
        for key in PSEUDO_KEYS:
            patch.pop(key, None)
        self._baseline = {k: after[k] for k in KEYS}
        self._pending.clear()
        return Commit(patch, effects)

    @staticmethod
    def _known(key: str) -> None:
        if key not in _SPEC:
            raise KeyError(key)
