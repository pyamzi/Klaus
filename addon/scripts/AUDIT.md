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
