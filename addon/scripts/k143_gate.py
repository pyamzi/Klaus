"""K-143 gate: the audit's unpinned INVARIANTS must now be caught.

Re-runs scripts/mutation_audit.py over the four modules this card
covers and asserts that each mutation K-139 reported as `survived` —
and that AUDIT.md judged a genuine invariant rather than trivia — now
comes back `caught`. Driven by the tool's own JSON and by exact
`ident` strings, so the gate and the audit cannot disagree about what
a finding is.

The first draft of this gate matched on field names that do not exist
in that JSON ("module", "mutation", "detail"), so nothing matched,
nothing was reported, and it passed before any work was done — the
very failure mode this card exists to close. It is asserted against
below: CLOSING must be a subset of the idents the run actually emits.
"""
import json
import os
import subprocess
import sys
import tempfile

# Exact idents, from AUDIT.md's "Findings worth a card".
CLOSING = [
    # 2. the gradient editor shipping armed on every deck screen
    "klaus_note/background.py::const::_GRAD_EDIT@261",
    "klaus_note/background.py::boolflip::bool@261:13@261",
    # 3. the deck browser booting into jiggle/edit mode
    "klaus_note/dashboard.py::boolflip::bool@346:14@346",
    # 4. a corrupt config silently HIDING a widget (documented rule)
    "klaus_note/dashboard.py::boolflip::bool@96:19@96",
    # 5. setup idempotency: panel never registers, or re-registers
    "klaus_note/lecture_view.py::const::_setup_done@273",
    "klaus_note/lecture_view.py::boolflip::bool@273:14@273",
    "klaus_note/lecture_view.py::boolflip::bool@724:18@724",
    # 6. the open/width persistence layer, entirely unwatched
    "klaus_note/lecture_view.py::gut::_saved_state@348",
    "klaus_note/lecture_view.py::gut::_save_state@356",
    # 7. the card-index path, whose pin is built FROM the constant
    "klaus_note/lecture_view.py::const::CARD_INDEX_SUBDIR@34",
    "klaus_note/lecture_view.py::const-loud::CARD_INDEX_SUBDIR@34",
    # 8. the resolver's cache invalidation
    "klaus_note/lecture_view.py::gut::LectureResolver.invalidate@130",
    # 9. save_notes reporting success on failure
    "klaus_note/pdf_notes.py::boolflip::bool@146:19@146",
    "klaus_note/pdf_notes.py::boolflip::bool@160:15@160",
]
MODULES = "background,dashboard,lecture_view,pdf_notes"

out = os.path.join(tempfile.mkdtemp(), "audit.json")
run = subprocess.run(
    [sys.executable, "scripts/mutation_audit.py",
     "--modules", MODULES, "--json", out],
    capture_output=True, text=True,
)
if not os.path.exists(out):
    print("auditor produced no JSON:\n", run.stdout[-2000:], run.stderr[-2000:])
    sys.exit(2)

rows = json.load(open(out))
seen = {r["ident"]: r["verdict"] for r in rows}

# A gate that cannot fail is worse than no gate: if an ident stops
# existing (a line moved, an operator was renamed), say so loudly
# instead of scoring it as closed.
missing = [i for i in CLOSING if i not in seen]
if missing:
    print("STALE GATE — these idents are no longer emitted by the auditor:")
    for i in missing:
        print("  ", i)
    print("Re-derive them from a fresh --json run before trusting this gate.")
    sys.exit(2)

still = [i for i in CLOSING if seen[i] == "survived"]
print(f"{len(CLOSING) - len(still)}/{len(CLOSING)} of this card's findings are now caught")
for i in still:
    print("   still surviving:", i)
sys.exit(1 if still else 0)
