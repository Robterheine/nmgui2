# NMGUI2 v2.9 — User Guide

A complete feature reference for pharmacometricians. Each section states *where* the feature lives and *how* to use it. If you are coming from **Pirana**, see the quick-mapping table at the end.

---

## Contents

1. [Required and optional software](#1-required-and-optional-software)
2. [Orientation — window layout](#2-orientation--window-layout)
3. [Models tab](#3-models-tab)
4. [Files tab](#4-files-tab)
5. [Model detail panel](#5-model-detail-panel-right-hand-pane)
6. [Tree tab](#6-tree-tab--model-lineage)
7. [Evaluation tab](#7-evaluation-tab--gof-and-diagnostics)
8. [VPC tab](#8-vpc-tab)
9. [Uncertainty tab](#9-uncertainty-tab--bootstrap--sir)
10. [Sim Plot tab](#10-sim-plot-tab)
11. [History tab](#11-history-tab)
12. [Settings tab](#12-settings-tab)
13. [Dialogs](#13-dialogs)
14. [Global keyboard shortcuts](#14-global-keyboard-shortcuts)
15. [Files written by NMGUI2](#15-files-written-by-nmgui2)
16. [Mapping: Pirana → NMGUI2](#16-mapping-pirana--nmgui2)

---

## 1. Required and optional software

NMGUI2 is a pure Python/PyQt6 desktop app. It never spawns a browser and never contacts a server (other than an optional GitHub update check). The app launches and can browse, compare and evaluate models even with nothing else installed.

### Required for the core app

| Tool | Minimum | Install |
|---|---|---|
| Python | 3.10 | python.org / brew / apt |
| PyQt6, pyqtgraph, numpy, matplotlib, scipy | — | `pip install -r requirements.txt` |

### Required to *run* NONMEM models from inside NMGUI2

| Tool | Minimum | Notes |
|---|---|---|
| NONMEM | 7.4 | Licensed install from ICON |
| PsN | 5.0 | `execute`, `vpc`, `bootstrap`, `scm`, `sir`, `cdd`, `npc`, `sse` must be on PATH |
| Perl | 5.16 | macOS/Linux: system Perl. Windows: Strawberry Perl |

Paths can be overridden in **Settings** if autodetection fails.

### Required for VPC generation

| Tool | Install |
|---|---|
| R ≥ 4.0 (`Rscript` on PATH) | `brew install r` / `apt install r-base` / cran.r-project.org |
| R package `vpc` | `install.packages("vpc")` |
| R package `xpose` | `install.packages("xpose")` |
| R package `tidyverse` | required by `xpose` |
| R package `ggplot2` | required by `vpc`/`xpose` |

One-liner:
```bash
Rscript -e 'install.packages(c("vpc","xpose","tidyverse","ggplot2"), repos="https://cran.r-project.org")'
```

The VPC tab shows a green ✓ / red ✗ per package at startup.

### Required for Uncertainty tab

PsN `bootstrap` and `sir` commands. Loading *existing* results folders works without PsN.

---

## 2. Orientation — window layout

```
┌─────────────────────────────────────────────────────────────┐
│  NMGUI  v2.9.0           PROJECTDIR / run12   [?About] [RS] │
├─────┬───────────────────────────────────────────────────────┤
│  M  │                                                       │
│  F  │           tab content                                 │
│  T  │                                                       │
│  E  │                                                       │
│  V  │                                                       │
│  U  │                                                       │
│  ~  │                                                       │
│  H  │                                                       │
│  ⚙  │                                                       │
├─────┴───────────────────────────────────────────────────────┤
│  status bar                                                 │
└─────────────────────────────────────────────────────────────┘
```

- **Left sidebar** — nine tabs: Models (M) / Files (F) / Tree (T) / Evaluation (E) / VPC (V) / Uncertainty (U) / Sim Plot (~) / History (H) / Settings (⚙).  
  Keyboard: ⌘1–⌘9 (macOS) / Ctrl+1–Ctrl+9 (Win/Linux).
- **Top bar** — app name, version, current directory / model breadcrumb, About button, Open RStudio button.
- **Status bar** — model count, active directory, last scan time, transient action messages.
- **Theme** — dark / light / follow system, toggled in Settings.

---

## 3. Models tab

**Shortcut:** ⌘1 / Ctrl+1. This is the home view.

### Directory controls (top row)

| Control | Action |
|---|---|
| **Browse…** | Pick a folder; scans for `.mod` / `.ctl` files |
| **⭮ Rescan** (⌘R / Ctrl+R) | Re-scan after external changes |
| **+ Bookmark** / **Bookmarks ▾** | Save / recall directories |
| **All / Completed / Failed** | Status filter buttons |
| **Search box** | Free-text filter on stem, comment, notes, tag |
| **New model…** (⌘N / Ctrl+N) | Create a new NONMEM control file from a template |

### New model

Click **New model…** or press ⌘N / Ctrl+N to open the New Model dialog:

- **Model name** — stem (no extension). Must start with a letter; letters, digits, `_` and `-` allowed. The destination path is shown live below the field.
- **Template** — choose from 26 built-in NONMEM templates (see below).
- **$DATA path** — type or **Browse…** to pick a dataset file. Stored as a relative path when inside the working directory.
- **Preview…** — renders the full control file text before writing.
- **OK** — writes `<stem>.mod`, rescans the directory, and auto-selects the new model with the Editor tab open.

#### Available templates

| Category | Template | Notes |
|---|---|---|
| Analytical | \$PRED subroutine blank | Minimal $PRED scaffold |
| Analytical | 1-CMT oral (ADVAN2 TRANS2) | KA, CL, V with IIV |
| Analytical | 1-CMT IV bolus (ADVAN1 TRANS2) | CL, V with IIV |
| Analytical | 2-CMT oral (ADVAN4 TRANS4) | KA, CL, Q, V2, V3 |
| Analytical | 2-CMT IV bolus (ADVAN3 TRANS4) | CL, Q, V1, V2 |
| Analytical | 3-CMT IV bolus (ADVAN11 TRANS4) | CL, Q2, Q3, V1, V2, V3 |
| Analytical | 3-CMT oral (ADVAN12 TRANS4) | KA, CL, Q3, Q4, V2, V3, V4 |
| ODE — Tier 1 | 1-CMT Michaelis-Menten IV (ADVAN6) | Non-linear (Vmax/Km) elimination |
| ODE — Tier 1 | 1-CMT Michaelis-Menten oral (ADVAN6) | MM elimination + oral absorption |
| ODE — Tier 1 | 2-CMT time-varying CL oral — sigmoid Imax (ADVAN6) | Auto-induction / inhibition |
| ODE — Tier 1 | QE-TMDD 1-CMT IV (ADVAN6) | Quasi-equilibrium TMDD |
| ODE — Tier 1 | Wagner 1-CMT IV — TMDD Rtot constant (ADVAN6) | Simplified TMDD (fixed Rtot) |
| ODE — Tier 1 | Dual first-order absorption 1-CMT (ADVAN6) | Two parallel absorption depots |
| ODE — Tier 1 | Parallel first-order absorption + lag 1-CMT (ADVAN6) | Two depots, lag on one |
| ODE — Tier 1 | Transit compartment absorption 1-CMT (ADVAN6) | N=3 transit CMTs, Savic 2007 |
| ODE — Tier 2 | QE-TMDD 1-CMT oral (ADVAN6) | SC/oral TMDD |
| ODE — Tier 2 | QE-TMDD 2-CMT IV (ADVAN6) | 2-CMT TMDD with peripheral |
| ODE — Tier 2 | Zero-order absorption + MM elimination (ADVAN6) | Extended-release + non-linear |
| ODE — Tier 2 | Simultaneous first+zero order absorption 1-CMT (ADVAN6) | Mixed-release |
| ODE — Tier 2 | 2-CMT IV + urine compartment (ADVAN6) | Dual DVID: plasma + urine |
| PK/PD | Direct Emax PK/PD (ADVAN1) | E = E0 + EMAX·C/(EC50+C); dual DVID |
| PK/PD | Sigmoid Emax PK/PD (ADVAN1) | Hill equation; GAM estimated; dual DVID |
| PK/PD | IDR Type I — inhibit Kin (ADVAN6) | Drug inhibits response production |
| PK/PD | IDR Type II — inhibit Kout (ADVAN6) | Drug inhibits response elimination |
| PK/PD | IDR Type III — stimulate Kin (ADVAN6) | Drug stimulates response production |
| PK/PD | IDR Type IV — stimulate Kout (ADVAN6) | Drug stimulates response elimination |

All ODE templates use `ADVAN6 TOL=6`, TV-parameterisation, combined proportional+additive residual error, and diagonal OMEGA. Dataset notes are embedded as comments where the template requires special columns (RATE, DVID).

**PK/PD templates** require a `DVID` column (1 = PK concentration, 2 = PD response). Two separate EPS terms with the same W-scaling trick are used, one per endpoint. The IDR templates initialise the response compartment at steady state (`A_0(2) = KIN/KOUT`) so that a pre-dose equilibration period is not needed.

### Table columns

| Column | Source | Notes |
|---|---|---|
| ★ | metadata | Star / unstar with Space or right-click |
| Stem | file | e.g. `run12` |
| Status tag | metadata | Base / Candidate / Final / Reject (coloured) |
| OFV | `.lst` / `.ext` | Final objective function value |
| ΔOFV | — | Relative to reference model |
| Min. | `.lst` | ✓ converged, ✗ failed, — not run |
| Cov | `.lst` | Covariance step result |
| Cond# | `.lst` | Condition number |
| Method | `$EST` | FO / FOCE / FOCEI / IMP / SAEM / BAYES / SIM |
| #ID | dataset | Individuals |
| #obs | dataset | Observations |
| #par | `.lst` | Estimated parameters |
| AIC | — | OFV + 2 × #par |
| Runtime | `.lst` | Reported or measured |
| Comment | metadata | Editable in Info panel |

Row colours: **green** = converged, **red** = failed / terminated, **orange** = stale (source newer than `.lst`) or boundary warning.

### Reference model

Right-click → **Set as reference model**. All ΔOFV values recompute against it. Clear via right-click → **Clear reference model**.

### Right-click context menu

| Item | Action |
|---|---|
| **Run** | Run the model with current Run panel settings |
| **Toggle star** | Also Space |
| **Duplicate…** | Clone with incremented run number |
| **Set / Clear reference model** | |
| **Compare with…** | Two-model parameter comparison dialog |
| **Copy .mod path** | Path to clipboard |
| **Copy folder path** | Folder path to clipboard |
| **Open folder** | Open in Finder / Explorer / xdg-open |
| **View .lst** | Raw listing in search-enabled viewer |
| **View .ext** | Parameter estimates by iteration (if run exists) |
| **View run record…** | Immutable audit record |
| **NMTRAN messages…** | NM-TRAN compilation warnings/errors |
| **QC Report…** | PASS/WARN/FAIL HTML checklist (completed models only) |
| **Run Report…** | HTML rendering of Output tab (completed models only) |
| **Workbench…** | Multi-model comparison table |
| **Delete…** | Remove `.mod` + all paired output files (confirms before deleting; excludes dataset) |

### Keyboard (model table)

| Key | Action |
|---|---|
| ↑ / ↓ | Move row |
| Enter | Jump to Output sub-tab |
| Space | Toggle star |

---

## 4. Files tab

**Shortcut:** ⌘2 / Ctrl+2.

A built-in file browser for the current working directory, with a content viewer for all common NONMEM file types.

### Navigation bar (top)

```
[←]  PROJECTDIR  /  run12        [All] [.mod] [.ctl] [.lst] [.tab] [.csv] [.ext] [.cov] [.cor] [.phi] [+]
```

| Element | Action |
|---|---|
| **← back button** | Return to previous directory; disabled at root |
| **Breadcrumb** | Shows current path relative to working directory root |
| **All** pill | Show all files (default) |
| **Extension pills** | Click to show only files with that extension; folders always remain visible regardless of filter |
| **[+] pill** | Add a custom extension filter via a text prompt |

Multiple extension pills can be active simultaneously. Clicking **All** clears all extension selections. Filter state persists across sessions.

### File list

- **Folders appear first** (bold, 📁 prefix), sorted A-Z.
- Files appear below, sorted by name by default; click column headers (Name / Size / Modified) to resort.
- Hidden folders (name starts with `.`) are not shown.

| Interaction | Result |
|---|---|
| Single-click file | Load preview in right pane |
| Single-click folder | Highlight only (no preview) |
| Double-click folder | Navigate into it; breadcrumb and back button update |
| Double-click file | Open with the OS default application (Finder / Explorer / xdg-open) |

### Content viewer (right pane)

**Toolbar** shows the current filename and context-sensitive controls:

| File type | View | Controls |
|---|---|---|
| `.mod`, `.ctl` | Syntax-highlighted text | Find bar, Edit / Save / Discard |
| `.lst`, `.phi`, other text | Monospace text | Find bar, Edit / Save / Discard |
| `.csv` | Spreadsheet (sortable, virtualised — no row cap) | Table / Plot pills, Edit / Save / Discard |
| `.tab` (NONMEM TABLE) | Spreadsheet (sortable, virtualised — no row cap) | Table / Plot pills (read-only) |

**Plot view** (`.csv` / `.tab`) — full Data Explorer:
- Any column on X and Y.
- Colour-by any column (categorical or continuous).
- Multi-filter (AND) — add rows of `column op value`.
- Paginated data table view.

**Edit mode** — toggle with the **Edit** button:
- Text files become editable; **Save** writes back, **Discard** reloads.
- `.csv` cells become editable; saves back with the original delimiter.
- `.tab` files remain read-only (NONMEM output).

**Find bar** (text files only) — highlights all occurrences; jumps to first match.

---

## 5. Model detail panel (right-hand pane)

Visible when a model is selected in the Models tab. Five sub-tabs:

### 5.1 Parameters

Full THETA / OMEGA / SIGMA table. Parameter names parsed from comments in the control stream. Columns: estimate, SE, RSE%, 95% CI, SD (for variance parameters). Handles `BLOCK(n)` and `BLOCK(n) SAME` correctly.

- THETA / OMEGA / SIGMA blocks are **collapsible** — click the section header.
- **Export CSV…** — full table.
- **Export HTML…** — self-contained report for sharing.

### 5.2 Editor

Syntax-highlighted `.mod` editor. **Save** writes the file and marks the model stale (orange row). Never overwrites `.lst`.

### 5.3 Run

Launch any PsN tool on the current model.

- **Tool dropdown** — `execute` / `vpc` / `bootstrap` / `scm` / `sir` / `cdd` / `npc` / `sse`.
- **Extra args** — free-form arguments appended verbatim.
- **Run detached** (Linux/macOS) — launch under `nohup` in a new OS session. The job continues even if NMGUI2 closes or the SSH connection drops. Auto-checked when running over SSH. Output written to `<run_id>.nmgui.log` in the project folder.
- **Run** — opens a floating popup window per model (unchecked), or adds a row to the Active & Recent Runs table (checked).

#### Run popup window

Each run gets its own independent floating window:

- **Status line** — pulsing ● while running; shows live iteration / OFV for `execute` runs; shows N/M progress for multi-run tools. On completion shows ✓/✗ with termination reason.
- **Elapsed timer**.
- **Live console** — stdout/stderr stream.
- **Stop button** — *Gentle (SIGTERM)* or *Force kill (SIGKILL)*.
- **Open run dir** — reveals the run subdirectory in the file manager.

#### Active & Recent Runs table

Shows all runs for the current project folder:
- **Live rows** — click to raise the popup window.
- **Detached rows** — click to open a **Watch Log** window (live tail with elapsed timer and Stop button).
- **Historical rows** — loaded from `nmgui_run_records.json`; persist across restarts.
- **Interrupted** — runs that were active when the app closed appear as "? Interrupted".

#### Detached run reconciliation

On the next NMGUI2 startup or directory rescan, finished detached runs are automatically reconciled — status, timestamps, and OFV are retrieved from the log file. A status bar message reports the outcome.

### 5.4 Info

- **Dataset card** — path, row count, columns, integrity warnings (missing file, non-monotonic TIME, duplicate doses, extreme DV, high BLQ proportion).
- **Annotation card** — status tag (Base / Candidate / Final / Reject) and comment, both visible in the table.
- **Notes card** — free-form multiline notes; persisted in `~/.nmgui/model_meta.json`.

### 5.5 Output

Structured HTML rendering of the `.lst` in-panel:

1. **Summary strip** — stem, OFV, minimisation, covariance, method, runtime.
2. **Estimation steps** (chained `$EST`) — one row per step: OFV, ΔOFV between steps, runtime, significant digits, termination reason.
3. **NM-TRAN warnings**.
4. **Convergence** — iteration history from `.ext`.
5. **Parameter estimates** with SEs.
6. **ETABAR** with p-values.
7. **Shrinkage** (ETA and EPS).
8. **Correlation and covariance matrices**.
9. **Eigenvalues and condition number**.

**Open in browser** — exports full HTML to a temp file and opens it externally.

---

## 6. Tree tab — model lineage

**Shortcut:** ⌘3 / Ctrl+3.

Interactive force-directed node graph of model genealogy. Parent is taken from the PsN metadata line `;; 1. Based on: NNN` or from the manually-set parent in Info → Annotation.

- **Scroll** to zoom, **drag** to pan.
- **Double-click** a node — selects that model in the Models tab.
- **Starred** models: gold border. **Final** models: green border.

---

## 7. Evaluation tab — GOF and diagnostics

**Shortcut:** ⌘4 / Ctrl+4.

Select a model in the Models tab first. NMGUI2 auto-loads the first `sdtab*` table file found next to the `.mod`. Manual override via **Browse…**. **Exclude MDV=1** is on by default.

Four pills across the top switch sections:

### 7.1 GOF

2×2 panel: DV vs PRED | DV vs IPRED | CWRES vs TIME | CWRES vs PRED — with unity / zero reference lines.

Inner pill strip also exposes:
- **CWRES histogram** — with normal density overlay and Save PNG.
- **QQ plot** — CWRES vs theoretical quantiles; Shapiro–Wilk statistic and 95% band; Save PNG.
- **NPDE distribution** — histogram + normal overlay; shown only when the table contains an NPDE column; Save PNG.
- **ETA vs Covariate** — scatter of each ETA against continuous covariates with LOESS overlay. Recognises `ETA`, `ET` and `PHI` column prefixes (including NONMEM-truncated `ET12` etc.).

### 7.2 Individual Fits

Paginated DV / IPRED / PRED vs TIME per subject. Configurable columns per page. Space / arrow keys page through.

### 7.3 OFV Waterfall

Ranked ΔOFV bar chart across all completed models in the current directory. Useful at the end of a model-building sequence.

### 7.4 Convergence

Parameter trajectories from the `.ext` file for the selected model — one trace per estimated parameter.

---

## 8. VPC tab

**Shortcut:** ⌘5 / Ctrl+5.

### 8.1 Backends

Two R backends:
- **vpc** — Ronny Keizer's package; binned PI / CI bands.
- **xpose** — tidyverse-based rendering.

Availability shown as ✓ / ✗ per package at the top of the panel.

### 8.2 Inputs

| Field | Purpose |
|---|---|
| VPC folder | PsN `vpc` output directory (contains `m1/`, `vpc_results.csv`) |
| Run directory | For xpose backend; contains sdtab, `.ext`, `.phi` |
| **Use PsN settings** (default on) | Inherits binning, stratification, pred-corr, LLOQ from PsN output; override individual fields by unchecking |
| Stratify | Column name; validated against header before running; warns if > 20 levels |
| PI (low / high) | Prediction interval percentiles |
| CI (low / high) | Confidence interval percentiles |
| LLOQ | Lower limit of quantification |
| Bins | Bin count (when overriding PsN) |
| Log Y axis | Toggle |
| Prediction-corrected (pcVPC) | Toggle |

### 8.3 Run flow

1. Click **Generate VPC**. A script is generated and run via `Rscript`.
2. Console streams stdout/stderr live.
3. On success, the PNG is displayed inline.
4. **Save high-res PNG…** — re-runs at 4× resolution.
5. **Save PDF…** — re-runs with a `pdf()` device (vector output).
6. **Stop** — terminates the R process.

### 8.4 R script

Toggle the **R Script** view to edit the generated script before running — add custom ggplot themes, colours, or annotations. **Reset** restores the template.

---

## 9. Uncertainty tab — Bootstrap & SIR

**Shortcut:** ⌘6 / Ctrl+6.

Two sub-sections: **Bootstrap** / **SIR** (switched by the top pill).

### 9.1 Bootstrap

1. Select a model in the Models tab (carried over).
2. **Run bootstrap** (spawns PsN `bootstrap`) or **Load results folder…** (existing `raw_results_*.csv`).
3. Pre-run options: Samples, Threads, Stratify by.

Outputs:
- **Parameter table** — original estimate, bootstrap median, bias%, 2.5–97.5 percentile CI.
- **Forest plot** — normalised distributions.
- **Diagnostics**: completion rate, bias, parameter correlations, CI validity, boundary proximity.
- **Overall assessment** — PASSED / ACCEPTABLE / WARNING / FAILED.

### 9.2 SIR

Same layout. Uses PsN `sir`. Outputs:
- Effective sample size (ESS) and resampling efficiency.
- Degeneracy detection.
- Weighted percentile CIs.
- Overall assessment with one-line interpretation.

### 9.3 Console

Live PsN output streamed to the console at the bottom. **Reset** clears.

---

## 10. Sim Plot tab

**Shortcut:** ⌘7 / Ctrl+7.

Plots prediction intervals from NONMEM Monte Carlo simulation output. Requires a NONMEM table file that contains a replicate column (REP, IREP, SIM, SIMNO, SIM_NUM, etc. — auto-detected).

### 10.1 Data card

- **Browse / Load** — pick any NONMEM table file or CSV (no row-count cap).
- **X column** and **Y column** selectors.
- **Replicate column** — auto-detected or manually selected.
- **Observed data** — optionally load a second file to overlay observed DV points.

### 10.2 Filters card (expanded by default)

Up to 6 independent column filters (`==`, `!=`, `>`, `<`, `>=`, `<=`), ANDed together. Use to subset by compartment, dose group, sex, or any other column. **Exclude MDV=1** checkbox in this card.

### 10.3 PI Bands card

Up to 4 simultaneous prediction interval ribbons, each configured on a single-line card:

| Control | Purpose |
|---|---|
| Visibility checkbox | Show / hide the band |
| Lo% / Hi% spinboxes | Percentile pair (e.g. 5 / 95) |
| Colour swatch | Click to open colour picker |
| Alpha spinbox | Transparency (0–1) |
| Remove (×) button | Delete this band |

**Add band** — adds a new row. **Preset** dropdown restores a named set (4 presets cover common pharmacometric conventions).

### 10.4 Appearance card

- **Median line** — colour and line width; computed as the 50th percentile across replicates.
- **Log Y axis** — toggle for concentration-time plots.
- **LOESS smoothing** — smooth all PI boundaries and the median line; **Span** spinbox controls bandwidth (0.05–1.0, default 0.30).

### 10.5 Generate / Save

- **Generate** — runs quantile calculations in a background thread; UI stays responsive.
- **Save PNG** — 300 DPI PNG via matplotlib.

---

## 11. History tab

**Shortcut:** ⌘8 / Ctrl+8.

Chronological log of every PsN run started from NMGUI2 (last 200 entries, global across all projects).

| Column | Meaning |
|---|---|
| Status | Running / Completed / Failed |
| Stem | Model |
| Tool | `execute` / `vpc` / `bootstrap` / … |
| Command | Full command line |
| Started / Duration | Timestamps |

Double-click any row to open the full **Run Record** dialog.

---

## 12. Settings tab

**Shortcut:** ⌘9 / Ctrl+9. All settings persist in `~/.nmgui/settings.json`.

- **Theme** — Dark / Light / Follow system.
- **Font size** — base font point size.
- **Paths** — manual overrides for PsN `execute`, NONMEM binary, R `Rscript`, RStudio.
- **Directory bookmarks** — add / remove / reorder.
- **GitHub update check** — optional; pings `/releases/latest` once per launch; compares versions numerically.
- **Debug logging** — verbose output to `~/.nmgui/nmgui_debug.log`.
- **Open `.nmgui/` folder** — reveals the config directory in the file manager.

---

## 13. Dialogs

### 13.1 New Model

Opens from **New model…** button or ⌘N / Ctrl+N in the Models tab. See §3 for full description.

### 13.2 Compare

Right-click → **Compare with…**, pick a second model. Side-by-side parameter table with ΔOFV, ΔAIC, ΔBIC, Δ#par, LRT p-value (sign-aware), and a verdict string. Export CSV / HTML.

### 13.3 Workbench

Right-click → **Workbench…** or toolbar button. Sortable table of all completed models: OFV, ΔOFV, AIC, BIC, #par, LRT p-value, minimisation, covariance. Choose the reference from a dropdown. **Export CSV**.

### 13.4 QC Report

Right-click → **QC Report…** (completed models only). Self-contained HTML with PASS / WARN / FAIL checklist: termination, covariance, condition number, max %RSE, parameter correlations (|r| ≥ 0.95), shrinkage, ETABAR, OMEGA near boundary.

### 13.5 Duplicate

Right-click → **Duplicate…**. Clones `.mod` with an incremented run number; optionally copies dataset reference.

### 13.6 LST viewer

Right-click → **View .lst**. Raw listing in a monospaced, search-enabled viewer window.

### 13.7 NM-TRAN messages

Right-click → **NMTRAN messages…**. Parsed compilation warnings and errors — useful for catching `WARNING: DES COMPARTMENT NOT USED` and similar.

### 13.8 Run record

Right-click → **View run record…**. Immutable audit record per run:
- Run UUID.
- SHA-256 hash of the control stream and dataset.
- NONMEM / PsN / NMGUI versions.
- Start/end timestamps and duration.
- Final OFV, minimisation status, covariance status.
- Full command line.
- **Export JSON** for archival.

### 13.9 About

App version, Python / PyQt6 / numpy versions, environment summary, credits.

### 13.10 Keyboard shortcuts reference

A floating card of all shortcuts, accessible from the About dialog.

---

## 14. Global keyboard shortcuts

| Action | macOS | Win / Linux |
|---|---|---|
| Models tab | ⌘1 | Ctrl+1 |
| Files tab | ⌘2 | Ctrl+2 |
| Tree tab | ⌘3 | Ctrl+3 |
| Evaluation tab | ⌘4 | Ctrl+4 |
| VPC tab | ⌘5 | Ctrl+5 |
| Uncertainty tab | ⌘6 | Ctrl+6 |
| Sim Plot tab | ⌘7 | Ctrl+7 |
| History tab | ⌘8 | Ctrl+8 |
| Settings tab | ⌘9 | Ctrl+9 |
| Open directory | ⌘O | Ctrl+O |
| Rescan directory | ⌘R | Ctrl+R |
| New model | ⌘N | Ctrl+N |
| Navigate model table | ↑ / ↓ | ↑ / ↓ |
| Jump to Output panel | Enter | Enter |
| Toggle star | Space | Space |

---

## 15. Files written by NMGUI2

Global state — `~/.nmgui/` (created on first launch):

| File | Contents |
|---|---|
| `settings.json` | Theme, paths, window geometry, splitter sizes |
| `model_meta.json` | Stars, status tags, comments, notes, parent overrides |
| `bookmarks.json` | Directory bookmarks |
| `runs.json` | Global run history (last 200 entries across all projects) |
| `nmgui_debug.log` | Debug log |

Per-project files — written inside each project folder:

| File | Contents |
|---|---|
| `nmgui_run_records.json` | Immutable run audit trail (last 500 entries); drives the Active & Recent Runs table |
| `<run_id>.nmgui.log` | stdout/stderr of a detached run; tailed by the Watch Log window |
| `<run_id>.nmgui.pid` | PID and metadata of a running detached job; removed on completion |

Delete `~/.nmgui/` to reset global settings. Per-project run records are not affected.

---

## 16. Mapping: Pirana → NMGUI2

| Pirana feature | NMGUI2 equivalent |
|---|---|
| Run overview spreadsheet | **Models tab** |
| Run comparison / ΔOFV | Right-click → **Compare with…** or **Workbench…** |
| Model tree / ancestry | **Tree tab** (⌘3) |
| Execute / bootstrap / VPC buttons | **Run sub-tab** and **VPC tab** |
| Xpose diagnostic plots | **Evaluation tab** — native, no R required for GOF / CWRES / QQ / ETA plots |
| `.lst` reader | **Output sub-tab**, or right-click → **View .lst** for raw |
| NONMEM messages | Right-click → **NMTRAN messages…** |
| Bootstrap results | **Uncertainty tab → Bootstrap** |
| SIR results | **Uncertainty tab → SIR** |
| Audit / archival | Right-click → **View run record…** and **QC Report…** |
| Annotation, star, status tag | **Info sub-tab → Annotation**, Space to star |
| File browser | **Files tab** (⌘2) — with subfolder navigation and content preview |
| Simulation plot / PI ribbons | **Sim Plot tab** (⌘7) |
| Create new model file | **New model…** button / ⌘N — 26 built-in templates |
| SSH / nohup workflow | **Run detached** checkbox in the Run sub-tab |

---

*NMGUI2 v2.9 · Developed with [Anthropic Claude](https://claude.ai) · [GitHub](https://github.com/Robterheine/nmgui2)*
