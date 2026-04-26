# NMGUI2 — Structural Flags for Future Sessions

These items were identified during the 2026-04-26 audit but are **not fixed here**.
Each requires a separately scoped session.

---

## SF-001 — Editor / notes_edit palettes are theme-switch stale snapshots

**Lens:** B (PyQt6) + audit discipline theme lens  
**Files:** `nmgui2/tabs/models.py:365, 510`  
**Why flag:**
The QPlainTextEdit (editor) and QTextEdit (notes_edit) in ModelsTab set their
QPalette at `__init__` time using `T('bg2')` / `T('fg')` snapshots.  After a
dark→light theme switch, the editor background stays dark.  `MainWindow._apply_theme()`
does not call any refresh method on ModelsTab.

**Suggested next step:**  
Add `refresh_theme()` to ModelsTab; call it from MainWindow._apply_theme().  Run
the 4-lens audit discipline check (correctness, theme, Qt-style, clean-code) before
shipping.  Estimated effort: 1-2 hours.

**Do NOT fix in this audit.**

---

## SF-002 — RunPopup / WatchLogPopup stylesheet not refreshed on theme switch

**Lens:** B (PyQt6)  
**Files:** `nmgui2/dialogs/run_popup.py:153-165, 431-438`  
**Why flag:**
Both popup types call `_apply_theme()` once at `__init__` and build inline
stylesheets with `T()` snapshots.  They are top-level `Qt.WindowType.Window`
widgets; `findChildren()` in MainWindow does not reach them.  Opening a run popup
then switching theme leaves the popup at the old colors.

**Suggested next step:**  
MainWindow should maintain a list of open popups and call `_apply_theme()` on each
during theme switches.  Or popups could connect to a `theme_changed` signal.
Estimated effort: 1 hour.  Apply 4-lens audit discipline before shipping.

**Do NOT fix in this audit.**

---

## SF-003 — RunPopup / WatchLogPopup use hardcoded Menlo/Consolas without Linux fallback

**Lens:** E (cross-OS)  
**Files:** `nmgui2/dialogs/run_popup.py:108, 389`  
**Why flag:**
`QFont('Menlo' if IS_MAC else 'Consolas', 11)` — on Linux, Consolas is typically
absent.  Qt silently falls back to the system default monospace, which may differ
from the fallback chain in `theme.monospace_font()`.  The fix (replacing with
`monospace_font(11)`) is trivial but changes the visual appearance on Linux, which
§1 of the audit prohibits.

**Suggested next step:**  
In a UI-polish session, replace hardcoded font names with `monospace_font(11)` from
`nmgui2.app.theme`.  Also import it in run_popup.py.  Estimated effort: 10 minutes.

**Do NOT fix in this audit.**

---

## SF-004 — All tabs (incl. scipy/matplotlib) imported eagerly at startup

**Lens:** G (memory & startup)  
**Files:** `nmgui2/app/main_window.py:15-20`, `nmgui2/tabs/uncertainty.py:59-77`  
**Why flag:**
All 9 tab widgets are instantiated in `MainWindow.__init__()`.  `ParameterUncertaintyTab`
triggers top-level imports of scipy (~200ms), matplotlib (~300ms), and numpy.  A user
who never visits the Uncertainty tab pays these costs on every launch.

**Suggested next step:**  
Lazy-initialise heavy tabs (uncertainty, vpc, sim_plot) — create them only on first
`_nav_to(index)` call.  Requires restructuring how signals are wired.  Estimated
effort: 3-4 hours.  Profile startup time before/after to confirm benefit.

**Do NOT fix in this audit.**

---

## SF-005 — `ModelTableModel.set_reference()` uses beginResetModel/endResetModel

**Lens:** B (PyQt6)  
**Files:** `nmgui2/tabs/models.py:79`  
**Why flag:**
`set_reference()` triggers a full model reset (every cell re-queried) when only
`COL_NAME` and `COL_DOFV` columns change.  Emitting `dataChanged()` for those two
columns across all rows would be correct and cheaper.  Not on a hot path; impact is
imperceptible in practice.

**Suggested next step:**  
Replace `beginResetModel()/endResetModel()` with two `dataChanged()` emissions
covering `COL_NAME` and `COL_DOFV` columns, all rows.  Estimated effort: 20 minutes.

**Do NOT fix in this audit.**

---

## SF-006 — RunWorker._proc assignment race with stop()

**Lens:** F (threading)  
**Files:** `nmgui2/app/workers.py:157, 166-175`  
**Why flag:**
`RunWorker.run()` assigns `self._proc` at line 157 after the thread starts.
`stop()` / `stop_hard()` guard with `if not self._proc:`.  There is a sub-millisecond
window where `stop()` could fire before `self._proc` is assigned, causing a silent
no-op.  In practice unreachable: the Stop button only appears after the popup is
fully shown and `run()` is well past line 157.  CPython GIL makes the None check
atomic.

**Suggested next step:**  
Low enough risk that a simple `threading.Lock` or check for `isRunning()` in stop()
would suffice.  Or document the invariant with a comment.  Estimated effort: 10 min.

**Do NOT fix in this audit.**

---

## SF-007 — Nav icon pixmaps recreated on every theme switch without caching

**Lens:** G  
**Files:** `nmgui2/app/main_window.py:388-392`, `nmgui2/widgets/_icons.py:40`  
**Why flag:**
All 9 nav icon pixmaps are regenerated on every theme switch.  No cache exists.
Each call runs QPainter setup + path drawing.  At ~2 theme switches per typical
session the total overhead is ~5ms — immeasurable in practice.

**Suggested next step:**  
Add a module-level `dict[tuple, QPixmap]` cache keyed on `(name, size, color_hex)`.
Estimated effort: 20 minutes.  Low priority.

**Do NOT fix in this audit.**

---

## SF-008 — `parser.py` is 1600+ lines with mixed parsing responsibilities

**Lens:** A  
**Files:** `nmgui2/parser.py`  
**Why flag:**
Parses .lst, .ext, .cor, .cov, and table files in one module.  No clear unit
boundaries make it risky to touch.  Bug fixes in one section can cascade.

**Suggested next step:**  
Dedicated scoped session to split into `parser/lst.py`, `parser/ext.py`,
`parser/tables.py` with shared helpers in `parser/_common.py`.  Requires a
regression corpus of real .lst files.  Estimated: 1-2 days.

**Do NOT fix in this audit.**
