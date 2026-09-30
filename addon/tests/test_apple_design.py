"""Accessibility and interaction contracts across Klaus-owned surfaces."""
from __future__ import annotations
import importlib
import re
import sys
from pathlib import Path
sys.path.insert(0, '.claude/skills/klaus-test/scripts')
from anki_stubs import install, check, report
install()
theme = importlib.import_module('klausmate.theme')
dash = importlib.import_module('klausmate.dashboard')
for name in ('toolbar_css', 'bottombar_css', 'reviewer_bar_css', 'editor_css'):
    css = getattr(theme, name)()
    check(name + ' keeps keyboard focus visible', ':focus-visible' in css and 'outline-offset' in css)
for night in (False, True):
    css = theme.dialog_qss(night)
    plain = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    base = re.search(r'QPushButton\s*\{([^}]+)', plain).group(1)
    check('dialog buttons reserve focus border '+str(night), '1px solid transparent' in base)
    check('primary action is explicit '+str(night), 'QPushButton:default' in css)
    check('advanced disclosure is quiet '+str(night), 'QPushButton#AdvancedModelSettings' in css)
    check('native PDF tools have focus feedback '+str(night), 'QToolButton:focus' in theme.panel_header_qss(night))
css = dash.dashboard_css()
check('dashboard respects OS reduced motion', 'prefers-reduced-motion: reduce' in css)
check('dashboard respects reduced transparency', 'prefers-reduced-transparency: reduce' in css)
check('dashboard supports increased contrast', 'prefers-contrast: more' in css)
html = Path('klausmate/web/pdfjs_viewer.html').read_text()
check('PDF toolbar keyboard focus', ':focus-visible' in html)
check('PDF toolbar respects reduced transparency', 'prefers-reduced-transparency: reduce' in html)
raise SystemExit(report())
