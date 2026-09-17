# Mutation audit — six modules (K-139)

Findings from `scripts/mutation_audit.py`, which breaks the code on
purpose one small break at a time and records whether any check
notices. A break nothing notices is behaviour with no pin on it.

Nothing here is fixed. Findings become cards.

    python3 scripts/mutation_audit.py --selftest        # the gate
    python3 scripts/mutation_audit.py --modules all     # this report

Run 2026-09-01, 314 mutations, 372 test-file runs, 82s, zero skipped.
Deterministic: a second run of the same tree gives the same report.
Versions audited (`sha256`, first 12) — several sessions were editing
this checkout, so findings name their input:

| module | sha256 | test file(s) run |
|---|---|---|
| `klausmate/heatmap.py` | `e5b505c24e61` | `test_heatmap.py` |
| `klausmate/dashboard.py` | `037ad3d6c80c` | `test_dashboard.py` |
| `klausmate/background.py` | `7359207abb78` | `test_background.py`, `test_heatmap.py` |
| `klausmate/pdf_notes.py` | `ee706518137b` | `test_pdf_notes.py` |
| `klausmate/lecture_view.py` | `534bf13fc9a3` | `test_lecture_view.py` |
| `klausmate/projection.py` | `cc30f799e389` | `test_projection.py` |

**Re-run the projection findings before acting on them.**
`klausmate/projection.py` and `tests/test_projection.py` were being
actively edited by another session throughout. The run above copied
`cc30f799e389` and its sandbox baseline was green, so findings 10 and 11
are sound *for that version*; within the hour the file had moved to
`93de08d99e6e` and `tests/test_projection.py` was failing 6 of 35 on
disk — someone else's work in flight, unrelated to this tool, which
writes into the checkout not at all. Every other module's digest was
stable across two full runs.

## Why you can believe the numbers

K-135's vacuous pin was found by accident, and the first attempt at
finding more by regex reported 395 then 257 hits, all garbage. So the
tool is validated before it is trusted, and validated the only way that
works — by making pins fail on demand.

`--selftest` (the card's verify command) answers three questions and
exits non-zero on any wrong answer:

* **(a) Does it recognise a pin that cannot fail?** It plants
  `_MUTATION_AUDIT_PLANT = "#AABBCC"` into `klausmate/setup_flow.py` and
  checks the hex pin in `test_setup_crop_theme.py` twice. Against
  today's tokenised helper the pin **fails** (control — without this,
  "the old one survived" would prove nothing; the plant might simply be
  invisible to everything). Against the reconstructed pre-a2c22f4
  split-on-`#` helper the same pin **passes on a literal that is right
  there**. The reconstruction is also proved blind independently, in
  process, before any test runs: it returns `[]` for `BLUE = "#AABBCC"`.
* **(b) Does it recognise a pin that works?** Two decoys are gutted in
  `heatmap.py` — `stats_from_history` and `level_for` — and both must
  come back caught, naming the checks that tripped.
* **(c) Is the tree untouched?** 145 repo files hashed before and after.

Eleven further controls were run against the tool during development
and all pass: a red sandbox baseline aborts instead of scoring every
mutation "caught"; `_assert_no_bytecode` fires on a stray `.pyc`; a real
run leaves zero bytecode; a write outside the sandbox is refused; a test
file outside K-139's scope is refused; an inapplicable, no-op, or
non-compiling mutation is **skipped, never caught**; enumeration is
byte-identical across runs; `gut` provably preserves the original body
text and `gut-cut` provably removes it. A real `SIGINT` mid-run was
sent: the tree came back byte-identical and the scratch directory was
cleaned.

Two repo-specific traps were handled explicitly. **Stale bytecode**:
children run with `-B` and `PYTHONDONTWRITEBYTECODE=1`, both cache roots
(local `__pycache__` and this Mac's `sys.pycache_prefix` mirror) are
purged before every run, and the sandbox is scanned for `.pyc` after
every run — without this a same-size mutation inside one mtime second
executes the OLD code and every mutation looks caught, which is being
confidently wrong in the reassuring direction. **Source pins**: see the
next section.

## How to read a verdict

| verdict | meaning |
|---|---|
| `caught` | a named check failed. A behavioural pin exists. |
| `caught-crash` | the run died non-zero with no `FAIL` line — the mutated value flowed into module-scope test code and blew it up. Still a real catch; the behaviour is observed, just not reported gracefully. |
| `source-pinned-only` | **nothing behavioural notices, but a test that greps the module text does.** |
| `survived` | nothing noticed at all. |

`source-pinned-only` exists because some tests in this repo read module
SOURCE as text rather than importing it, and that has to be told apart
from a real behavioural pin. The primary `gut` operator *inserts*
`return None` after the docstring and leaves the original body in place
as dead code: behaviour destroyed, every byte of text preserved, so a
catch is a behavioural catch. Every survivor of that is then re-probed
with `gut-cut`, which deletes the body text outright. Caught only there
means a grep notices the code is gone and nothing notices what it did.

Constants get two strengths, because one proves nothing. *Quiet* nudges
by one and appends `MUT` to strings — the right probe for an identity (a
path fragment, a bridge prefix, a dict key), a **useless** probe for a
tolerance or a geometry constant, since `144.0 -> 145.0` surviving says
only that no fixture sits on that boundary. *Loud* collapses the value
to `1` / `1.0` / `"MUT"`. Only a survivor of **both** is evidence. The
loud variant converted 8 apparent survivors into catches (`CELL`,
`SET_PREFIX`, `_WEEKDAYS[0]`, `MAX_SPHERES`, `GRAD_EDIT_CLEANUP_JS`,
`_BUTTON_JS`, `MAX_ITERATIONS`, `SECS_PER_DAY`) — i.e. a quarter of what
the weak operator alone would have reported was noise.

## Headline

| module | mutations | caught | crash | source-only | survived |
|---|---:|---:|---:|---:|---:|
| `heatmap.py` | 82 | 46 | 9 | 2 | 25 |
| `dashboard.py` | 38 | 18 | 3 | 6 | 11 |
| `background.py` | 47 | 28 | 9 | 0 | 10 |
| `pdf_notes.py` | 56 | 44 | 6 | 0 | 6 |
| `lecture_view.py` | 76 | 13 | 6 | 5 | 52 |
| `projection.py` | 15 | 2 | 8 | 0 | 5 |
| **total** | **314** | **151** | **41** | **13** | **109** |

109 surviving records; 89 distinct once the 20 constants that survived
both strengths are collapsed. Of those 89, **11 are worth a card** and
the rest are trivial or beyond this harness's reach — the honest read
is in the two sections after the findings.

**The suite is in better shape than feared.** `background.py` and
`pdf_notes.py` have **zero** surviving function-body mutations: every
function in both is behaviourally pinned, and their only survivors are
constants. `heatmap.py` catches 55 of 82. Nothing resembling K-135 —
a pin structurally incapable of failing — turned up in these six. The
gaps that did turn up are gaps in *coverage*, not pins that lie.

---

## Findings worth a card

**1. The day/night palette blocks can be swapped, and only their
existence is checked.** `heatmap.py:604-605` and `dashboard.py:205-206`
build `":root {…}" ":root.night-mode {…}"` from `_palette_vars(False)`
and `_palette_vars(True)`. Flipping either argument survives — so does
making both blocks identical. The only pins are
`test_heatmap.py:386` and `test_dashboard.py:130`, which assert the two
selectors are *present*. Genuinely unpinned, and the highest-value
finding here: this is a hard-won CLAUDE.md invariant (both palettes ship
in one sheet because Anki's theme switch only toggles classes), and the
failure mode is light mode painted dark. Two sites, one bug shape, one
cheap fix — assert the two blocks differ and that the day block carries
a light-palette value.

**2. `background.py:261` — `_GRAD_EDIT = False` can be flipped to
`True`.** Genuinely unpinned. The on-screen gradient editor is supposed
to be armed only while Preferences is open; shipping it armed would grow
drag handles on every user's deck screen. Nothing notices in either
direction.

**3. `dashboard.py:346` — `_EDIT: bool = False` can be flipped.**
Genuinely unpinned. The deck browser would boot into jiggle/edit mode.
The flag's *reset* paths are source-pinned; its default is not pinned at
all.

**4. `dashboard.py:96` — the corrupt-config rule is inverted with
nothing noticing.** `widget_shown`'s `if not isinstance(cfg, dict):
return True` is the documented "a bad config entry must not silently
hide a feature" rule (heatmap.enabled's rule, called out in CLAUDE.md).
Flipping it to `False` survives. Genuinely unpinned, and it is a stated
invariant — worth a check on principle. (The neighbouring `key is None
-> return True` for mandatory widgets IS pinned; only the corrupt-value
branch is bare.)

**5. `lecture_view.py:273` and `:724` — the setup idempotency guard is
unpinned in both directions.** `_setup_done = False` flipped to `True`
means `setup()` never registers a hook and the whole Lecture panel
silently does not exist; `_setup_done = True` at the end flipped to
`False` means every call re-registers the hooks. Both survive, and
`setup()` itself is only `source-pinned-only`. Genuinely unpinned.

**6. The Lecture dock's open/width persistence has no pin at all.**
`_saved_state` and `_save_state` (`lecture_view.py:348,356`) both
survive gutting, and so do all four `_save_state(open=…)` call sites
(`:552,553,603,616`) under a boolean flip. These are pure JSON logic
over `pdf_handler._load_tabs_file`/`_save_tabs_file` — this harness can
test them against a temp `user_files` dir, so this is a coverage gap,
not a Qt limitation. Genuinely unpinned; `lecture_view_reopen` is a
user-visible feature whose entire storage layer is unwatched.

**7. `lecture_view.py:34` — `CARD_INDEX_SUBDIR` is one of three
independent copies of the same on-disk path, and its pin is
self-referential.** `curation.py:52` (`INDEX_DIR = …"card_index"`),
`lecture_view.py:34` and `pdf_graph.py:51` each spell the directory
separately. `test_lecture_view.py:87,175` build the fixture directory
*from* `lecture_view.CARD_INDEX_SUBDIR`, so the constant defines both
the code and the test and the two can never disagree — even the loud
`"MUT"` variant survives. Genuinely unpinned: if the three copies drift,
the Lecture panel reads an empty directory and shows "No lecture page
available" forever, with a green suite.

**8. `lecture_view.py:130` — `LectureResolver.invalidate` is
unpinned.** The class is otherwise well covered (81 checks), but gutting
its cache-clearing method changes nothing any check can see. Genuinely
unpinned and cheap to fix — CLAUDE.md says results are "revalidated by
file stamps", and this is the method that does it.

**9. `pdf_notes.py:146` and `:160` — `save_notes` can report success on
failure.** Both `return False` error branches (the delete path and the
write path) flip to `return True` undetected. Genuinely unpinned: a
caller that trusts the return value would silently lose a note. Testable
by pointing the sidecar at an unwritable directory.

**10. `projection.py:74` — `DEFAULT_FIT_ROWS` is never exercised.**
Every one of the 14 `projection.project(...)` calls in
`test_projection.py` passes `fit_rows=` explicitly; the only mention of
the constant is a `hasattr` existence check (`:148`). Collapsing the
default to `1` survives — meaning every production caller relying on the
default would fit the PCA from a single row and no test would object.
Genuinely unpinned, and it is exactly the fit-sample/project-all split
K-138 is about.

**11. `projection.py:76` — `_CONVERGENCE_EPS` can be loosened by nine
orders of magnitude.** `1e-9 -> 1.0` survives (the loop still runs two
iterations, because the epsilon test needs a `prev_eigval`), while
`MAX_ITERATIONS -> 1` is caught. So the accuracy pin has a resolution of
about one power-iteration step, not of the documented convergence
criterion. Genuinely unpinned in the narrow sense that matters: nothing
compares the recovered axes against a known-answer PCA to a tolerance.
Lower value than the others — the projection is a layout, not a number
anyone reads — but real.

**Also worth one small card:** the bridge's "we handled this message"
contract. `return (True, None)` flips to `(False, None)` undetected at
`heatmap.py:1071,1105`, `dashboard.py:471,478,481,484,496` and
`lecture_view.py:647` — eight sites across three modules. Returning
`False` re-opens the message to the rest of Anki's hook chain. Each site
individually is minor; eight of them with no pin anywhere is a pattern.

---

## Survivors judged too trivial to matter

Each of these survived both mutation strengths. One line of judgement
each; none is worth a card.

*Self-referential value pins — the fallback PATH is pinned, the VALUE is
not.* This is the K-135 shape in miniature, but harmless here because
the value is arbitrary:

* `background.py:51` `DEFAULT_BLUR` — `resolve({"background_blur":999})["blur"] == bg.DEFAULT_BLUR` reads the constant it is checking. The clamp behaviour is pinned; the number is cosmetic.
* `heatmap.py:50` `SECS_PER_DAY` — `test_heatmap.py` opens with `DAY = heatmap.SECS_PER_DAY`. Same shape. (The loud variant crashes the run, so the constant is not entirely free.)
* `background.py:216` `MAX_SPHERES` — `test_background.py:228` compares against `bg.MAX_SPHERES`. The cap behaviour is pinned, the number 4 is a documented design choice. The loud variant is caught.
* `lecture_view.py:36-40` `R_NO_TAGS`, `R_NO_VECTOR`, `R_NO_CARD_INDEX`, `R_INDEX_UNAVAILABLE`, `R_BELOW_FLOOR` — internal reason codes compared against themselves. No external contract; renaming them is a no-op by construction. Correct as written.

*Unobservable by construction:*

* `background.py:33,34` `MODES[0]`, `FITS[0]` — the first member equals the hardcoded fallback, so removing it from the valid set produces the same answer either way. Mild redundancy, not a gap.
* `pdf_notes.py:222` `_DEFAULT_WIDTH` — the fallback glyph width for undefined WinAnsi slots. The code comment already says the branch is unreachable in practice; the table exists only to be total.

*Cosmetic constants — a wrong value is visible the moment Anki opens:*

* `heatmap.py:61,65` `GAP`, `MONTH_GAP` — CSS grid spacing.
* `heatmap.py:71,74` `RANGE_LABELS[0]`, `_MONTHS[0]` — display strings. (`_WEEKDAYS[0]` IS caught, via `_WEEKDAY_INITIALS`.)
* `heatmap.py:453` `_GEAR_SVG` — the gear icon's path data.
* `heatmap.py:56` `DEFAULT_FORECAST_DAYS` — the four-week forecast default.
* `lecture_view.py:274` `_JUMP_DELAYS_MS[0]` — the first rung of the pdfjs retry ladder. A timing constant; the ladder's *shape* is what matters and that is pinned.
* `pdf_notes.py:86` `MIN_PAGE_SIDE` — the tiny-mediabox fallback to Letter is never exercised by any fixture. Real but negligible: a corrupt mediabox is a defensive branch, not a feature.

*Design markers with no runtime consequence in these tests:*

* `lecture_view.py:54,63` `@dataclass(frozen=True)` on `LectureMatch`/`NoLecture` — unfreezing survives. A one-line "records are frozen" check would be cheap, but nothing mutates them today.
* `lecture_view.py:663` — the in-code `lecture_view_reopen` default. `klausmate/config.json` ships the key and `test_lecture_view.py:453` pins that it does, so the in-code fallback is belt-and-braces.

*Qt widget configuration, unreachable under the aqt stub:*
`lecture_view.py:391` `setWordWrap(True)`, `:692` `setCheckable(True)`,
`:694` the lambda's unused default, `:552,706` the
`_closing_for_shutdown` handshake.

## Survivors that are harness limits, not coverage gaps

29 function-body mutations survived. Two thirds of them are the aqt-glue
layer below each module's "aqt glue" divider — code that constructs or
drives real Qt widgets and Anki hooks, which this headless harness
cannot instantiate at all:

* `lecture_view.py` — the whole `LectureDock` class (`__init__`,
  `follow_card`, `_show_match`, `_show_empty`, `_set_status`,
  `_arm_jump` and its inner `attempt`, `save_width`, `closeEvent`) plus
  `_refocus_reviewer`, `_ensure_dock`, `open_lecture_view`,
  `toggle_lecture_view`, `_on_show_question`, `_on_state_change`,
  `_on_reviewer_menu`, `_teardown`. This is why lecture_view's survivor
  count (52) dwarfs every other module's: the module is mostly dock.
* `heatmap.py` — `_config`, `_open_day`, `_refresh`, `_write_cfg`,
  `setup`.
* `dashboard.py` — `_addon`, `_config`.
* `lecture_view.py` — `_user_files`, `_cfg` (thin `mw`/package
  accessors).

Calling these "unpinned behaviour" would be true and useless. The one
qualification worth recording: `tests/test_drive.py` proves real
offscreen PyQt6 IS available under this machine's `python3` (K-117), so
"cannot be tested" is really "would need a real-Qt section nobody has
written". `heatmap._write_cfg` is the one in this group I would flag
if pressed — it is the gear's only writer — but it is glue, and glue is
what the group is.

### The 13 `source-pinned-only` findings

These have no behavioural pin; a test that greps the module text is all
that stands behind them. That is worth knowing but is not the same as a
gap — several are deliberately documented-by-grep because the behaviour
is a hook registration that cannot run headlessly:

* `dashboard.py` (6): `write_cfg`, `_script_url`, `_refresh`,
  `_on_webview_will_set_content`, `_on_profile_open`, `setup`.
* `lecture_view.py` (5): `shutdown`, `_on_bottom_bar_content`,
  `_on_js_message`, `_on_state_shortcuts`, `setup`.
* `heatmap.py` (2): `_on_deck_browser_content`,
  `_on_webview_will_set_content`.

`dashboard.write_cfg` is the notable one: CLAUDE.md records that it
patches an armed Preferences preview so a dashboard edit survives the
next preview tick — a hard-won behaviour whose only guard is a text
search for the code that implements it.

## The shape this keeps finding: one source of truth, read twice

Across two independent lanes the tool has now surfaced the same defect
family more than any other, and it is worth naming because it is
**invisible to a reader and obvious to the mutator**.

A pin cannot fail when the test and the code read the SAME source of
truth. Concretely:

```python
# the code
max_cards = 2 * CARDS_PER_PAGE
# the "test"
check("max_cards is two pages", forge.max_cards == 2 * CARDS_PER_PAGE)
```

Change `CARDS_PER_PAGE` and both sides move together, forever. The
check reads like coverage and asserts nothing. Same for
`min_score == DUPLICATE_THRESHOLD`, and same for a test fixture built
FROM the constant it is meant to verify — `tests/test_lecture_view.py`
built its card-index directory out of `lecture_view.CARD_INDEX_SUBDIR`,
so the constant defined both the code and its own test (K-142 replaced
it with a three-way agreement check against the two OTHER modules that
spell the same path).

The same root cause wearing different clothes:

* **Prose satisfying a pin.** `"validates the body" in SRC` passes on
  the docstring that says so. Strip comments and docstrings first, or
  read the AST.
* **A helper that removes what it hunts.** The hex-colour check split
  each line at its first `#` to skip comments — and a hex literal *is*
  a `#` inside a string, so it deleted exactly what it was looking for
  and returned nothing, forever (K-135).
* **A stray substring elsewhere in a big file.** `"_page_bar" in src`
  passes on an unrelated line 3,000 lines away (K-153).
* **The wrong gate doing the work.** A handler called with a `None`
  context returned "rejected" because of the *context* check, so
  gutting the *message* check changed nothing (K-151).

**The test to apply when writing a pin: what single edit would make
this fail? If the honest answer is "an edit that also changes the
test", the pin is decoration.** Assume every new pin has one until you
have watched it fail — five separate lanes in one day each found one in
their own work, after writing it carefully.

## Known limitations of the tool

Stated plainly so nobody over-reads the numbers.

* **Only three operators.** Gut a function body, mutate a module-level
  constant, flip a boolean literal. It does not reorder statements,
  swap comparison operators, drop `try/except` arms, or touch anything
  inside a nested data structure past the first element. "Caught" means
  *these* mutations are caught, not that the module is pinned.
* **Module-level constants only.** Class attributes and defaults inside
  function bodies are out of scope for the `const` operator.
* **The quiet string mutation is weak for blobs.** Appending `MUT` to a
  large CSS/JS/SVG literal changes almost nothing semantically; the loud
  variant is what carries the signal there.
* **No pins for the untestable.** Anything requiring a live Anki, a real
  `QWidget`, or the JS DOM tests is invisible to this run.
* **One test file per module** (plus any of the six that import it, found
  by scanning their source). A mutation another suite would catch is
  reported as surviving here. It refuses to run any test file outside
  K-139's scope.
* **`caught-crash` is a coarse verdict.** It says the mutation was
  observed, not which check would have said so.
* **Concurrency.** Several agents share this checkout. The tool never
  writes into it — every write is path-checked into a sandbox under a
  scratch dir, and every repo file that changes during a run is compared
  against the set of blobs the run produced, so a genuine leak and
  somebody else's edit can never be confused. One external edit
  (`klausmate/pdf_map.py`) was correctly reported as such during this
  run.

## Bottom line

Worth running over the rest of the suite. It found eleven things worth
cards in six modules, it proved each one by making a check fail (or
demonstrably not fail) rather than by pattern-matching, and it proves
itself on every invocation. Its bias is toward under-reporting: the
loud/quiet split threw away a quarter of what a weaker operator would
have called a finding, and 29 of the 89 distinct survivors are honestly
labelled as beyond the harness rather than counted as coverage gaps.

It found no second K-135. In these six modules there is no pin that
cannot fail — only behaviour nobody got round to pinning.

---

# Second lane — `klausmate/index_queue.py` (K-162)

The index runner landed with K-152 and was swept by hand (~100
mutations) before it shipped, but it was never added to
`AUDIT_MODULES`, so nothing kept it that way. It is now.

(`AUDIT_MODULES` also carries the assistant layers that survived the
2026-09-02 convergence — `card_forge`, `anki_tools`, `agent_host`,
`assistant_sessions`; `llm_client`, `entitlement`, `assistant_session`
and `podcast` were deleted that day and dropped from the list.
Those lanes audited their own modules and *fixed* what they found
rather than recording it, so the report above is still exactly what its
title says — the six K-139 modules. This section is the second one with
findings left standing, per K-162's brief: report, don't fix.)

Run 2026-09-01, 101 mutations, 112 test-file runs, 25s, one pre-skip
(`tooltip@278`, the no-op fallback stub — its body is already vacuous,
correctly skipped rather than scored). Run twice back to back: identical
apart from the timing line and which of another session's files moved
underneath.

| module | sha256 | test file run |
|---|---|---|
| `klausmate/index_queue.py` | `9012ecdb11db` | `test_index_queue.py` (`81037eede0d3`, 122 checks, 0.2s) |

| operator | mutations | caught | crash | source-only | survived |
|---|---:|---:|---:|---:|---:|
| `gut` | 58 | 37 | 10 | 2 | 8 (+1 skipped) |
| `const` | 11 | 1 | – | – | 10 |
| `const-loud` | 10 | 1 | – | – | 9 |
| `boolflip` | 23 | 9 | 1 | – | 13 |
| **total** | **101** | **48** | **11** | **2** | **40** |

**The hand sweep's claim holds exactly.** K-152 predicted that the only
survivors would be the Qt-widget-only functions, and under `gut` that is
precisely the list the tool returns: `offer_model_sweep.answered`
(`:758`), `_StatusDock.__init__` (`:806`), `_on_dock_button` (`:851`),
`_ensure_dock` (`:860`), `_render_dock` (`:874`), `_hide_dock_later`
(`:889`) with its inner `go` (`:897`), `_hide_dock` (`:907`), plus
`_StatusDock.render` (`:846`) and `setup` (`:939`) as
`source-pinned-only`. Nothing else. Every other function body — the
four-phase chain, the queue, the gates, the state publishing, the pure
renderers — is behaviourally pinned, and 47 of 57 applied `gut`
mutations are caught. There is no second K-135 here either.

The new ground is the two operators the hand sweep did not run. All
four findings below are `boolflip`, and all four are reachable by this
headless harness — none of them is a Qt limit.

## Findings worth a card

**1. The `announce` path is never exercised, in a module whose
docstring says nothing may start silently.** `index_queue.py:45` states
the invariant — "Nothing is ever started silently: a single add
tooltips and shows the bar". Yet every one of the ~30 `request` /
`request_pdf` calls in `test_index_queue.py` passes `announce=False`,
so flipping **both** defaults to `False` (`request` at `:358`,
`request_pdf` at `:396`) survives. The production caller that relies on
the default is the one that matters: `on_pdf_imported` (`:408`) —
`import_pdf_file`'s funnel for the Library tree drop, the Library's
Browse…, the deck-screen square and the deck-screen file drop — calls
`request_pdf(name)` bare. Flip the default and every user-visible
"indexing started" tooltip on an add disappears with a green suite.
Genuinely unpinned; the message builders (`queued_message`,
`add_tooltip`) are well pinned, the firing is not.

**2. `index_queue.py:373` — the once-per-session key warning can be
disarmed.** `_key_warned = True` flips to `False` undetected, and the
comment on that very line is the invariant it breaks: "ten drops must
not stack ten tooltips". Ten PDFs dropped without an API key would
raise ten tooltips. The flag's *reset* on profile close **is** pinned
(`test_index_queue.py:552`); its set is not, and neither is its module
default (`:298`, but that one is trivial — the tests assign it in their
own reset helper).

**3. Three `except` fallbacks flip with nothing noticing, and each
one's polarity is a documented decision.** All three are one-line arms
on functions whose happy paths are well covered:

* `:485` `_pdf_present` — `return True  # never lose a job to a
  bookkeeping hiccup`. Flipped to `False`, a presence check that raises
  silently drops every job behind it, which is the exact outcome the
  comment exists to prevent.
* `:733` `signature_changed` — `return False`, i.e. fail closed. It
  gates `offer_model_sweep` (`:748`), and its docstring is entirely
  about not silently re-embedding a whole collection on a paid API.
  Flipped to `True`, any exception inside `embeddings.signature_matches`
  turns every Preferences Save into a whole-library re-index offer. The
  function's normal answers have six checks on them
  (`test_index_queue.py:184-201`); the except arm has none.
* `:471` `_busy_elsewhere` — `return False`, i.e. run rather than
  stall. Flipped to `True`, a failed deferred import reads as
  permanently busy: the queue polls `BUSY_WAIT_POLLS` times and gives
  up, forever.

Each is testable headlessly by making the deferred import or the callee
raise. Three sites, one shape, one cheap fix.

**4. All three "the runner is idle" publishes are unobserved.**
`_pump` declares `active=False` on the drained queue (`:497`), on a
busy-wait retry (`:506`) and on the give-up branch (`:513`). Flipping
any of the three survives. `status_line` (`:205`) and
`dock_button_label` (`:221`) both branch on `active` — so a flipped
flag puts a live progress line and a **Stop** button on the status dock
while nothing is running, on the one screen that exists to say what is
running. The neighbouring fields on the same publishes are pinned
(`finished == "a"` at `test_index_queue.py:368`, `message ==
BUSY_WAIT_TEXT` at `:611`), which is what makes this an oversight
rather than a limit: the tests already reach all three branches. A
probe confirmed the drained branch executes exactly once across the
suite and nothing looks at what it published. Assert
`state().active is False` — or better, assert `status_line(state())` —
on the three paths.

## Survivors judged trivial

Nine constants survived **both** strengths. None is worth a card.

*Internal tags with no external contract:* `JOB_CARDS`, `JOB_PDF`
(`:72,73`) name nothing outside this module — no other file in
`klausmate/` mentions either — and the tests reference them
symbolically, which is correct for an arbitrary tuple tag.

*Counter seeds:* `_seq`, `_hide_gen`, `_waits` (`:293,297,299`) start
at 0 because they must start somewhere; the tests assign them in their
own reset helper. Nothing observable rides on the initial value.

*Self-referentially pinned, correctly:* `BUSY_WAIT_POLLS` (`:303`) and
`BUSY_WAIT_TEXT` (`:304`) — `test_index_queue.py:619` loops
`range(iq.BUSY_WAIT_POLLS + 2)` and `:611` compares against
`iq.BUSY_WAIT_TEXT`. The *behaviour* (waiting is bounded; the bar says
why) is pinned; the bound and the wording are tuning choices, and a
test that hardcoded 40 would only pin the tuning. This is the K-135
shape in miniature and harmless here — but it is the fifth module in
which it appears, so it is worth noting that the reviewer's question
still applies: nothing would fail if `BUSY_WAIT_TEXT` became `""`.

*Timer durations, invisible headless:* `IDLE_HIDE_MS`,
`BUSY_RETRY_MS` (`:301,302`).

`_key_warned` (`:298`) survived the quiet strength and was caught by
the loud one, so by this report's own rule it is not evidence — see
finding 2 for the part of it that is.

Three `boolflip` survivors are Qt configuration below the glue divider
and out of this harness's reach: `announce=False` inside
`offer_model_sweep.answered` (`:766`), that function's closing
`return True` (`:787`), and `WA_StyledBackground` in
`_StatusDock.__init__` (`:824`).

## Bottom line for this module

122 checks, and the tool can falsify all but ten of the module's
function bodies — the ten being exactly the widget layer K-152 said it
would be. The gaps it found are not in the chain or the queue, which
are the parts that would lose a user's work; they are in the *edges*:
what happens when a bookkeeping call raises, and what the status
surface says when nothing is running. Four cards' worth, none urgent,
all cheap.

---

# Third lane — the API-first modules (K-228, 2026-09-15)

Plan 1 of
`docs/superpowers/specs/2026-09-15-api-first-klaus-design.md` landed four
new modules, and Task 8 added all four to `AUDIT_MODULES`:
`page_store`, `cost`, `openai_client`, `anthropic_client`. They belong
here for the same reason the rest of the roster does — each is pure, or
pure above one `_urlopen` its tests replace, so nearly every function is
reachable from its own test file, which is the condition this audit
needs.

Run 2026-09-15 after `--selftest` passed (6 test-file runs, 0.4s, all
three cases answered correctly): 70 mutations, 78 test-file runs, 4.1s —
the pre-fix snapshot; see the follow-up below for the totals after both
findings closed.

| module | sha256 | test file run | checks |
|---|---|---|---:|
| `klausmate/page_store.py` | `9fc229c45cc4` | `test_page_store.py` (`6b78631127f9`) | 16 |
| `klausmate/cost.py` | `8754377b80b9` | `test_cost.py` (`281e18b72f38`) | 8 |
| `klausmate/openai_client.py` | `478ed6d1c7a8` | `test_openai_client.py` (`9ce6d8e6ac87`) | 9 |
| `klausmate/anthropic_client.py` | `5f0dc5a1175d` | `test_anthropic_client.py` (`7ef603227884`) | 39 |

| operator | mutations | caught | crash | survived |
|---|---:|---:|---:|---:|
| `gut` | 39 | 13 | 26 | **0** |
| `const` | 13 | 6 | – | 7 |
| `const-loud` | 13 | 5 | 2 | 6 |
| `boolflip` | 5 | 3 | 1 | 1 |
| **total** | **70** | **27** | **29** | **14** |

**Not one `gut` survivor in four modules.** Every function body in all
four is behaviourally pinned: emptying any of them fails its test file.
That is the number that matters, and it is the first lane in this
document to return it clean. All fourteen survivors are module-level
constants or one boolean keyword, judged below.

## Found and fixed during this lane: `render_page_png`

The first run had `page_store.py:143 render_page_png (gut)` surviving —
gut the body and `test_page_store.py` still passed. The cause was a
deletion, not an oversight: `render_page_png` moved into `page_store`
from `page_ocr.py`, which was deleted on 2026-09-15 and took
`tests/test_page_ocr.py` — the **only** test of that function — with it.
`test_page_store.py`'s header said so out loud ("covered by
tests/test_page_ocr.py"), which by then named a file that did not exist.

Fixed in this lane rather than reported, since K-228 owns that test
file. Two things were done differently from the check that was lost:

- The old check built its one-page PDF with the vendored `pypdf`, which
  **this machine's python3 cannot import at all** — so restoring it
  verbatim would have restored a permanent `SKIP`, a vacuous pin wearing
  a different hat. The page is now a literal 300×200 PDF written by hand
  in the test; pdfium reads it fine.
- The old assertion was `png[:8] == b"\x89PNG…" and len(png) > 100`,
  which any PNG at all satisfies. It now reads the width out of the
  PNG's own IHDR, so the SCALE is pinned: `long_edge=140` on a 300×200
  page must come back 140 wide, and the default must be `LONG_EDGE`
  (1400) — the size the assistant actually sends. Out-of-range pages are
  pinned to raise.

That took `page_store` from 4 survivors to 1, and killed both `LONG_EDGE`
constant survivors as a side effect.

## Findings worth a card

**1. `test_openai_client.py:59` compares the URL against the constant it
is testing.** `url == oc.API_BASE + "/embeddings"` is the K-135 shape:
mutate `API_BASE` and both sides move together, so the check cannot fail
on it — `API_BASE (const)` survives, and it is the only `const` survivor
in this lane that is load-bearing. This is the one string that decides
where a paid request goes and where a key is sent; point it at
`http://klaus.invalid` and nine checks still pass. Assert the literal
`"https://api.openai.com/v1/embeddings"` once, in one check, and keep
the symbolic comparison everywhere else.

**2. `test_cost.py:26` names arithmetic it does not verify.** The check
is titled "judge: 10 batches, each (page + 8 cards + prompt overhead) in
and ~40 tokens per verdict out" and asserts
`j.tokens > 0 and j.dollars > 0 and estimate_judge(160, 1200).tokens >
j.tokens`. Both constants in that sentence —
`JUDGE_PROMPT_OVERHEAD_TOKENS` and `JUDGE_OUTPUT_TOKENS_PER_CARD` —
survive at both strengths, including the loud one, because monotonicity
and positivity hold whatever they are. Not strictly vacuous (zeroing
`estimate_judge` would fail it), but the title promises a computation the
pin never performs. One `j.tokens == <the worked number>` would close it.
Cheap, and worth it before Plan 2 puts a price in front of the user.

Both findings above were closed the same day — see the follow-up below.

## Survivors judged trivial

*Timeouts.* `EMBED_TIMEOUT_S`, `TRANSCRIBE_TIMEOUT_S`
(`openai_client.py:18,19`), `DEFAULT_TIMEOUT_S`, `_MAX_RETRY_AFTER_S`
(`anthropic_client.py:43,44`). Tuning values with no observable
behaviour headless — the fake `_urlopen` records the timeout it is
handed, so they *could* be pinned, but pinning a duration pins the
tuning, not the contract. The behaviour that matters (a bounded wait
exists; a `retry-after` is honoured but capped) is already caught.

*The `cost` judge constants*, as their own finding above — trivial as
constants, not trivial as a titled-but-unpinned computation.

*One boolflip, behaviour-equivalent:* `ensure_ascii=False` in
`page_store._atomic_json` (`:70`). Flipping it changes the bytes on disk
for non-ASCII text and changes nothing at all about what `json.load`
gives back, which is the only thing any caller sees. There is no
assertion that could catch it without asserting file bytes, and file
bytes are not the contract.

## Bottom line for this lane

Four modules, 72 checks between them, and the tool cannot falsify a
single function body in any of them. The two findings are both in test
files, both the same shape this document keeps finding — a pin that
reads its own source of truth, and a pin whose title outruns its
assertion — and neither is in the code that spends money. The hole that
mattered was the one the deletion opened, and it is closed.

### Follow-up, same day (K-228 completion round)

Both findings above were closed before this lane was committed:
`tests/test_openai_client.py` now pins the literal
`https://api.openai.com/v1/embeddings` and `…/audio/transcriptions`
(a scratch copy with `API_BASE = "http://klaus.invalid/v1"` fails both
pins; the old `oc.API_BASE + …` form passed against the same bad host),
and `tests/test_cost.py` pins the judge's worked arithmetic as a literal
(21,700 tokens · $0.069 for `estimate_judge(80, 1200, 600, 8)`). Re-run:

    python3 scripts/mutation_audit.py --modules openai_client
    -- caught=2, caught-crash=6, survived=4   (the two timeout constants, const + const-loud)
    python3 scripts/mutation_audit.py --modules cost
    -- caught=7, caught-crash=5, survived=0

`API_BASE`, `JUDGE_PROMPT_OVERHEAD_TOKENS` and
`JUDGE_OUTPUT_TOKENS_PER_CARD` no longer survive. The remaining
survivors in this lane are the timeout durations judged trivial above.

**Fix-round-2 re-run, same day, all four modules together:**

    python3 scripts/mutation_audit.py --modules page_store,cost,openai_client,anthropic_client
    -- caught=32, caught-crash=29, survived=9

Up from 27/29/14 pre-fix. All 9 remaining survivors are the timeout
constants judged trivial above (`EMBED_TIMEOUT_S`/`TRANSCRIBE_TIMEOUT_S`
in `openai_client.py`, `DEFAULT_TIMEOUT_S`/`_MAX_RETRY_AFTER_S` in
`anthropic_client.py`, one each at `const` and `const-loud`) plus the
one behaviour-equivalent `boolflip` in `page_store._atomic_json` also
judged above — no `gut` survivor in any of the four modules. Note for
whoever next diffs this table against the tree: `anthropic_client.py`'s
sha256 no longer matches the `5f0dc5a1175d` row above — this same task
(K-228 fix round 2) touched a comment in that file (Finding 9), which
changes the file's hash without changing any executable line.

---

# Fourth lane — `klausmate/plus.py` (K-249, 2026-09-16)

Klaus Plus on the add-on side landed with Task 8 (`klausmate/plus.py`:
the key, the endpoint every tagged call carries, the cached verdict) and
Task 10 (this task) registered it in `AUDIT_MODULES` — aqt-free, stdlib
`urllib` above one `_urlopen` its own test file replaces, the same shape
as the rest of this roster, so nearly every function is reachable
headless.

    python3 scripts/mutation_audit.py --modules plus

| module | sha256 | test file | checks | runtime |
|---|---|---|---:|---:|
| `klausmate/plus.py` | `132a43e61d97` | `tests/test_plus.py` (`a7ad723b1063`) | 22 | 0.04s |

| operator | mutations | caught | crash | survived |
|---|---:|---:|---:|---:|
| `gut` | 14 | 7 | 7 | **0** |
| `const` | 8 | 2 | 2 | 4 |
| `const-loud` | 8 | 2 | 2 | 4 |
| `boolflip` | 2 | 2 | 0 | 0 |
| **total** | **32** | **13** | **11** | **8** |

**No `gut` survivor.** Every function body in `plus.py` — `key`, `base`,
`active`, `endpoint`, `parse_quota`, `remember`, `note_refusal`, `_call`,
`refresh`, `portal_url`, `status_line`, `_day`, `client_version`,
`_cache` — is behaviourally pinned; emptying any of them fails
`test_plus.py`. Both booleans (`active`'s `status.startswith("refused")`
branch and `verdict`'s grace check at `:60,63`) are pinned too.

All 8 survivors are module-level constants, and none is worth a card:

* `DEFAULT_BASE` (`:21`) — self-referential, the K-135 shape in
  miniature: `test_plus.py:13` compares `plus.base({}) ==
  plus.DEFAULT_BASE`. Harmless — the fallback *path* (a bare key falls
  back to the shipped host) is pinned; the literal fly.dev hostname is
  not something a test should hardcode either.
* `TOKENS_PER_CARD`, `TOKENS_PER_TURN` (`:22,23`) — not merely
  self-referential but **unreferenced anywhere else in the file**, and
  the module's own comment says why: "the service's own constants
  (spec D1); shown, never enforced, here." `status_line`'s card/turn
  counts come from the server's pre-computed `human` snapshot
  (`meter.py`'s own copy of these same two numbers), never from this
  mirror. Genuinely free of runtime consequence today — decorative
  documentation of the service's units for a reader of this file, not
  dead code reachable from a real call.
* `TIMEOUT_S` (`:27`) — a request timeout, invisible headless against a
  fake `urlopen` that never blocks. Same "Timeouts" category as
  `EMBED_TIMEOUT_S`/`DEFAULT_TIMEOUT_S` in the third lane above.

## Bottom line for this lane

22 checks, and the tool cannot falsify a single function body. The only
survivors are two self-referential/decorative constants and one timeout
duration — the same shape this document keeps finding, and, as with the
third lane, none of it is in the code that spends money or handles a
key. `plus.py` never logs or reprints the licence key in any check
output either, consistent with the house rule the service side enforces
on its end.


# Fifth lane — Plan 2: `pertinence.py` and `lecture_recorder.py` (K-259, 2026-09-17)

Plan 2 added the two modules this lane covers — the pertinence judge
(index phase four) and the lecture recorder — and Task 7 registered both
in `AUDIT_MODULES`. Both are aqt-free above their own dividers and reach
the network only through a seam their tests replace (`client.complete`
for the judge, `lecture_recorder._transcribe` for the uploader), which is
the condition this audit needs.

One tool change came with them. `tests/test_lecture_recorder.py` lifts
the Klaus Plus service's own `wav_seconds` out of
`service/klausplus/proxy.py` **by AST** — never importing it — so its
WAV-header pin proves interop with the real metering code instead of a
retyped formula. The sandbox copied only `klausmate`, `tests` and the
klaus-test skill, so that read raised `FileNotFoundError` at module level
and the baseline was red, which aborts the run. `service/klausplus`
joined `SANDBOX_TREES` for exactly that one file: it is never a mutation
target (targets come from `klausmate/<module>.py` alone) and it is hashed
before and after like every other tree.

    python3 scripts/mutation_audit.py --modules pertinence,lecture_recorder

| module | sha256 | test files | checks | mutations |
|---|---|---|---|---:|
| `klausmate/pertinence.py` | `a0ade11b60f1` | `tests/test_pertinence.py` (`ad33f4ae04df`), `tests/test_index_queue.py` (`4ed85f023ce7`) | 55 + 162 | 39 |
| `klausmate/lecture_recorder.py` | `53f4e4d63149` | `tests/test_lecture_recorder.py` (`e0263c7d2e57`) | 41 | 48 |

Whole run: 106 test-file runs, 5,224 s — of which 1,200 s is four
300-second timeouts (see the recorder lane below) and the rest was
measured on a machine also running the full test loop, so treat the wall
clock as an upper bound, not a benchmark. The tree-integrity check
reported one changed repo file, `klausmate/config.md`, correctly
classified as "another session is editing the checkout" — it was this
same task's own doc edit landing mid-run, not a sandbox leak.

## `pertinence.py` — 39 mutations, **no `gut` survivor**

| operator | mutations | caught | crash | survived |
|---|---:|---:|---:|---:|
| `gut` | 18 | 6 | 12 | **0** |
| `const` | 7 | 1 | 1 | 5 |
| `const-loud` | 7 | 5 | 1 | 1 |
| `boolflip` | 7 | 3 | 1 | 3 |
| **total** | **39** | **15** | **15** | **9** |

Every function body — `build_request`, `parse_verdicts`, `judge`,
`judged_path`, `load_judged`, `save_judged`, `is_stale`, `entry_for`,
`rejected_nids`, `all_rejected`, `candidates` and the glue helpers —
is behaviourally pinned: emptying any of them fails the suite. The nine
survivors:

* **`MAX_TOKENS`, `MAX_CARD_CHARS`, `MAX_PAGE_CHARS` (`:20–22`)** — the
  `const` operator moves each by one (2048→2049, 4000→4001,
  12000→12001). The caps themselves ARE pinned, but by reading the
  constant, and a slice bound one character further along is invisible
  on any fixture short of the cap. `MAX_TOKENS` is worse off still: it
  is a request budget only the real API could reject. The "Timeouts"
  category of the third lane in miniature — a number whose consequence
  lives at the other end of a socket.
* **`JUDGED_FILE` (`:23`)** — survives BOTH `const` and `const-loud`,
  and it is the purest K-135 shape in this document: every read and
  every write goes through `judged_path`, so a test that saves and
  loads through this module can never observe the filename. The real
  consequence is real (renaming it orphans every existing user's
  verdicts) but it is not a consequence a test can see without
  hardcoding the literal, which is what the original vacuity bug was.
  Same category as `matches.json` and `layout.bin` elsewhere in the
  add-on; not worth a card.
* **`SYSTEM` (`:27`)** — `const` appends to the prompt and nothing
  notices; `const-loud` (which replaces it outright) IS caught. Exactly
  right: the prompt must exist and must be sent, and pinning its prose
  would be a text pin on wording that is meant to be tuned.
* **`bool@85:107` and `bool@196:42`** — `ensure_ascii=False` in
  `build_request`'s `json.dumps` and in `save_judged`'s `json.dump`.
  Flipping either changes byte-level escaping and nothing else; the
  judged.json round-trip is lossless with either setting, and the
  request stays valid JSON. Genuinely free of runtime consequence.
* **`bool@74:44` — the one real gap.** This is the INNER
  `"additionalProperties": False`, on each verdict object inside the
  `verdicts` array. `tests/test_pertinence.py:75` pins `strict`, the
  tool name, the forced `tool_choice` and the OUTER
  `input_schema.additionalProperties` — but not this one, so a flip to
  `True` would loosen the per-verdict object while every check still
  passes. The global constraint for this plan spells out all three
  halves of the strictness ("`strict: true`, `additionalProperties:
  false`, all fields `required`"); two are pinned, one is not. One
  clause added to that existing check closes it. Flagged for the final
  fix wave rather than fixed here — `tests/test_pertinence.py` is
  outside this task's file set.

## `lecture_recorder.py` — 48 mutations, **nine `gut` survivors**, and why

| operator | mutations | caught (incl. crash) | inconclusive | survived |
|---|---:|---:|---:|---:|
| `gut` | 28 | 19 | 2 | 7 |
| `const` | 2 | 1 | 0 | 1 |
| `const-loud` | 2 | 1 | 0 | 1 |
| `boolflip` | 16 | 3 | 2 | 11 |
| **total** | **48** | **24** (21 caught + 3 crash) | **4** | **20** |

The per-operator caught/crash split is not broken out here: the run's
JSON was not captured and re-running for that one column costs another
87 minutes of hung-timeout wall clock. The totals row carries the split.

**The pure half is solid.** Every `Chunker` transition, `wav_bytes`,
`chunk_path`, `Uploader._one` (including the Klaus Plus routing, the
quota readout and the refusal path), `_ensure_page` and
`requeue_leftovers` are caught. That is the half the spec calls "pinned
without Qt", and it is.

**The survivors are one cluster and two footnotes.** The cluster is the
Qt-side `Recorder`, which `tests/test_lecture_recorder.py` scopes out in
its own docstring — "this file never opens a real microphone":

* **`Recorder._tick` (`:419`, gut)** — the glue that actually reads the
  device, steps the chunker and flushes a closed chunk. The state
  machine under it is pinned exhaustively; the code that drives it, on a
  real `QTimer`, is not pinned anywhere headless. This is the most
  consequential survivor in the lane and it is a genuine gap, not a
  vacuity: nothing in the suite would notice `_tick` doing nothing.
  Live-checklist items 3, 4 and 11 on K-259 are what covers it today.
* **`start()`'s failure and success tails (`:364, :369, :395, :398, :409`
  → `return False`; `:415, :417` → the success pair; `:468` in `stop()`)**
  — every `return False` flipped to `True` claims a microphone that
  never opened, and the success tail flipped the other way claims none
  that did. Unreachable headless for the same reason (the one failure
  path a test CAN reach, PyQt6 being unimportable, is pinned and is
  caught).
* **`Recorder.is_recording`, `elapsed`, `queued` (`:339, :343, :347`)
  and `Uploader.queued` (`:164`)** — one-expression readouts. Their
  values do reach a user, through the dock's `m:ss · n to transcribe`
  label, and that label IS pinned — in `tests/test_pdf_dock.py`, which
  is not in `AUDIT_MODULES` and so is outside this lane's reach. Pinned
  elsewhere, invisible here.
* **`Chunker.__init__` (`:64`, gut) and `self.active = False` (`:67`,
  boolflip)** — `start()` assigns all three attributes unconditionally
  and every caller starts before ticking, so the constructor's values
  are dead on every real path. Not worth a card.
* **`Uploader.stop` (`:287`, gut)** — the sentinel is never queued, so
  the worker keeps waiting. It is a daemon thread and dies with the
  process either way; nothing observable is lost.
* **`TICK_MS` (`:293`, both const operators)** — a timer interval, the
  "Timeouts" category again.
* **`exist_ok=True` → `False` (`:458`)** — `_flush`'s `makedirs`. This
  one has a real consequence (the second chunk into an existing
  recordings folder would raise, be swallowed by `_flush`'s own
  `except Exception`, and be dropped) and it survives because the tests
  flush into a fresh directory. Small, real, and the cheapest of the
  lot to pin.

**The four inconclusive results are hangs, not survivors.**
`Uploader._ensure_thread` (`:167`), `Uploader._loop` (`:176`),
`daemon=True` (`:173`) and `while True` (`:177`) all mutate to "no
worker ever drains the queue", and the test file's `drain()` is
`Queue.join()`, which then blocks forever — 300 s each, twice each
(`gut` then `gut-cut`), which is the 1,200 s above. The harness is
right to refuse to score them: an unapplied or unfinished mutation
scored as "caught" is the exact failure this tool exists to detect. What
they do tell us is that the worker plumbing's failure mode under test is
a hang rather than a red check — worth knowing before anyone adds a
mutation-audit gate to CI on this module.

## Bottom line for this lane

The judge is pinned through and through — 39 mutations, not one function
body falsifiable, and the only finding is one missing clause on an
existing check (the inner `additionalProperties`). The recorder splits
cleanly in two: its pure half is as well pinned as the judge, and its Qt
half is pinned nowhere headless, by its own test file's stated scope.
Neither is a defect in the shipped code; both are honest statements of
where the evidence stops, and where Pouya's live checklist starts.
