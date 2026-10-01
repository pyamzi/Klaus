"""The Preferences state machine (klausmate/prefs_state.py), spec
docs/superpowers/specs/2026-09-30-prefs-state-design.md.

Run: PYTHONDONTWRITEBYTECODE=1 python3 tests/test_prefs_state.py
"""
from __future__ import annotations

import importlib
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()


def raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception:  # noqa: BLE001
        return False
    return False


ps = importlib.import_module("klausmate.prefs_state")
embeddings = importlib.import_module("klausmate.embeddings")

section("seeding and normalisation")
st = ps.PrefsState.from_config({"endpoint": " http://x:1 ", "embedding_model": "m",
                                "pdf_match_threshold": 0.456, "pdf_renderer": "weird"})
check("seed normalises endpoint", st.get("endpoint") == "http://x:1")
check("seed rounds the threshold", st.get("pdf_match_threshold") == 0.46)
check("seed coerces an unknown renderer", st.get("pdf_renderer") == "native")
check("missing keys take defaults", st.get("image_crop_enabled") is True and st.get("runtime_auto_setup") is True)
check("the threshold default is retention's", ps.DEFAULT_THRESHOLD == importlib.import_module("klausmate.retention").DEFAULT_THRESHOLD == 0.45
      and ps.PrefsState.from_config({}).get("pdf_match_threshold") == 0.45)
check("a fresh state is clean", st.dirty is False and st.pending() == {} and st.commit() == ps.Commit({}, []))

section("set, reseed, discard")
st.set("endpoint", "")
check("empty endpoint becomes the default and is an edit", st.get("endpoint") == ps.DEFAULT_ENDPOINT and st.dirty)
st.set("endpoint", "http://x:1")
check("setting back to baseline drops the pending value", st.dirty is False and st.pending() == {})
st.set("embedding_model", "n")
st.reseed("endpoint", "http://y:2")
check("reseed moves the baseline without an edit",
      st.get("endpoint") == "http://y:2" and st.pending() == {"embedding_model": "n"})
st.set("endpoint", "http://z:3")
st.reseed("endpoint", "http://z:3")
check("reseed to the pending value drops it", "endpoint" not in st.pending() and st.get("endpoint") == "http://z:3")
check("set on an unknown key raises", raises(KeyError, lambda: st.set("nope", 1)))
check("reseed on an unknown key raises", raises(KeyError, lambda: st.reseed("nope", 1)))

section("commit: changed keys only, effects in the fixed order")
st.set("pdf_match_threshold", 0.6)
st.set("pdf_renderer", "pdfjs")
c = st.commit()
check("commit writes changed keys only, threshold with its user-set mark",
      c.patch == {"embedding_model": "n", "pdf_match_threshold": 0.6, "_threshold_user_set": True, "pdf_renderer": "pdfjs"},
      str(c.patch))
check("effects in the fixed order",
      c.effects == [("index_sweep", embeddings.index_signature({"embedding_model": "m"})),
                    ("threshold_changed", 0.46, 0.6), ("renderer_restart",)], str(c.effects))
check("commit moves the baseline", st.dirty is False and st.get("embedding_model") == "n" and st.get("pdf_match_threshold") == 0.6)
st.set("image_crop_enabled", False)
st.discard()
check("discard drops pending", st.dirty is False and st.get("image_crop_enabled") is True)
check("view is a fresh dict", st.view() is not st.view() and st.view()["endpoint"] == "http://z:3")
st.set("runtime_auto_setup", False)
c = st.commit()
check("a bool-only change has no effect", c.patch == {"runtime_auto_setup": False} and c.effects == [])
st.set("endpoint", "http://q:9")
c = st.commit()
check("an endpoint change alone moves no signature, so no sweep", c.patch == {"endpoint": "http://q:9"} and c.effects == [])

section("appearance keys: specs as values, accent pair, the anki_theme pseudo-key")
theme = importlib.import_module("klausmate.theme")
st = ps.PrefsState.from_config({"color_theme": "not-a-theme", "color_theme_custom": "zzz",
                                "background_mode": "color", "reviewer_background_grad_x": 7})  # resolve rejects a string here
check("unknown accent seeds as ocean, a bad custom colour as the default swatch, and neither is dirty",
      st.get("color_theme") == "ocean" and st.get("color_theme_custom") == theme.DEFAULT_CUSTOM_COLOR and st.dirty is False)
check("specs seed through background.resolve",
      st.get("background")["mode"] == "color" and st.get("reviewer_background")["grad_x"] == 7)
check("anki_theme defaults to 0 and klausbook_design to off", st.get("anki_theme") == 0 and st.get("klausbook_design") is False)
check("APPEARANCE_KEYS is the six", set(ps.APPEARANCE_KEYS) == {"klausbook_design", "color_theme", "color_theme_custom",
                                                                "background", "reviewer_background", "anki_theme"})
spec = st.get("background")
spec["grad_x"] = 12.0
st.set("background", spec)
spec["grad_x"] = 99  # the caller's dict is not the state's
check("a spec edit is dirty by equality and copied in", st.dirty and st.get("background")["grad_x"] == 12.0)
st.set("anki_theme", 2)
c = st.commit()
check("commit flattens the spec with int casts and drops the pseudo-key",
      c.patch.get("background_grad_x") == 12 and isinstance(c.patch["background_grad_x"], int)
      and "anki_theme" not in c.patch and "background" not in c.patch, str(sorted(c.patch)))
check("appearance effects in order", c.effects == [("anki_theme", 2), ("appearance",)], str(c.effects))
flat = ps.flatten_appearance(st.view())
check("flatten_appearance never emits heatmap_enabled or color2", not ({"heatmap_enabled", "color2"} & set(flat)))
check("flatten_appearance casts reviewer geometry too and has no reviewer blur",
      isinstance(flat["reviewer_background_grad_x"], int) and "reviewer_background_blur" not in flat
      and isinstance(flat["background_blur"], int))
check("flatten_appearance carries the accent pair and the design gate",
      flat["color_theme"] == "ocean" and flat["color_theme_custom"] == theme.DEFAULT_CUSTOM_COLOR and flat["klausbook_design"] is False)
check("gradients are copied lists of dicts", isinstance(flat["background_gradients"], list)
      and flat["background_gradients"] is not st.get("background")["gradients"])
st.set("color_theme", "custom")
st.set("color_theme_custom", "#abcdef")
c = st.commit()
check("an accent change is an appearance effect alone", c.effects == [("appearance",)]
      and c.patch == {"color_theme": "custom", "color_theme_custom": "#abcdef"}, str(c))
st.set("color_theme", "nope")
check("an unknown accent name normalises to ocean (an edit)", st.get("color_theme") == "ocean" and st.dirty)
st.discard()
st.set("klausbook_design", True)
check("a design-gate change is an appearance effect", st.commit().effects == [("appearance",)])

section("review fixes: a requested mode survives set; a corrupt design value reads OFF")
st = ps.PrefsState.from_config({})
spec = st.get("background"); spec["mode"] = "image"
st.set("background", spec)
check("picking Image with no image yet is kept as the pending mode (the painters resolve an empty "
      "image to theme; the state must not, or Choose Image… never appears)",
      st.get("background")["mode"] == "image" and st.dirty)
check("a corrupt klausbook_design seeds OFF (background.design_enabled's rule: never surprise-restyle)",
      ps.PrefsState.from_config({"klausbook_design": "true"}).get("klausbook_design") is False
      and ps.PrefsState.from_config({"klausbook_design": 1}).get("klausbook_design") is False
      and ps.PrefsState.from_config({"klausbook_design": True}).get("klausbook_design") is True)
view = st.view()
check("flatten_appearance copies the gradients of the view it is handed",
      ps.flatten_appearance(view)["background_gradients"] is not view["background"]["gradients"])

raise SystemExit(report())
