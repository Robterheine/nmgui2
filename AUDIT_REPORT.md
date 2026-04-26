# NMGUI2 Code Audit Report
**Branch:** `claude/focused-yalow-445bee`  
**Date:** 2026-04-26  
**Tag at start:** `audit-r1-start`

---

## Round 1 — Discovery

### R1-A-001 / R1-D-001 — Dead `_f` function defined inside data-parsing loop
```
ID:          R1-A-001
Lens:        A (Python idiom) + D (bug chaser, confirmed cross-lens)
File:        nmgui2/app/dataset_check.py:153-158
Severity:    med
Effort:      S
Risk:        1
Description: Inside the `for raw in data_lines:` loop, a nested function `_f(i)` is
             defined on every iteration but is never called — neither inside the loop
             nor after it.  The actual float conversion is done independently by
             `col_vals()` (lines 176-186) using identical logic.  On a dataset with
             50,000 rows (MAX_ROWS limit), Python creates and discards 50,000 function
             objects per scan.
Proposed fix: Delete lines 153-158 entirely (the `def _f` block and its comment).
             `col_vals()` already handles all conversions.
Verification: `python3 -m py_compile nmgui2/app/dataset_check.py` passes; run the
             app and open a model — dataset report in the Info panel must still show
             row/ID/obs counts identically.
Status:      CONFIRMED (Round 2)
```

---

### R1-A-002 — `import re` inside `ScanWorker.run()` method body
```
ID:          R1-A-002
Lens:        A (Python idiom)
File:        nmgui2/app/workers.py:40
Severity:    low
Effort:      S
Risk:        1
Description: `import re` appears as the very first line of `ScanWorker.run()`.
             Python caches module imports so there is no repeated parse cost, but
             placing an import inside a method body is a code-quality violation
             (Lens A checklist item).  The module is used throughout run() for
             re.search() calls with inline pattern strings.
Proposed fix: Move `import re` to module top (line 1, after stdlib imports).
Verification: `python3 -m py_compile nmgui2/app/workers.py`; scan any directory.
Status:      CONFIRMED (Round 2)
```

---

### R1-A-003 — Regex patterns compiled inside per-model loop
```
ID:          R1-A-003
Lens:        A (Python idiom)
File:        nmgui2/app/workers.py:79, 82, 97
Severity:    low
Effort:      S
Risk:        1
Description: Three `re.search()` calls use inline pattern literals inside the
             `for f in sorted(p.iterdir()):` loop:
               line 79:  r'\$PROB(?:LEM)?\s+(.*?)(?:\n|\$)'  (IGNORECASE)
               line 82:  r'\$DATA\s+(\S+)'                   (IGNORECASE)
               line 97:  r'^;;\s*1\.\s*Based on:\s*(\S+)'    (MULTILINE|IGNORECASE)
             Python 3.10+ has a 512-entry compiled-pattern LRU cache so the same
             string + flags will hit the cache after the first call.  Actual perf
             impact is a dict lookup per call (negligible).  Hoisting to module-level
             `re.compile()` constants follows the stated best practice and makes the
             patterns visible at a glance.
Proposed fix: Add three module-level `_RE_*` constants and use `.search(content)`.
Verification: `python3 -m py_compile`; scan a directory, verify $PROBLEM / $DATA /
             Based-on fields still populate correctly.
Status:      CONFIRMED (Round 2) — value adjusted to low/style
```

---

### R1-B-001 — `setItem()` loops without `setUpdatesEnabled(False)` in models.py
```
ID:          R1-B-001
Lens:        B (PyQt6)
File:        nmgui2/tabs/models.py:614-626 and 706-719
Severity:    high
Effort:      S
Risk:        2
Description: `_on_scan()` (lines 614-626) and `_apply_filter()` (lines 706-719)
             both populate the models table with nested loops (rows × 10 cols =
             up to 500 `setItem()` calls).  Neither wraps the loop with
             `self.table.setUpdatesEnabled(False)`.  Qt schedules a repaint after
             each `setItem()` call; with 50 models × 10 cols, the table repaints
             ~500 times instead of once.  On slow hardware or over X11/MobaXterm
             this causes visible flicker and measurable lag.
             `setSortingEnabled(False/True)` is already handled correctly around
             both loops (prevents spurious sort during fill).
Proposed fix: Wrap both inner-loop bodies with:
               self.table.setUpdatesEnabled(False)
               # ... setItem loop ...
               self.table.setUpdatesEnabled(True)
             (inside the setSortingEnabled(False) / setSortingEnabled(True) span)
Verification: Scan a directory with 30+ models.  Before fix: visible row-by-row
             paint flicker.  After fix: table appears atomically.  Data shown must
             be identical.
Status:      CONFIRMED (Round 2)
```

---

### R1-C-001 — `_boot_time()` reads `/proc/stat` on every `is_alive()` call
```
ID:          R1-C-001
Lens:        C (I/O) + F (threading, confirmed cross-lens)
File:        nmgui2/app/detached_runs.py:141-150
Severity:    med
Effort:      S
Risk:        1
Description: `is_alive()` calls `_boot_time()` on every invocation when running on
             Linux.  `_boot_time()` reads `/proc/stat` (a synthetic kernel file) to
             extract the `btime` field.  The system boot time is a constant for the
             entire lifetime of the process — it never changes.
             `_refresh_run_list()` in models.py calls `is_alive()` once per active
             detached run, every 30 seconds.  For 5 active runs over a 2-hour
             bootstrap: 5 × (2×60×60/30) = 1,200 unnecessary file reads.
             On macOS the function is never called (no /proc), so no impact there.
             Windows: detached runs not supported.
Proposed fix: Cache the result in a module-level `_BOOT_TIME: float | None = None`
             variable; set it on first call and reuse thereafter.
Verification: grep for any path that mutates _boot_time result → none exist;
             `python3 -m py_compile`; start/stop detached run, verify is_alive
             returns correctly.
Status:      CONFIRMED (Round 2)
```

---

### R1-C-002 — `check_dataset()` reads dataset file per-model with no scan-level cache
```
ID:          R1-C-002
Lens:        C (I/O)
File:        nmgui2/app/workers.py:86-90
Severity:    med
Effort:      S
Risk:        1
Description: Inside `ScanWorker.run()`, `check_dataset(str(f), m['data_file'])` is
             called for each .mod/.ctl file.  `check_dataset()` reads the full
             dataset file (up to MAX_BYTES=50MB) on every call.  In a typical
             directory, all models reference the same dataset (e.g. `../../data.csv`).
             With 10 models, the dataset file is read 10 times per scan.
             The `data_file` string and the model directory (`p`) are constant within
             a single scan, so the resolved dataset path is identical for all models
             referencing the same string.  A dict keyed on `m['data_file']` scoped
             to `run()` (i.e., a local variable, not a module-level cache) gives
             correct deduplication with zero staleness risk.
Proposed fix: Add `_ds_cache: dict[str, object] = {}` before the per-model loop and
             check it before calling check_dataset().
Verification: Confirm dataset report still appears in Info panel; check that changing
             to a different directory (new scan) doesn't reuse a stale cache (it
             can't — the dict is local to run()).
Status:      CONFIRMED (Round 2)
```

---

### R1-B-002 — QPalette snapshots at `__init__` won't refresh on theme switch
```
ID:          R1-B-002
Lens:        B (PyQt6) + theme discipline
File:        nmgui2/tabs/models.py:365-366, 510
Severity:    med
Effort:      M
Risk:        3
Description: The editor (QPlainTextEdit) and notes_edit (QTextEdit) palettes are
             set once at __init__ with T('bg2') / T('fg') snapshots:
               line 365: self.editor.setPalette(...)
               line 510:  self.notes_edit.setPalette(...)
             MainWindow._apply_theme() does not refresh these palettes.  After a
             dark→light switch, the editor retains dark colors.
Proposed fix: Add a refresh_theme() method to ModelsTab and call it from
             MainWindow._apply_theme(); rebuild the two QPalette objects inside it.
Risk of breakage: 3 (touches theme dispatch path — needs the audit discipline
             4-lens check before shipping)
Status:      CONFIRMED (Round 2) — Bucket C (theme fix, separate session)
```

---

### R1-B-003 — RunPopup / WatchLogPopup stylesheet snapshot on theme switch
```
ID:          R1-B-003
Lens:        B (PyQt6) + theme discipline
File:        nmgui2/dialogs/run_popup.py:153-165, 431-438
Severity:    med
Effort:      M
Risk:        3
Description: Both RunPopup._apply_theme() and WatchLogPopup._apply_theme() build
             inline stylesheets with T() snapshots.  They are called once at
             __init__.  MainWindow._apply_theme() does not find these dialogs via
             findChildren() because they use Qt.WindowType.Window (top-level windows,
             not children in the widget hierarchy).  If the user switches theme
             while a run is in progress, popup colors stay at the old theme.
Status:      CONFIRMED (Round 2) — Bucket C (theme fix, separate session)
```

---

### R1-B-004 — `set_reference()` calls beginResetModel/endResetModel unnecessarily
```
ID:          R1-B-004
Lens:        B (PyQt6)
File:        nmgui2/tabs/models.py:79
Severity:    low
Effort:      S
Risk:        2
Description: ModelTableModel.set_reference() ends with beginResetModel()/
             endResetModel(), which forces Qt to re-query every cell of the table.
             Only COL_NAME (suffix "[REF]") and COL_DOFV change; emitting
             dataChanged() for those two columns across all rows would be cheaper.
             set_reference() is user-triggered (right-click menu), so perf impact
             is immeasurable.  Bucket A is marginal given low value.
Status:      CONFIRMED (Round 2) — Bucket C (low value, not on a hot path)
```

---

### R1-E-001 — RunPopup/WatchLogPopup use hardcoded font names without Linux fallback
```
ID:          R1-E-001
Lens:        E (cross-OS)
File:        nmgui2/dialogs/run_popup.py:108, 389
Severity:    low
Effort:      S
Risk:        2 (visual change on Linux)
Description: Console font set as:
               QFont('Menlo' if IS_MAC else 'Consolas', 11)
             On macOS: Menlo is always present. On Windows: Consolas is present.
             On Linux: Consolas is often absent; Qt silently falls back to the
             system default monospace, which may differ from the rest of the app.
             theme.monospace_font(11) already provides a proper fallback chain
             (DejaVu Sans Mono, Liberation Mono, Ubuntu Mono, Courier New).
Proposed fix: Replace with `monospace_font(11)` from theme.py (already imported
             in models.py; needs to be imported in run_popup.py).
Risk note: Changes font appearance on Linux for users who don't have Consolas
           installed. Strictly an improvement, but §1 prohibits appearance changes.
Status:      CONFIRMED (Round 2) — Bucket C (cross-OS visual consistency, low risk)
```

---

### R1-F-001 — RunWorker._proc write/read race between run() and stop()
```
ID:          R1-F-001
Lens:        F (threading)
File:        nmgui2/app/workers.py:157, 166, 175
Severity:    low
Effort:      M
Risk:        3
Description: RunWorker.run() assigns self._proc = subprocess.Popen(...) at line 157.
             RunWorker.stop() / stop_hard() check `if not self._proc:` before using
             it.  There is a tiny window where stop() is called after the thread
             starts but before self._proc is assigned.  In that window, stop()
             returns without doing anything.  In practice the run button is only
             accessible to the user after the popup is visible and the thread is
             started, so the window is sub-millisecond.  No lock needed — CPython
             GIL makes bool/None reference reads atomic.
Status:      CONFIRMED (Round 2) — Bucket C (theoretical, not practically triggerable)
```

---

### R1-G-001 — All tabs (incl. scipy/matplotlib) imported eagerly at startup
```
ID:          R1-G-001
Lens:        G (memory & startup)
File:        nmgui2/app/main_window.py:15-20, nmgui2/tabs/uncertainty.py:59-77
Severity:    med
Effort:      L
Risk:        3
Description: All 9 tabs are instantiated in MainWindow.__init__() including
             ParameterUncertaintyTab which triggers top-level imports of scipy
             (≈ 200ms cold), matplotlib (≈ 300ms cold), and numpy.  A user who
             never opens the Uncertainty tab pays this startup cost every launch.
             Lazy instantiation (create tab widget on first nav click) would help,
             but requires restructuring signal wiring in _build_ui().
Status:      CONFIRMED (Round 2) — Bucket C (L effort, non-trivial restructuring)
```

---

### R1-G-002 — Nav icon pixmaps recreated on every theme switch
```
ID:          R1-G-002
Lens:        G (memory & startup)
File:        nmgui2/app/main_window.py:388-392, nmgui2/widgets/_icons.py:40
Severity:    low
Effort:      S
Risk:        1
Description: _apply_theme() regenerates all 9 nav icon pixmaps by calling
             _make_nav_icon() for each.  Each call does QPainter setup, geometry
             calculations, and polygon/path drawing.  The result is not cached.
             At ~2 theme switches per session this is ~18 pixmap draws, taking
             perhaps 5ms total.  Caching per (name, size, color_hex) would avoid
             redundant work on repeated toggles.
Status:      CONFIRMED (Round 2) — Bucket C (negligible in practice)
```

---

## Round 2 — Independent Verification

Each finding re-checked against file+line without referencing Round 1 reasoning.

| ID | File:line | Verdict | Notes |
|---|---|---|---|
| R1-A-001 | dataset_check.py:153-158 | **CONFIRMED** | `def _f(i)` inside loop, `col_vals` does same work |
| R1-A-002 | workers.py:40 | **CONFIRMED** | `import re` is line 40 inside `run()` |
| R1-A-003 | workers.py:79,82,97 | **CONFIRMED** — value=low | Cache hit makes perf negligible; code quality issue only |
| R1-B-001 | models.py:614-626,706-719 | **CONFIRMED** | Both loops lack setUpdatesEnabled wrapper |
| R1-C-001 | detached_runs.py:141-150 | **CONFIRMED** | `_boot_time()` reads /proc/stat uncached; Linux only |
| R1-C-002 | workers.py:86-90 | **CONFIRMED** | No per-scan dataset-path cache |
| R1-B-002 | models.py:365,510 | **CONFIRMED** | QPalette set at init, not refreshed in _apply_theme |
| R1-B-003 | run_popup.py:165,438 | **CONFIRMED** | T() snapshot, not reached by findChildren walk |
| R1-B-004 | models.py:79 | **CONFIRMED** — Bucket C | set_reference is not a hot path |
| R1-E-001 | run_popup.py:108,389 | **CONFIRMED** — Bucket C | Appearance change, §1 forbids |
| R1-F-001 | workers.py:157,166 | **CONFIRMED** — Bucket C | Sub-ms race, not practically reachable |
| R1-G-001 | main_window.py + uncertainty.py | **CONFIRMED** — Bucket C | L effort |
| R1-G-002 | main_window.py:388 | **CONFIRMED** — Bucket C | Low value |

---

## Round 3 — Triage

### Bucket A — Implement now

| ID | File | Fix | Risk | Effort | Value |
|---|---|---|---|---|---|
| R1-A-001 | dataset_check.py:153-158 | Delete dead `_f` function | 1 | S | high |
| R1-A-002 | workers.py:40 | Hoist `import re` | 1 | S | low |
| R1-A-003 | workers.py:79,82,97 | Module-level `re.compile()` constants | 1 | S | low |
| R1-C-001 | detached_runs.py:141-150 | Cache `_boot_time()` result | 1 | S | med |
| R1-C-002 | workers.py:86-90 | Per-scan dataset cache dict | 1 | S | med |
| R1-B-001 | models.py:614-626,706-719 | `setUpdatesEnabled(False)` wrapper | 2 | S | high |

### Bucket C — Flag for later (do not fix in this audit)

See `STRUCTURAL_FLAGS.md`.

---

## Round 4 — Implementation status

| ID | Status | Commit |
|---|---|---|
| R1-A-001 | PENDING | — |
| R1-A-002 | PENDING | — |
| R1-A-003 | PENDING | — |
| R1-C-001 | PENDING | — |
| R1-C-002 | PENDING | — |
| R1-B-001 | PENDING | — |
