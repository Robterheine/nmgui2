# NMGUI2 v2.5 — User Guide

A complete feature reference for experienced pharmacometricians. If you are coming from **Pirana** or **PopED**, the structure below is written to let you locate the equivalent workflow quickly: each section states *where* the feature lives in the UI and *how* to use it.

---

## Contents

1. [Required and optional software](#1-required-and-optional-software)
2. [Orientation — window layout](#2-orientation--window-layout)
3. [Models tab](#3-models-tab)
4. [Model detail panel (right-hand pane)](#4-model-detail-panel-right-hand-pane)
5. [Tree tab](#5-tree-tab--model-lineage)
6. [Evaluation tab](#6-evaluation-tab--gof-and-diagnostics)
7. [VPC tab](#7-vpc-tab)
8. [Uncertainty tab](#8-uncertainty-tab--bootstrap--sir)
9. [History tab](#9-history-tab)
10. [Settings tab](#10-settings-tab)
11. [Dialogs invoked from the model table](#11-dialogs-invoked-from-the-model-table)
12. [Global keyboard shortcuts](#12-global-keyboard-shortcuts)
13. [Files written by NMGUI2](#13-files-written-by-nmgui2)
14. [Mapping: Pirana / PopED → NMGUI2](#14-mapping-pirana--poped--nmgui2)

---

## 1. Required and optional software

NMGUI2 is a pure Python/PyQt6 desktop app. It never spawns a browser and never contacts a server (other than an optional GitHub update check). To get the **full feature surface**, the following external tools should be on `PATH`.

### Required for the core app

| Tool | Minimum | Why | Check |
|---|---|---|---|
| Python | 3.10 | Runtime | `python3 --version` |
| PyQt6, pyqtgraph, numpy, matplotlib, scipy | — | `pip install -r requirements.txt` | `pip list` |

The app launches and can browse/compare models even with nothing else installed.

### Required to *run* NONMEM models from inside NMGUI2

| Tool | Minimum | Notes |
|---|---|---|
| NONMEM | 7.4 | Licensed install from ICON |
| PsN | 5.0 | `execute`, `vpc`, `bootstrap`, `scm`, `sir`, `cdd`, `npc`, `sse` must be on PATH |
| Perl | 5.16 | Required by PsN. macOS/Linux: system Perl. Windows: Strawberry Perl |

NMGUI2 autodetects these; paths can be overridden in **Settings**.

### Required for VPC generation

| Tool | Minimum | Install |
|---|---|---|
| R | 4.0 | `Rscript` on PATH |
| R package `vpc` | — | `install.packages("vpc")` |
| R package `xpose` | — | `install.packages("xpose")` |
| R package `xpose4` | — | classic xpose |
| R package `tidyverse` | — | required by `xpose` |
| R package `ggplot2` | — | required by `vpc`/`xpose` |
| RStudio Desktop | — | optional; "Open RStudio" button in VPC tab |

One-liner:
```bash
Rscript -e 'install.packages(c("vpc","xpose","xpose4","tidyverse","ggplot2"), repos="https://cran.r-project.org")'
```

The VPC tab displays a green ✓ / red ✗ per package at the top of the panel on startup so you can see at a glance what is installed.

### Required for Uncertainty tab

Bootstrap and SIR runs use PsN's `bootstrap` and `sir` commands — so PsN + NONMEM suffice; no additional R packages are needed. Loading *existing* bootstrap/SIR results also works without PsN installed.

### Not required but recommended

| Tool | Benefit |
|---|---|
| Git | Pull updates (`git pull`) |
| RStudio | Click-through editing of the generated VPC R script |

---

## 2. Orientation — window layout

```
┌───────────────────────────────────────────────────────┐
│  NMGUI  v2.5.0                    [? About] [RStudio] │  ← toolbar
├─────┬─────────────────────────────────────────────────┤
│Tabs │   tab content (Models / Tree / Evaluation / …)  │
│ M   │                                                 │
│ T   │                                                 │
│ E   │                                                 │
│ V   │                                                 │
│ U   │                                                 │
│ H   │                                                 │
│ S   │                                                 │
└─────┴─────────────────────────────────────────────────┘
│  <n> models, <n> with results · <DIR> · scanned in 0.1s │ ← status bar
└───────────────────────────────────────────────────────┘
```

- **Left sidebar**: seven tabs (Models / Tree / Evaluation / VPC / Uncertainty / History / Settings). Keyboard ⌘1–⌘7 (macOS) or Ctrl+1–Ctrl+7 (Win/Linux).
- **About button**: opens the About dialog (version, environment, credits).
- **Open RStudio button**: launches RStudio if installed.
- **Status bar**: model count, active directory, last scan duration, and transient messages from actions.
- **Dark / light theme**: toggled from Settings; persisted in `~/.nmgui/settings.json`.

---

## 3. Models tab

**Where:** left sidebar → *Models* (⌘1 / Ctrl+1). This is the home view.

**Purpose:** pick a directory, see every `.mod` / `.ctl` inside it with their outcomes, act on any model.

### Directory controls (top row)
- **Browse…** — pick a folder; `.mod` and `.ctl` files are scanned recursively one level.
- **⭮ Rescan** (⌘R / Ctrl+R) — rerun the scan after you added/modified models on disk.
- **+ Bookmark** / **Bookmarks ▾** — save the current directory for one-click recall. Stored in `~/.nmgui/bookmarks.json`.
- **Filter ▾** — *All / Completed / Failed / Starred*.
- **Search box** — free-text filter on stem, comment, notes, status tag.

### Table columns
| Column | Source | Notes |
|---|---|---|
| ★ | metadata | Star/unstar with `Space` or right-click |
| Stem | file | e.g. `run12` |
| Status tag | metadata | Base / Candidate / Final / Reject (colored) |
| OFV | `.lst` / `.ext` | Final objective function value |
| ΔOFV | — | Relative to **reference model** (see below) |
| Min. | `.lst` | ✓ = successful, ✗ = failed, — = not available |
| Cov | `.lst` | Covariance step result |
| Cond# | `.lst` | Condition number (correlation matrix) |
| Method | `$EST` | FO / FOCE / FOCEI / IMP / SAEM / BAYES |
| #ID | dataset | Individuals |
| #obs | dataset | Observations |
| #par | `.lst` | Estimated parameters |
| AIC | — | `OFV + 2·#par` |
| Runtime | `.lst` | Reported or measured |
| Comment | metadata | Editable in Info panel |

Row colours: **green** = converged, **red** = failed / terminated, **orange** = stale (source newer than `.lst`) or boundary warning.

Sort by clicking any header. Filter state persists per directory.

### Reference model (for ΔOFV)
Right-click any successful model → **Set as reference**. All ΔOFV values recompute against this model. The reference is marked with a diamond icon in the star column. Clearing is via right-click → **Clear reference**.

### Right-click context menu
- **Toggle star** — also `Space`.
- **Set / Clear reference** — see above.
- **Duplicate…** — opens the duplicate dialog (new run number; copies `.mod`, renames table outputs). See §11.
- **Compare with…** — opens the two-model comparison dialog.
- **Open workbench…** — the multi-model table. See §11.
- **QC report…** — HTML quality-control report with PASS/WARN/FAIL checklist.
- **Open run report** — the HTML version of the Output tab, saved to a temp file.
- **View `.lst`** — raw listing in a separate viewer window.
- **NM-TRAN messages** — shows NM-TRAN compilation warnings/errors.
- **View run record** — the immutable audit record for this run.

### Keyboard
- `↑ / ↓` — move row.
- `Enter` — jump focus to Output sub-tab of detail panel.
- `Space` — toggle star.

---

## 4. Model detail panel (right-hand pane)

The panel under the Models table has sub-tabs:

### 4.1 Parameters
Full THETA / OMEGA / SIGMA table. Parameter names are parsed from comments in `$THETA`/`$OMEGA`/`$SIGMA` blocks. Columns include estimate, SE, RSE%, 95% CI, and SD for variance parameters. Handles `BLOCK(n)` and `BLOCK(n) SAME` correctly.

- THETA / OMEGA / SIGMA blocks are **collapsible** — click the section header to fold.
- **Export CSV…** — full table as CSV.
- **Export HTML…** — self-contained HTML report (for emailing to a collaborator).

### 4.2 Editor
Syntax-highlighted `.mod` editor.
- **Save** writes the file back and marks the model stale (so the row turns orange).
- Never overwrites `.lst`. Re-run the model to regenerate outputs.

### 4.3 Run
Launch any PsN tool on the current model.

- **Tool dropdown** — execute / vpc / bootstrap / scm / sir / cdd / npc / sse.
- **Extra args** — free-form arguments appended to the command.
- **Clean previous run dir** — checkbox; deletes the `<stem>/` subdirectory before running.
- **Run** — spawns PsN as a subprocess; stdout/stderr stream live to the console.
- **Stop** — sends SIGINT/terminate to the process tree.

Every run creates a **run record** (see §11).

### 4.4 Info
- **Dataset card** (collapsible) — path, row count, columns, integrity warnings (missing file, non-monotonic TIME, duplicate doses, extreme DV, high BLQ).
- **Annotation card** — status tag (Base/Candidate/Final/Reject) and comment line, visible in the table.
- **Notes card** — free-form multiline notes; persisted in `~/.nmgui/model_meta.json`.

### 4.5 Output
Structured HTML rendering of the `.lst` in-panel:
1. **Summary strip** — stem, OFV, minimisation, covariance, method, runtime.
2. **Estimation steps** (if chained `$EST`) — one row per step with OFV, ΔOFV between steps, runtime, significant digits, termination reason.
3. **NM-TRAN warnings**.
4. **Convergence** — iteration history from `.ext`.
5. **Parameter estimates** with SEs.
6. **ETABAR** with p-values.
7. **Shrinkage** (ETA and EPS).
8. **Correlation and covariance matrices**.
9. **Eigenvalues and condition number**.

Use *Open in browser* to save the full HTML and view it externally.

---

## 5. Tree tab — model lineage

**Where:** ⌘2 / Ctrl+2.

Interactive force-directed node graph of model genealogy. Parent is taken from the PsN header line `;; 1. Based on: NNN` or from the "parent" field you set manually (Info → Annotation).

- **Scroll** to zoom, **drag** to pan.
- **Double-click** a node — selects that model in the Models tab.
- **Starred** models rendered with a gold border; **final** models with a green border.
- Dark-/light-theme aware (v2.5.0).

Useful as the top-down equivalent of Pirana's run hierarchy view.

---

## 6. Evaluation tab — GOF and diagnostics

**Where:** ⌘3 / Ctrl+3.

Select a model in the Models tab first. On selection, NMGUI2 auto-loads the first `sdtab*` table file found next to the `.mod` (or inside its run directory). Manual override via **Browse…**. **Exclude MDV=1** is on by default.

Pills across the top switch sections:

### 6.1 GOF (2×2)
DV vs PRED | DV vs IPRED | CWRES vs TIME | CWRES vs PRED — with unity / zero reference lines.

Inner pill strip also exposes:
- **CWRES histogram** with normal distribution overlay.
- **QQ plot** — CWRES vs theoretical quantiles; Shapiro–Wilk test statistic and 95% band.
- **ETA vs Covariate** — scatter of each ETA against continuous covariates, LOESS overlay.

### 6.2 Individual Fits
Paginated DV/IPRED/PRED vs TIME per subject. Configurable columns per page. Space / arrow keys page through.

### 6.3 OFV Waterfall
Ranked ΔOFV bar chart across **all** completed models in the current directory. Reads `.phi` files. Useful at the end of a model-building sequence.

### 6.4 Convergence
Parameter trajectories from the `.ext` file for the selected model — one trace per parameter. Detects divergence patterns (oscillating, flat, runaway).

### 6.5 Data Explorer
Interactive scatter of the loaded table file:
- Any column on X / Y.
- **Colour by** any column (categorical or continuous).
- Multi-filter (AND) — add rows of `column op value`.
- Paginated data table view.
- Export filtered selection.

Truncation warning if the source table exceeds 15 000 rows — the first 15 000 are plotted.

---

## 7. VPC tab

**Where:** ⌘4 / Ctrl+4.

### 7.1 Backend selection
Three R backends:
- **vpc** — Ronny Keizer's package; fastest; binned PI / CI.
- **xpose** — tidyverse-based rendering.
- **xpose4** — classic Uppsala xpose.

Availability indicator top-right shows ✓ / ✗ per package.

### 7.2 Inputs
| Field | Purpose |
|---|---|
| Run no | Used by xpose / xpose4 to locate the run directory |
| VPC folder | PsN `vpc` output directory (contains `m1/`, `vpc_results.csv`) — used by `vpc` backend |
| Run directory | For xpose backends; contains `sdtab*`, `.ext`, `.phi` |
| Stratify | Column name; validated against header before running; warns if >20 levels |
| PI (low / high) | Prediction interval percentiles, default 0.05–0.95 |
| CI (low / high) | Confidence interval percentiles, default 0.05–0.95 |
| LLOQ | Lower limit of quantification; rows below are shaded |
| Bins | Number of bins for `vpc` backend |
| Log Y axis | Toggle |
| Prediction-corrected (pcVPC) | Toggle |

### 7.3 Run flow
1. Click **Generate VPC**. R is invoked via `Rscript` on a generated script.
2. Console panel streams stdout/stderr live.
3. On success, the PNG is displayed in the viewer panel.
4. **Open in viewer** — system default image viewer.
5. **Save high-res PNG…** — re-executes the R script with a 4× resolution.
6. **Save PDF…** — re-executes with `pdf()` device (vector output).

### 7.4 R Script panel
A toggle between the **Console** and **R Script** view. You can edit the generated R script before running — for example, to add custom ggplot themes, change colours, or add annotations. Changes are saved for the session. **Reset** restores the template.

### 7.5 Stop
Click **Stop** to terminate the R process tree.

---

## 8. Uncertainty tab — Bootstrap & SIR

**Where:** ⌘5 / Ctrl+5.

Two sub-sections switched by the top pill: **Bootstrap** / **SIR**.

### 8.1 Bootstrap
Workflow:
1. **Model** — select one from the Models tab first (carried over).
2. Either **Run bootstrap** (spawns PsN `bootstrap`) or **Load results folder…** (an existing `bootstrap_*/raw_results_*.csv`).
3. **Samples / Threads / Stratify by** are editable pre-run.

Outputs:
- **Parameter table** — for each THETA / OMEGA / SIGMA: original estimate, bootstrap median, bias%, 2.5–97.5 percentile CI.
- **Forest plot** — normalized distributions across parameters.
- **Diagnostics**:
  - Completion rate (% of runs that converged).
  - Bias (median vs point estimate).
  - Parameter correlations.
  - CI validity — does the CI contain the original estimate?
  - Boundary proximity — warns if OMEGAs cluster near zero.
- **Overall assessment** — PASSED / ACCEPTABLE / WARNING / FAILED banner.

### 8.2 SIR
Same layout. Outputs:
- **ESS** (effective sample size).
- **Resampling efficiency** (ESS / n_resample).
- **Degeneracy detection**.
- **Weighted percentile CIs**.
- **Overall assessment** with one-line interpretation.

### 8.3 Console
Live PsN output is streamed into the console at the bottom. **Reset** clears.

---

## 9. History tab

**Where:** ⌘6 / Ctrl+6.

Chronological log of every PsN run started from inside NMGUI2 (last 200 entries).

| Column | Meaning |
|---|---|
| Status | Running / Completed / Failed |
| Stem | Model |
| Tool | execute / vpc / bootstrap / … |
| Command | Full command line (click to copy) |
| Started / Duration | Timestamps |

Double-click any row to open the full **Run Record** (see §11).

---

## 10. Settings tab

**Where:** ⌘7 / Ctrl+7. All settings persist in `~/.nmgui/settings.json`.

- **Theme** — Dark / Light / Follow system.
- **Font size** — base font point size.
- **Paths** — manual overrides for:
  - PsN `execute`
  - NONMEM binary / script
  - R `Rscript`
  - RStudio application
- **Directory bookmarks** — add / remove / reorder.
- **GitHub update check** — on by default; pings `/releases/latest` once per launch. Compares tuple-wise (`2.10.0 > 2.9.0`).
- **Debug logging** — toggles verbose logging to `~/.nmgui/nmgui_debug.log`.
- **Open `.nmgui/` folder** — reveals the config directory in the system file manager.

---

## 11. Dialogs invoked from the model table

### 11.1 Compare (`comparison.py`)
Right-click → **Compare with…**, pick a second model. Modal dialog with:
- Side-by-side parameter table with aligned rows.
- Statistics strip: ΔOFV, ΔAIC, ΔBIC, Δ#par, **LRT p-value** (chi² on `|ΔOFV|` with `|Δ#par|` df, sign-aware since v2.5.0), and a verdict string (*nested: significant at α = 0.05* / *ns* / *non-nested: LRT not applicable*).
- Export CSV / HTML.

### 11.2 Workbench (`workbench.py`)
Right-click → **Open workbench…** (or toolbar button in Models tab). Modal sortable table of all completed models in the current directory: OFV, ΔOFV, AIC, BIC, #par, LRT p-value (against a chosen reference), minimisation status, covariance status. Pick the reference from a dropdown at the top. **Export CSV**.

### 11.3 QC report (`app/qc_report.py`)
Right-click → **QC report…**. Opens a self-contained HTML page with a PASS / WARN / FAIL checklist:
- Termination status.
- Covariance step.
- Condition number (< 100 / 100–1000 / >1000).
- Maximum %RSE.
- Parameter correlations (|r| ≥ 0.95).
- Shrinkage (ETA / EPS).
- ETABAR p-values.
- OMEGA near boundary.

Saveable from the browser for archival.

### 11.4 Duplicate (`duplicate.py`)
Right-click → **Duplicate…**. Clones the `.mod` with an incremented run number; offers to copy dataset references.

### 11.5 LST viewer (`lst_viewer_dialog.py`)
Raw `.lst` in a monospaced search-enabled viewer.

### 11.6 NM-TRAN messages (`nmtran.py`)
Parsed NM-TRAN compilation output (warnings, errors). Useful to spot `WARNING: DES COMPARTMENT NOT USED` and similar.

### 11.7 Run record (`run_record.py`)
Immutable record of a single run:
- Run UUID.
- SHA-256 hash of control stream.
- SHA-256 hash of dataset.
- NONMEM / PsN / NMGUI versions.
- Start / end timestamps.
- Final OFV (including `0.0`), minimisation status, covariance status.
- Full command line.

**Export JSON** — save a standalone file for the archive.

### 11.8 Shortcuts (`shortcuts.py`)
Opens a reference card of all keyboard shortcuts.

### 11.9 About (`about.py`)
App version, author, environment (Python / PyQt6 / pyqtgraph / numpy versions), credits.

---

## 12. Global keyboard shortcuts

| Action | macOS | Win/Linux |
|---|---|---|
| Models tab | ⌘1 | Ctrl+1 |
| Tree tab | ⌘2 | Ctrl+2 |
| Evaluation tab | ⌘3 | Ctrl+3 |
| VPC tab | ⌘4 | Ctrl+4 |
| Uncertainty tab | ⌘5 | Ctrl+5 |
| History tab | ⌘6 | Ctrl+6 |
| Settings tab | ⌘7 | Ctrl+7 |
| Open directory | ⌘O | Ctrl+O |
| Rescan | ⌘R | Ctrl+R |
| Move row | ↑ / ↓ | ↑ / ↓ |
| Jump to Output | Enter | Enter |
| Toggle star | Space | Space |

---

## 13. Files written by NMGUI2

All user state lives in `~/.nmgui/` (created on first launch):

| File | Purpose |
|---|---|
| `settings.json` | Theme, paths, window geometry, splitter sizes |
| `model_meta.json` | Stars, status tags, comments, notes, parent overrides |
| `bookmarks.json` | Directory bookmarks |
| `runs.json` | Run history (last 200) |
| `run_records.json` | Immutable audit trail |
| `nmgui_debug.log` | Debug log |

Temp files: VPC PNG/PDF output lives in the VPC folder itself; arrow glyph PNGs for the theme are cached in `$TMPDIR/nmgui2_arrows/`.

Delete `~/.nmgui/` to reset to defaults.

---

## 14. Mapping: Pirana / PopED → NMGUI2

| You are used to (Pirana / PopED) | In NMGUI2 |
|---|---|
| Run overview spreadsheet | **Models tab** |
| Run comparison | Right-click → **Compare with…** or **Open workbench…** |
| Model tree / ancestry | **Tree tab** |
| Execute / bootstrap / VPC buttons | **Run sub-tab** and **VPC tab** |
| Xpose diagnostics from inside Pirana | **Evaluation tab** (native, no R required for GOF/CWRES/QQ/ETA plots) |
| `.lst` reader | **Output sub-tab**, or right-click → **View `.lst`** for raw |
| NONMEM messages | Right-click → **NM-TRAN messages** |
| Bootstrap results viewer | **Uncertainty tab → Bootstrap** |
| SIR results | **Uncertainty tab → SIR** |
| Audit / archival | **Right-click → View run record**, **QC report…** |
| Annotation, star, status | **Info sub-tab → Annotation**, Space to star |
| PopED design-evaluation | **Not in NMGUI2** — NMGUI2 is estimation-focused |

---

*Developed with [Anthropic Claude](https://claude.ai). Comments, bug reports and pull requests welcome at https://github.com/Robterheine/nmgui2.*
