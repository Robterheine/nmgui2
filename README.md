# NMGUI2

**A standalone desktop application for NONMEM pharmacometric modelling workflows**

NMGUI2 is a PyQt6 desktop application that brings together everything a pharmacometrician needs in one window: browse and compare NONMEM models, evaluate goodness-of-fit, run PsN tools, analyse bootstrap and SIR results, visualise model lineage, and read `.lst` output — without switching between terminals, text editors and R.

It runs entirely offline on macOS, Windows and Linux. No browser. No server. No internet connection required during use.

<p align="center">
  <img src="screenshots/screenshotmain.png" alt="NMGUI2 Models tab" width="900">
</p>

<p align="center">
  <img src="screenshots/screenshotgof.png"     alt="Goodness-of-fit diagnostics" width="440">
  <img src="screenshots/screenshotvpc.png"     alt="Visual predictive check"     width="440">
</p>
<p align="center">
  <img src="screenshots/screenshotsimplot.png" alt="Simulation plot"             width="440">
  <img src="screenshots/screenshotsir.png"     alt="SIR uncertainty diagnostics" width="440">
</p>

---

## Table of contents

- [Features](#features)
- [User guide](USER_GUIDE.md) — full reference for every tab, dialog, and required R/PsN package
- [Dependencies overview](#dependencies-overview)
- [Quick start](#quick-start)
- [Installation — macOS](#installation--macos)
- [Installation — Windows](#installation--windows)
- [Installation — Linux](#installation--linux)
- [First use](#first-use)
- [Updating NMGUI2](#updating-nmgui2)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Configuration files](#configuration-files)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [Author](#author)
- [Acknowledgements](#acknowledgements)
- [License](#license)
- [Changelog](#changelog)

---

## Features

### Models tab
- Scans a directory for `.mod` / `.ctl` files and displays all models in a sortable, filterable table
- Columns: OFV, ΔOFV (relative to user-selected reference), minimisation status, covariance step, condition number, estimation method, individuals, observations, parameters, AIC, runtime
- Colour-coded rows: green = converged, red = failed/terminated, orange = stale or boundary warning
- Filter buttons: All, Completed, Failed — plus free-text search
- **New model…** (Ctrl+N / ⌘N) — create a blank NONMEM control file from one of 17 built-in templates (analytical ADVAN1/2/3/4 and ODE-based ADVAN6 including Michaelis-Menten, QE-TMDD, time-varying CL, dual/mixed absorption, urine compartment); preview before writing; auto-selects the new file after creation
- **Right-click context menu**: run, toggle star, duplicate, set/clear reference, compare, copy paths, open folder, view `.lst`, view `.ext`, QC report, run report, view run record, NM-TRAN messages, workbench, delete
- Keyboard: ↑↓ move rows, Space toggles star, Enter jumps to Output

### Model detail panel

**Parameters** — full THETA/OMEGA/SIGMA table with names (parsed from control stream comments), estimates, SE, RSE%, 95% CI, SD for variance parameters. Handles `BLOCK(n)` and `BLOCK(n) SAME`. Export to CSV and HTML.

**Editor** — syntax-highlighted `.mod` editor with save functionality.

**Run** — launch any PsN tool (`execute`, `vpc`, `bootstrap`, `scm`, `sir`, `cdd`, `npc`, `sse`). Each run opens its own floating popup with a live console, iteration/OFV progress, elapsed timer, and Stop button (SIGTERM or SIGKILL). Multiple models run simultaneously. **Run detached** (Linux/macOS) launches under `nohup` so the job survives SSH disconnection or app closure — auto-checked when running over SSH. The **Active & Recent Runs** table shows live, detached, and historical runs; history persists per project across restarts.

**Info** — status tag (base/candidate/final/reject), comment, free-form notes, and a dataset integrity card (missing file, non-monotonic TIME, duplicate doses, extreme DV, high BLQ).

**Output** — structured HTML rendering of the `.lst` in-panel: summary card, estimation steps table (per-step OFV/ΔOFV/runtime for chained `$EST`), NM-TRAN warnings, convergence table, parameter estimates with SEs, ETABAR p-values, shrinkage, correlation/covariance matrices, eigenvalues, condition number. "Open in browser" exports full HTML.

### Files tab (Ctrl+2)
A built-in file browser with subfolder navigation and a content viewer — no external app needed.

- **Navigation bar** — ← back button, breadcrumb path, and extension filter pills (All · .mod · .ctl · .lst · .tab · .csv · .ext · .cov · .cor · .phi · [+]). All files shown by default; selecting pills filters files while keeping folders always visible.
- **File list** — folders appear first (bold, 📁 prefix); files below. Sortable by name, size, or date.
- **Double-click folder** → navigate into it; breadcrumb and back button update.
- **Double-click file** → open with the OS default application.
- **Content viewer** — syntax-highlighted text for `.mod`/`.ctl`; inline find bar; virtualised spreadsheet view for `.csv`/`.tab` (no row cap); **Table / Plot** toggle showing the full Data Explorer (scatter, LOESS, colour-by, filters); Edit / Save / Discard for text and CSV files.

### Tree tab (Ctrl+3)
Interactive force-directed node graph of model lineage based on PsN metadata or manually set parent. Zoom, pan, double-click any node to jump to that model. Gold border = starred; green border = final.

### Evaluation tab (Ctrl+4)
Native diagnostic plots — no R required:

- **GOF 2×2** — DV vs PRED, DV vs IPRED, CWRES vs TIME, CWRES vs PRED with reference lines
- **CWRES histogram** — normal overlay, Save PNG
- **QQ plot** — with Shapiro-Wilk test and 95% confidence band, Save PNG
- **NPDE distribution** — shown when NPDE column is present, Save PNG
- **ETA vs covariate** — scatter with LOESS overlay; recognises truncated NONMEM ETA column names (ET12, ET13 …)
- **Individual fits** — paginated DV/IPRED/PRED vs TIME per subject
- **OFV waterfall** — ranked ΔOFV across all completed models
- **Convergence traces** — parameter trajectories from `.ext`

Auto-loads `sdtab` on model selection.

### VPC tab (Ctrl+5)
Generate Visual Predictive Checks via R:
- **vpc** (Ronny Keizer) and **xpose** (tidyverse) backends — availability shown with ✓/✗ at startup
- "Use PsN settings" mode inherits binning, stratification and pred-corr from the PsN output folder
- Configurable PI/CI percentiles, LLOQ, bins, log Y, pcVPC
- Editable R script — modify before running
- Live console, inline PNG preview, Save high-res PNG, Save PDF

### Uncertainty tab (Ctrl+6)
**Bootstrap** — run via PsN or load existing results; parameter table with 95% CI from percentiles, forest plot, diagnostic checks (completion rate, bias, correlations, CI validity, boundary proximity), overall PASSED/ACCEPTABLE/WARNING/FAILED verdict.

**SIR** — same layout; ESS, resampling efficiency, degeneracy detection, weighted percentile CIs, overall assessment.

### Sim Plot tab (Ctrl+7)
Prediction interval visualisation from NONMEM Monte Carlo simulation output:
- Load any NONMEM table file or CSV — no row cap
- Auto-detects replicate column (REP, IREP, SIM, SIMNO, …)
- Up to 4 configurable PI band ribbons (percentile pair, colour, alpha, visibility), 4 presets
- Median line, log/linear Y axis, LOESS smoothing
- Up to 6 column filters (AND), MDV=1 exclusion
- Optional observed data overlay
- Background quantile computation — UI stays responsive
- Save 300 DPI PNG

### History tab (Ctrl+8)
Chronological log of all PsN runs (last 200 entries). Columns: status, model, tool, command, timestamps. Double-click any row to view the full run record.

### Run Records (audit trail)
Every run creates an immutable record: UUID, SHA-256 hashes of control stream and dataset, NONMEM/PsN/NMGUI versions, timestamps, OFV, minimisation/covariance status, full command. Accessible from right-click → "View run record". Export JSON.

### Settings tab (Ctrl+9)
- Dark / light / follow-system theme toggle
- Path configuration for NONMEM, PsN, R, RStudio
- Directory bookmarks management
- GitHub update check (numeric version comparison)
- Debug logging to `~/.nmgui/nmgui_debug.log`

### Additional features
- **Model comparison** — side-by-side parameter table with ΔOFV, ΔAIC, ΔBIC, LRT p-value
- **Model workbench** — sortable table of all completed models for quick multi-model review
- **QC report** — PASS/WARN/FAIL HTML checklist per model
- **Duplicate model** — copy with incremented run number
- **NM-TRAN messages** — compilation warnings/errors at a glance
- **Stale detection** — orange highlight when `.mod` or data file is newer than `.lst`
- **GitHub update check** — optional notification on new version
- **Cross-platform** — macOS, Windows, Linux (including X11/MobaXterm over SSH)

---

## Dependencies overview

### Python packages

All Python dependencies are listed in `requirements.txt` and installed automatically:

| Package | Purpose |
|---|---|
| PyQt6 | GUI framework |
| pyqtgraph | Interactive plots |
| numpy | Numerical operations |
| matplotlib | CWRES histogram, QQ plot |
| scipy | Shapiro-Wilk test, confidence bands (optional but recommended) |

### External tools for running models

| Dependency | Minimum version | Notes |
|---|---|---|
| NONMEM | 7.4 | Must be installed and licensed |
| PsN (Perl-speaks-NONMEM) | 5.0 | Must be on system PATH |
| Perl | 5.16 | Required by PsN |

### External tools for VPC generation

| Dependency | Notes |
|---|---|
| R ≥ 4.0 | Must be on system PATH (`Rscript` command must work) |
| RStudio | Optional but recommended |
| R package: vpc | `install.packages("vpc")` |
| R package: xpose | `install.packages("xpose")` |
| R package: tidyverse | `install.packages("tidyverse")` — required by xpose |
| R package: ggplot2 | `install.packages("ggplot2")` — required by vpc/xpose |

> NMGUI2 (browsing, evaluating, comparing results) works without NONMEM, PsN, R or RStudio. These are only needed if you want to run models or generate VPCs from within the app.

---

## Quick start

If you already have Python 3.10+, Git, and optionally R/PsN installed:

```bash
git clone https://github.com/robterheine/nmgui2.git
cd nmgui2
pip install -r requirements.txt
python3 nmgui2.py
```

For full installation instructions including NONMEM, PsN, and R, see the platform-specific sections below.

---

## Installation — macOS

### 1. Install Xcode Command Line Tools

```bash
xcode-select --install
```

### 2. Install Homebrew (if not already installed)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 3. Install Python 3

```bash
brew install python
python3 --version
```

### 4. Install R (required for VPC only)

```bash
brew install r
```

Or download from https://cran.r-project.org/bin/macosx/

Verify:
```bash
Rscript --version
```

### 5. Install RStudio (optional)

Download from https://posit.co/download/rstudio-desktop/ and add to `/Applications`.

### 6. Install required R packages

```bash
Rscript -e 'install.packages(c("vpc","xpose","tidyverse","ggplot2"), repos="https://cran.r-project.org")'
```

### 7. Install Perl (required by PsN — usually pre-installed on macOS)

```bash
perl --version
```

If missing:
```bash
brew install perl
```

### 8. Install PsN

Follow the official guide at https://uupharmacometrics.github.io/PsN/install.html

Verify:
```bash
execute --version
```

### 9. Clone and install NMGUI2

```bash
git clone https://github.com/robterheine/nmgui2.git
cd nmgui2
pip3 install -r requirements.txt
```

### 10. Run NMGUI2

```bash
python3 nmgui2.py
```

### Optional: desktop launcher

Create `~/Desktop/NMGUI2.command`:

```bash
#!/bin/bash
cd /path/to/nmgui2
python3 nmgui2.py
```

Make it executable:
```bash
chmod +x ~/Desktop/NMGUI2.command
```

Double-click in Finder to launch.

---

## Installation — Windows

### 1. Install Python 3.10 or newer

Download from https://www.python.org/downloads/windows/

**During installation, tick:**
- ✅ Add Python to PATH
- ✅ Install pip

Verify in Command Prompt:
```cmd
python --version
pip --version
```

### 2. Install R (required for VPC only)

Download from https://cran.r-project.org/bin/windows/base/

During installation, tick **"Add R to system PATH"** (or add manually: `C:\Program Files\R\R-4.x.x\bin` to PATH).

Verify:
```cmd
Rscript --version
```

### 3. Install RStudio (optional)

Download from https://posit.co/download/rstudio-desktop/

### 4. Install required R packages

Open Command Prompt or RStudio and run:

```cmd
Rscript -e "install.packages(c('vpc','xpose','tidyverse','ggplot2'), repos='https://cran.r-project.org')"
```

### 5. Install Perl (required by PsN)

Download Strawberry Perl from https://strawberryperl.com/ — this includes all required modules.

Verify:
```cmd
perl --version
```

### 6. Install PsN

Follow the official guide at https://uupharmacometrics.github.io/PsN/install.html

Verify:
```cmd
execute --version
```

### 7. Install Git

Download from https://git-scm.com/download/win

### 8. Clone and install NMGUI2

Open Command Prompt:

```cmd
git clone https://github.com/robterheine/nmgui2.git
cd nmgui2
pip install -r requirements.txt
```

### 9. Run NMGUI2

```cmd
python nmgui2.py
```

### Optional: desktop launcher

Create `NMGUI2.bat` in the nmgui2 folder:

```bat
@echo off
cd /d %~dp0
python nmgui2.py
```

Double-click to launch.

---

## Installation — Linux

Shown for Ubuntu/Debian. For Fedora replace `apt` with `dnf`; for Arch replace with `pacman`.

### 1. Install system dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git curl perl
python3 --version
```

### 2. Install Qt system libraries (required by PyQt6)

```bash
sudo apt install -y libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0 \
    libgl1-mesa-glx libegl1
```

### 3. Install R (required for VPC only)

```bash
sudo apt install -y r-base r-base-dev
```

For the latest R version, follow https://cran.r-project.org/bin/linux/ubuntu/

Verify:
```bash
Rscript --version
```

### 4. Install RStudio (optional)

Download the `.deb` installer from https://posit.co/download/rstudio-desktop/

```bash
sudo dpkg -i rstudio-*.deb
sudo apt --fix-broken install
```

### 5. Install required R packages

```bash
Rscript -e 'install.packages(c("vpc","xpose","tidyverse","ggplot2"), repos="https://cran.r-project.org")'
```

### 6. Install PsN

Follow the official guide at https://uupharmacometrics.github.io/PsN/install.html

Verify:
```bash
execute --version
```

### 7. Clone and install NMGUI2

```bash
git clone https://github.com/robterheine/nmgui2.git
cd nmgui2
pip3 install -r requirements.txt
```

Or with a virtual environment (recommended on systems with externally-managed Python):

```bash
git clone https://github.com/robterheine/nmgui2.git
cd nmgui2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 8. Run NMGUI2

```bash
python3 nmgui2.py
```

Or if using a virtual environment:

```bash
source venv/bin/activate
python3 nmgui2.py
```

### Optional: desktop launcher

Create `~/.local/share/applications/nmgui2.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=NMGUI2
Exec=/bin/bash -c "cd /path/to/nmgui2 && python3 nmgui2.py"
Terminal=false
Categories=Science;
```

---

## Updating NMGUI2

On all platforms, from the nmgui2 directory:

```bash
git pull
pip install -r requirements.txt
```

The second command ensures any new dependencies are installed. If no new packages were added, it completes instantly.

If using a virtual environment on Linux:

```bash
source venv/bin/activate
git pull
pip install -r requirements.txt
```

### Previous versions

All tagged releases from v2.5.0 onward are available on the [Releases page](https://github.com/Robterheine/nmgui2/releases). To run an older version, check out the tag into a separate directory:

```bash
git clone https://github.com/robterheine/nmgui2.git nmgui2-old
cd nmgui2-old
git checkout v2.8.0
pip install -r requirements.txt
python3 nmgui2.py
```

---

## First use

1. Launch the app (`python3 nmgui2.py`)
2. Click **Browse…** or use ⌘O / Ctrl+O and navigate to a folder containing `.mod` files
3. Click **+ Bookmark** to save the directory for quick access
4. Select a model row to view its parameters, output, and diagnostic plots
5. Go to **Settings** (⌘9 / Ctrl+9) to configure paths if PsN/NONMEM/RStudio are not auto-detected

---

## Keyboard shortcuts

| Action | macOS | Windows / Linux |
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

## Configuration files

All settings are stored in `~/.nmgui/` (created automatically on first run):

| File | Contents |
|---|---|
| `settings.json` | Theme, paths, window geometry, splitter sizes |
| `model_meta.json` | Stars, comments, status tags, notes, parent model |
| `bookmarks.json` | Directory bookmarks |
| `runs.json` | Run history (last 200 entries) |
| `nmgui_debug.log` | Debug log for troubleshooting |

These files are written **inside each project folder** (not in `~/.nmgui/`):

| File | Contents |
|---|---|
| `nmgui_run_records.json` | Immutable audit trail of runs for that project (last 500 entries), used by the Active & Recent Runs table |
| `<run_id>.nmgui.log` | stdout/stderr of a detached run; tailed by the Watch Log window |
| `<run_id>.nmgui.pid` | PID and metadata of a running detached job; removed automatically on completion |

To reset all settings: delete the `~/.nmgui/` folder. Run records in individual project folders are not affected.

---

## Troubleshooting

**App fails to launch — `ModuleNotFoundError: No module named 'PyQt6'`**
Dependencies did not install. Rerun `pip install -r requirements.txt` (or `pip3` on macOS/Linux). If you see "externally-managed environment" on Linux/macOS, use a virtual environment (see the Linux section).

**App launches but window is blank or scrollbars are native-grey**
Your Qt style is overriding the stylesheet. NMGUI2 forces Fusion at startup; if you see this, confirm you are on v2.5.0 (`git pull && pip install -r requirements.txt`).

**"R: vpc ✗ xpose ✗" in the VPC tab**
`Rscript` is not on PATH or the R packages are not installed. Verify `Rscript --version` in a shell, then install packages with
```bash
Rscript -e 'install.packages(c("vpc","xpose","tidyverse","ggplot2"), repos="https://cran.r-project.org")'
```

**`execute --version` not found**
PsN is not on PATH. On Linux/macOS, add the PsN `bin` directory to your shell profile (`~/.zshrc`, `~/.bashrc`). On Windows, add it to the system PATH via *Environment Variables*.

**NM-TRAN messages show "parser.py not available"**
Your `nmgui2` repository is outdated. Run `git pull`.

**Models tab shows models but OFV column is empty**
The `.lst` file is missing or incomplete — the run never finished or was deleted. Check the model's run directory.

**Dark mode colours look wrong after toggling theme**
Fixed in v2.5.0. If you still see stale colours, restart the app.

**Everything else** — enable debug logging and share `~/.nmgui/nmgui_debug.log` when filing an issue.

---

## Contributing

Contributions are very welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

Areas particularly in need of help:
- Windows and Linux testing and bug reports
- Additional NONMEM output parsing (BAYES, mixture models)
- New diagnostic plot types
- Documentation and tutorials
- Translations

---

## Author

**Rob ter Heine**
Hospital pharmacist – clinical pharmacologist
[Radboud Applied Pharmacometrics](https://www.radboudumc.nl/en/research/research-groups/radboud-applied-pharmacometrics) · Radboudumc, Nijmegen, the Netherlands

---

## Acknowledgements

Developed with [Anthropic Claude](https://claude.ai).

---

## License

[MIT License](LICENSE) — free to use, modify and distribute.

---

## Changelog

### v2.9.9 — Individual fit plots: legend and observation count

**Improvements**
- **Shared legend bar**: A 22 px legend bar now appears below the toolbar on the individual fit plot, identifying the three series: blue filled circles (DV — Observed), solid line (IPRED — Individual prediction), and red dashed line (PRED — Population prediction). The legend carries a tooltip explaining the diagnostic meaning of each comparison, including the ETA shrinkage warning (DV ≈ PRED ≠ IPRED).
- **Observation count in subplot titles**: Each subplot now shows `ID 101  (n=12)` — the number of informative observations plotted — so subjects with very sparse data (n=2–3) are immediately obvious without counting dots.
- The legend repaints correctly when switching between dark and light themes.

### v2.9.8 — iOFV waterfall: normalised mode and chi-squared threshold

**New features**
- **Normalised iOFV view**: The waterfall plot now offers an **Absolute / Normalised** toggle. Normalised mode divides each subject's iOFV by their number of informative observations (EVID=0, MDV=0), making subjects with very rich or very sparse sampling directly comparable.
- **Chi-squared outlier threshold**: The previous mean+2 SD horizontal line has been replaced by a statistically sound χ²(df=n_obs, α=0.001) threshold. In Absolute mode this renders as a per-subject step function; in Normalised mode as a smooth decreasing curve (because variance of χ²(k)/k = 2/k, so sparse subjects have a higher per-unit threshold).
- **Amber highlighting for sparse subjects**: Subjects with fewer than 5 observations are highlighted in amber — the chi-squared approximation is unreliable at that sample size.
- **Info bar**: A one-line explanation beneath the toolbar reads *"iOFV scales with the number of observations per subject · Absolute: raw iOFV with subject-specific χ² threshold · Normalised: iOFV / n_obs corrects for unequal sampling richness"*, so the reason two options exist is always visible.
- **Rich tooltips**: Each toggle button carries a detailed tooltip explaining when to use it and how the threshold is computed.
- **Colour legend**: A legend bar at the bottom of the plot identifies normal (blue–purple gradient), outlier (red), sparse (amber), and no-data (grey) bars.

**How it works**
- Observation counts are read from the dataset file specified in `$DATA` in the background using a `QThread` worker. Rows with EVID≠0 or MDV=1 are excluded.
- If `scipy` is not available the plot falls back to a mean+2 SD threshold with a visible warning.

### v2.9.7 — Code quality and stability audit

**Reliability fixes**
- **Run popup no longer freezes the UI on launch**: NONMEM and PsN version detection
  (`_detect_nonmem_version`, `_detect_psn_version`) was called synchronously on the main
  thread, blocking the GUI for up to 10 s when PsN was not on `$PATH`. Detection now runs
  in a background thread and patches the run record after the popup opens.
- **No more crash after closing the main window while a background check is in progress**:
  The R-availability check and version-update check post their results back to the UI via
  `QTimer.singleShot`. If the window is already closed when the callback fires, the call
  previously raised `RuntimeError: wrapped C++ object deleted`. Both callbacks are now
  guarded with `try/except RuntimeError`.
- **VPC Stop button now actually kills the Rscript process**: Clicking Stop terminated the
  Python `QThread` wrapper but left the Rscript subprocess running (it was started with
  `start_new_session=True` in its own process group). A new `stop_subprocess()` method on
  `VPCWorker` explicitly kills the child process. The same fix is applied to export workers
  (PNG/PDF). An export in progress now also correctly blocks a new VPC run from starting.
- **Stale scan-error callbacks no longer accumulate**: When a directory scan was cancelled
  and immediately replaced by a new scan, the `error` signal of the old worker was not
  disconnected. Each rapid rescan leaked one error handler that could fire misleading status
  messages. The `error` signal is now disconnected alongside `result`.
- **Parameter CSV export status message no longer silently fails**: `ParameterTable` used a
  fragile `parent().parent()` widget-tree walk to emit a status-bar message after CSV
  export. It now emits its own `export_done` signal, connected at the callsite in `models.py`.

**Code quality**
- Bootstrap / SIR sample, resample, and thread spinboxes in the Uncertainty tab changed from
  `QDoubleSpinBox(decimals=0)` to `QSpinBox` — avoids showing a spurious decimal point on
  some platforms and removes unnecessary `int()` casts in the command builder.
- Per-model parse errors in `ScanWorker` are now logged at `WARNING` level instead of being
  silently swallowed, so problems with individual `.mod` files appear in diagnostic output.

### v2.9.6 — VPC coverage hardening

**Bug fix (critical)**
- **xpose VPC failed with "Model file run3.lst not found"** when the model that generated the
  VPC had been renamed or moved. The xpose backend now auto-detects the correct `.lst` file
  from `command.txt` in the vpc folder (`xpose_data(file=…)` instead of `xpose_data(runno=…, dir=…)`).
  A new *Model .lst* field in the xpose settings allows manual override when auto-detection fails.

**VPC correctness fixes (previously silent failures)**
- **pcVPCs now plot correctly** when PsN was run with `-predcorr`: `pred_corr=TRUE` is
  auto-injected into `vpc::vpc()` and `xpose::vpc_opt()` from `meta.yaml`.
- **Stratified VPCs now work with "Use PsN settings"**: `stratify_on` from `meta.yaml` is
  forwarded as `stratify=` (vpc package) or `stratify_on=` (xpose).
- **Categorical and TTE VPCs**: NMGUI2 now detects `-categorical` and `-tte` in `meta.yaml`
  and shows a clear error instead of silently producing a wrong continuous-style plot.
- **vpc package v1.x compatibility**: the vpc() return value is unwrapped from `$plot` when
  needed, preventing `ggsave()` failures on vpc ≥ 1.0.
- **Non-default DV column** (`-dv=LNDV` etc.) now forwarded to `obs_cols`/`sim_cols`.
- **Log-scale VPCs**: `-lnDV=1` is detected from `meta.yaml` and the Log Y axis is
  auto-enabled.

**Robustness**
- Multiple simulation directories (`m2.zip`, `m3.zip`, …) from PsN `-n_simulation_models > 1`
  are now all extracted before the R script runs.
- `command.txt` fallback now handles both `=` and space-separated PsN arguments (`-idv TAD`).
- `meta.yaml` parser fixed for values containing colons (e.g., `stratify_on: DOSE:BIN`).
- xpose `pred_corr` injection is version-gated for xpose < 0.4 compatibility.
- LLOQ method selector (M1/M2/M3) added to VPC settings.

### v2.9.5 — VPC tab: non-default IDV support and regex fix

Two bug fixes for the VPC tab. Both surfaced when running `psn vpc -idv=TAD` (or any non-`TIME` IDV).

**Bug fixes**

- **xpose VPC failed at the parse step with `'\.' is an unrecognized escape in character string`.** A regex pattern in the xpose error-diagnostic block (added in v2.9.4) used Python f-string escaping that rendered as `\.` in R source. R 4.x rejects this. The two patterns now use `glob2rx("*.lst")` and `glob2rx("*.mod")`, letting R construct the regex itself.
- **vpc and xpose backends failed with "no idv column" when PsN was run with `-idv=TAD`.** Neither `vpc::vpc(psn_folder=...)` nor `xpose::vpc_data(psn_folder=...)` auto-detect the IDV column from PsN output, so non-default IDVs caused the run to abort with `No column for indepentent variable indicator found`. NMGUI2 now parses PsN's `meta.yaml` (preferred) or `command.txt` (fallback) to recover the IDV, DV, predcorr flag, samples, stratification column, and LLOQ that PsN actually used. The IDV is forwarded as `obs_cols=list(idv="…")` / `sim_cols=list(idv="…")` to `vpc::vpc()` and as `idv=…` inside `vpc_opt()` for xpose. The detected options are logged to the run console so users can see exactly what was recovered.

**New functionality**

- **IDV override field** — a new *IDV* field in the VPC settings panel (Row 5: IDV / LLOQ / ULOQ). Leave blank to use auto-detection; type a column name to override. Always available, regardless of "Use PsN settings", because the IDV column-name issue is independent of which numerical settings are used.

**Internal**

- New `_parse_psn_meta(vpc_folder)` helper reads `meta.yaml`'s `tool_options:` block and `command.txt` flags without adding a YAML dependency.
- New `_resolve_idv(vpc_folder)` centralises the resolution order: manual override → meta.yaml → command.txt → package default.

### v2.9.4 — VPC tab: hardening and new options

Seven targeted fixes and improvements to the VPC tab, covering silent failures, missing UI controls, and R script robustness.

**Bug fixes**

- **Stale `m1/` after a PsN re-run** — previously, if PsN's `vpc` was re-run with different settings and produced a fresh `m1.zip`, the app kept using the old extracted `m1/` folder. The extractor now compares the modification time of `m1.zip` against the newest file in `m1/` and re-extracts automatically when the zip is newer.
- **`vpc_results.csv` absence not detected** — PsN run with `-no_results=1` or an aborted VPC produces no `vpc_results.csv`, causing the R backend to fail with a confusing message. The app now detects this before running and prints a clear warning to the console.
- **`xpose4` confused with `xpose`** — users who have the legacy `xpose4` package installed (common in older NONMEM groups) but not the newer `xpose` package got a cryptic R error. The R-package check now explicitly detects this and shows: *"xpose ✗ (xpose4 found — run install.packages('xpose'))"*.
- **R locale mismatch** — on systems with a non-English `LC_NUMERIC` locale (e.g. Dutch/German), `read.csv` would misparse decimal separators in `vpc_results.csv`. Both generated R scripts now begin with `Sys.setlocale("LC_NUMERIC", "C")`.
- **xpose error messages lacked run-file diagnostics** — the xpose error handler now also lists `.lst` and `.mod` files in the run directory alongside sdtab files, so the cause of a "run not found" failure is immediately visible in the console.

**New functionality**

- **ULOQ field** — an upper limit of quantification field is now available next to LLOQ in the settings panel. Passed as `uloq=` to both `vpc::vpc()` and `xpose::vpc_opt()`. Disabled when "Use PsN settings" is checked.
- **Configurable timeout** — the hard-coded 5-minute R script timeout is replaced by a user-configurable *Timeout* field (1–120 min, default 30 min) in the settings panel. VPCs with 1000+ simulations routinely need 10–30 minutes.

**UX**

- Stratify field now has a tooltip warning that combining it with PsN's `-stratify_on` option produces incorrect results.

### v2.9.3 — VPC tab: auto-extract m1.zip

A focused bug-fix release for the VPC tab.

**Bug fix**

- **VPC failed silently when PsN had zipped the `m1/` folder.** PsN's `vpc` command produces `m1.zip` (instead of an unpacked `m1/`) when run with `-clean=2` or higher. Both VPC backends used by NMGUI2 — PsN's bundled `vpc.R` and the xpose-based plotter — read simulation tables from `m1/` directly, so they would either fail with "no simulation tables found" or silently produce an empty plot. The VPC tab now detects `m1.zip` on Run, extracts it in place if `m1/` is missing or empty, and logs the action to the run console. Existing unpacked `m1/` folders are left alone (no re-extract). Corrupt zips, permission errors, and unexpected layouts are reported with a clear error instead of failing silently. The folder hint in the VPC settings panel was updated to reflect that either `m1/` or `m1.zip` is acceptable.

### v2.9.2 — Files tab improvements

Focused on the Files tab: new file-type handling, usability fixes, and a conversion utility.

**New functionality**

- **Convert .tab to CSV** — right-click any `.tab` file in the file browser and choose *Convert to CSV*. A new `.csv` file is created in the same folder using comma-separated format. If the target file already exists a warning is shown and nothing is overwritten. The file list reloads automatically and the new CSV is selected.
- **NONMEM output files open as tables** — `.ext`, `.cov`, `.cor`, `.phi`, `.cnv`, `.coi` are now parsed by the NONMEM TABLE reader and open in the Table / Plot viewer, exactly like `.tab` files. Filter-bar pills for `.cnv` and `.coi` added.
- **Multi-section CSV files display correctly** — PsN summary reports such as `sir_results.csv` (multiple sections with repeated headers) are now merged into a single flat table with section-label rows (e.g. *── Quantiles (R type=2) ──*) instead of showing a broken single-column table.
- **Binary files show a friendly placeholder** — clicking a `.pdf`, `.png`, `.docx`, `.zip` or similar file now shows *"No preview available — double-click to open with the system application"* instead of garbled content.

**Usability fixes**

- **Resizable file-browser columns** — all three columns (Name, Size, Modified) are now freely draggable. Default widths: Name 220 px, Size 72 px, Modified 130 px.
- **Duplicate Table/Plot pills removed** — when a table file was open in Plot mode, two identical Table/Plot pill rows appeared. The inner row (from `DataExplorerWidget`) is now hidden when the widget is embedded in the Files tab.
- **Button text clipping on Linux** — `setFixedWidth` on the *Remove selected* and *Save settings* buttons in the Settings tab, and *Discard* in the Files toolbar, replaced with `setMinimumWidth` so text is never clipped on Linux.

### v2.9.1 — bug fixes and performance

A bug-fix release from a multi-lens code audit. No new features, no UI changes. Every fix was independently reviewed before merge.

**Bug fixes**

- **Editor and Notes panels stayed dark after theme switch.** The Editor and Notes panels in the Models tab now correctly update their palette colours when the theme is toggled (previously they remained at the original theme's background).
- **Open run popups stayed at the old theme.** `RunPopup` and `WatchLogPopup` are tracked on a popup-list and re-themed on theme change. Previously, popups opened in dark mode stayed dark after switching to light.
- **Run-output console font on Linux.** The console now uses the existing `monospace_font()` fallback chain (SF NS Mono → Consolas → DejaVu Sans Mono → …) instead of hardcoding "Menlo" / "Consolas". Linux gets a defined font instead of Qt's silent system fallback.
- **Stop-button race during run teardown.** `RunWorker._send_signal()` now also checks `isRunning()` alongside the existing `_proc` None-check, hardening the stop path against teardown races.
- **Dead code in dataset parser.** A no-op nested function inside the dataset-row parsing loop was discarded (it created an unused closure on every row).

**Performance**

- **Models tab — faster bulk fill.** `setUpdatesEnabled(False)` now wraps both the scan and filter `setItem` loops, eliminating per-cell repaints. Visible flicker on directories with 30+ models is gone, especially noticeable over X11/MobaXterm. The wrapper sits inside a `try/finally` so updates always re-enable, even if a row raises mid-fill.
- **Models scan — fewer file reads.** `ScanWorker` now caches `check_dataset()` results within a single scan, so a directory of 10 models that all reference the same dataset reads it once instead of ten times. Regex patterns used per-model (`$PROBLEM`, `$DATA`, `Based on:`) are compiled at module level instead of inline.
- **Detached runs — `_boot_time()` cached.** On Linux, the system boot time was being read from `/proc/stat` on every `is_alive()` check (≈1,200 redundant reads per 2-hour bootstrap with 5 active runs). Cached on first call now.
- **`set_reference()` no longer triggers a full model reset.** Only the affected columns (Name, dOFV) emit `dataChanged`.
- **Nav-icon cache.** Sidebar nav icons are now cached per `(name, size, color)`; theme toggling no longer redraws every icon from scratch.

### v2.9.0

- **New Model** — create a blank NONMEM control file directly from the Models tab. Click **New model…** in the filter row (or press Ctrl+N / ⌘N) to open a dialog that lets you choose a model name, pick a structural-model template (Blank, 1-CMT oral, 1-CMT IV, 2-CMT oral, 2-CMT IV), set the `$DATA` path with a file picker, and preview the rendered file before writing it. After creation the directory is rescanned and the new model is auto-selected with the Editor tab open.

### v2.8.0

- **Files tab now supports plotting** — selecting a `.tab` or `.csv` file shows a `[ Table | Plot ]` pill pair in the toolbar. Plot view is the full DataExplorer (scatter, LOESS, colour-by column, filters) that previously lived in the Evaluation tab. Column deduplication (from v2.7.9) now also applies in the Files tab viewer.
- **Evaluation tab simplified** — "Data Explorer" pill removed; the tab is now a clean 4-pill diagnostics panel: GOF | Individual Fits | OFV Waterfall | Convergence.
- **Auto-select sdtab in Files tab** — navigating to the Files tab with a model selected automatically highlights the model's sdtab in the file list.

### v2.7.9

- **Sim Plot — fix crash on duplicate column names** — NONMEM sdtab files that list the same column twice (e.g. `IPRED` appearing as both column 3 and 18) caused `pd.to_numeric` to raise `arg must be a list, tuple, 1-d array, or Series` because selecting a duplicate column returns a DataFrame instead of a Series. Duplicates are now renamed at load time (`IPRED` → `IPRED`, `IPRED_2`) and a warning is shown in the Data card label.

### v2.7.8

- **Sim Plot — PI band row redesign** — each band is now a single-line card (rounded, bordered) instead of a two-line layout; Alpha moved onto the same row as Lo/Hi; colour picker is now a circular 22×22 swatch; remove button is a round ghost pill that turns red on hover; "Add band" and "Add filter" buttons use a dashed-border style to communicate additive intent; band card spacing increased for breathing room; preset dropdown gains a tooltip warning it resets all bands. Changes are fully cross-platform (macOS/Windows/Linux).

### v2.7.7

- **Eliminated `-apple-system` startup warning** — Qt cannot resolve CSS-level font aliases like `-apple-system`; replaced with `"Helvetica Neue", "Segoe UI", Arial, sans-serif` which Qt can find on all platforms without the 71 ms alias-population penalty.

### v2.7.6

- **SF Mono actually renders now** — Qt registers `SFNSMono.ttf` under the internal family name `.SF NS Mono` (not `SF Mono`). The font priority list now uses the correct name, so macOS editors show SF Mono instead of Courier.
- **Removed `system-ui` from base stylesheet** — Qt does not understand the CSS `system-ui` keyword and emitted a 74 ms warning on every startup. Replaced with `-apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif`.

### v2.7.5

- **SF Mono now loads on macOS** — `QFontDatabase.addApplicationFont()` explicitly registers `/System/Library/Fonts/SFNSMono.ttf` (and the italic variant) at startup. Qt's normal font enumeration cannot see SF Mono; this one-time registration makes the `SF Mono` name resolvable so editors render in SF Mono instead of falling back to Menlo.

### v2.7.4

- **Virtualised table viewer** — CSV and NONMEM TABLE files in the Files tab are now backed by `QAbstractTableModel` + `QTableView` instead of `QTableWidget`. Qt only fetches data for visible rows, so files of any size (100k+ rows) open instantly and scroll smoothly. The 5 000-row cap and the "Showing first N rows" notice have been removed. Column sorting tries numeric comparison first, falling back to case-insensitive string sort.

### v2.7.3

- **Font priority reordered** — SF Mono is now first in the editor font chain: SF Mono → Consolas → DejaVu Sans Mono → JetBrains Mono → Cascadia Code → Liberation Mono → Menlo → Ubuntu Mono → Courier New. macOS users will see SF Mono by default.

### v2.7.2

- **File list panel wider** — Files tab middle pane default width increased from 240 → 320 px so filenames are no longer truncated on first open.
- **SF Mono added** to the monospace font priority list (macOS 10.12+, the font used by Xcode and Terminal). On a standard Mac without JetBrains Mono installed the editors now use SF Mono instead of Menlo.

### v2.7.1

- **Consistent monospace font** — both the Models tab editor and the Files tab viewer now use a shared `monospace_font()` helper that calls `QFont.setFamilies()` with a priority list: JetBrains Mono → SF Mono → Cascadia Code → Cascadia Mono → Consolas → DejaVu Sans Mono → Liberation Mono → Menlo → Ubuntu Mono → Courier New. `StyleHint.TypeWriter` ensures a monospace fallback on minimal installs. Both editors render at 11 pt.

### v2.7.0

New **Files tab** and **Models tab right-click additions**.

- **Files tab (Ctrl+2)** — three-pane file browser: extension filter checkboxes (`.mod`, `.ctl`, `.lst`, `.tab`, `.csv`, `.ext`, `.cov`, `.cor`, `.phi` pre-populated; custom extensions addable), sortable file list (name / size / modified), and content viewer with syntax highlighting for `.mod`/`.ctl`, inline find, and spreadsheet view for `.csv`/`.tab` with NONMEM `TABLE NO.` header handling. Row cap of 5 000 with notice. Edit/Save/Discard for text and CSV files.
- **Run** added to the top of the Models right-click menu — runs the selected model with current panel settings.
- **Open folder** added to the right-click menu — opens the model's directory in Finder / Explorer / xdg-open.
- **View .ext** added to the right-click menu (shown when a run exists) — opens the parameter-estimates-by-iteration file.
- **Delete…** added to the bottom of the right-click menu — removes `.mod` and all paired output files; parses `$DATA` to identify and exclude the dataset. Confirmation dialog lists every file before deletion.
- **Navigation shortcuts shifted**: Ctrl+2 = Files, Ctrl+3 = Tree, Ctrl+4 = Evaluation, Ctrl+5 = VPC, Ctrl+6 = Uncertainty, Ctrl+7 = Sim Plot, Ctrl+8 = History, Ctrl+9 = Settings.

### v2.6.13

- **Run detached defaults to OFF** — the "Run detached" checkbox now always starts unchecked, regardless of whether an SSH session is detected. Detached mode must be opted in to explicitly.

### v2.6.12

Sim Plot default panel width increased to 600 px.

- **Splitter default** — 380 → 600 px so the panel opens at the width where all spinbox values display fully without the user needing to drag the splitter
- **Panel max width** — 500 → 700 px to allow further widening if desired

### v2.6.11

Sim Plot spinboxes — adaptive width instead of fixed pixels.

- **Stop guessing font metrics** — fixed-width spinboxes (64 px) still clipped values because macOS font size varies with display scaling; switched Lo%, Hi% and Alpha spinboxes to `setMinimumWidth(62)` + `setMaximumWidth(110/90)` with `addWidget(stretch=1)` so they expand to fill whatever space the panel provides
- **Result**: spinboxes now use the full available panel width (typically 80–110 px each), guaranteeing values like "95.0" and "0.25" always display completely regardless of system font size or display scaling

### v2.6.10

Sim Plot band row — fix checkbox expansion and spinbox clipping.

- **Checkbox fixed width** — `setFixedWidth(20)` added to the visibility checkbox; without it, `QCheckBox` has `Preferred` size policy and silently absorbs all spare horizontal space, pushing the colour swatch and × button off-screen
- **`row1.addStretch()`** — explicit stretch added at the end of the band row so any remaining panel width goes to blank space on the right, not to widgets
- **Spinboxes widened 58 → 64 px** — on macOS the arrow buttons consume ~28 px, leaving 30 px text area at 58 px; "95.0" (4 chars) needs ~32 px and clipped to "9". At 64 px the text area is 36 px, enough for all expected values
- **Alpha row spacer uses literal 20 px** — previously used `sizeHint()` which would not match the now-fixed checkbox width

### v2.6.9

Sim Plot band row redesign — two-line layout with inline labels.

- **Root cause fixed** — macOS QDoubleSpinBox has a minimum intrinsic rendering width (~58 px); forcing 46 px clipped the value to nothing. Pixel-squeezing six controls onto one line was the wrong architecture
- **Two-line band rows** — each band now uses two compact lines: line 1 holds the visibility checkbox, Lo%, Hi%, colour swatch and remove button; line 2 holds Alpha. Inline labels ("Lo%", "Hi%", "Alpha") replace the old separate column-header row
- **Spinboxes now 58 px** — wide enough for macOS to render "49.9" and "0.25" without clipping
- **Column-header row removed** — no longer needed; inline labels provide the same context without alignment fragility
- **Colour swatch restored to 32 px** — previous shrink to 26 px hit macOS button minimums

### v2.6.8

Sim Plot band row layout overhaul — all controls now fully visible.

- **Removed `%` suffix from Lo/Hi spinboxes** — the column header "Lo%" / "Hi%" already communicates the unit; dropping the suffix saves ~12 px per spinbox and lets the values render fully
- **Narrowed Lo/Hi spinboxes** — 60 → 46 px (fits "49.9" at 1 decimal place)
- **Narrowed colour swatch** — 32 → 26 px (still clearly a colour picker)
- **Narrowed alpha spinbox** — 58 → 52 px
- **Narrowed remove button** — 22 → 20 px
- **Tightened row spacing** — 4 → 3 px between widgets
- **New band row total: 221 px** (was 270 px) — fits comfortably in the available content width with ~40 px to spare, even accounting for the vertical scrollbar
- **Filter header fixed** — Op and Value column labels now have explicit fixed widths (52 / 72 px) matching the data row, so "Op" is never clipped

### v2.6.7

Sim Plot panel default width correction.

- **Wider default panel** — splitter default increased from 300 → 380 px and max-width from 400 → 500 px; the vertical scrollbar was consuming ~15 px of horizontal space, causing the band row columns to clip even at 300 px; 380 px gives ~333 px usable content width, well clear of the 270 px band row

### v2.6.6

Sim Plot left panel layout fixes.

- **Narrower band rows** — Lo%/Hi% spinboxes reduced from 68 → 60 px, Alpha from 72 → 58 px so all columns (including the × button) fit without clipping
- **Narrower panel** — default splitter position reduced from 360 → 300 px; max panel width reduced from 480 → 400 px
- **Span spinbox** — widened from 62 → 70 px so "0.30" is never clipped

### v2.6.5

Sim Plot LOESS smoothing option.

- **Smooth curves** — new checkbox in the *Appearance* card applies LOESS smoothing to all PI ribbon boundaries and the median line before rendering; a **Span** spinbox (0.05–1.0, default 0.30) controls bandwidth — lower follows data closely, higher gives a smoother curve

### v2.6.4

Sim Plot MDV filter accessibility fix.

- **MDV filter moved to Filters card** — the "Exclude MDV=1 rows" checkbox is now in the *Filters* card (expanded by default) instead of the collapsed *Appearance* card, making it immediately visible and easy to toggle

### v2.6.3

Sim Plot usability and layout fixes.

- **Workflow hint** — a note in the Data card explains that the Sim Plot tab requires a NONMEM simulation output file with a replicate column (REP, IREP, SIM, SIMNO…), not a standard estimation sdtab
- **Replicate column validation** — a status bar warning is shown when no recognised replicate column is found in the loaded file, preventing meaningless plots from being silently generated
- **Median colour default** — now initialises to the current theme foreground colour instead of white (which was invisible on light backgrounds)
- **PI band header alignment** — column labels (Vis / Lo% / Hi% / Colour / Alpha) now use exact fixed widths matching the data row widgets so they align correctly
- **Alpha spinbox** — widened from 58 px to 72 px; values such as "0.25" no longer clip to "0"
- **Y-axis label overflow** — replaced `tight_layout` with explicit `subplots_adjust` so the Y-axis label no longer overflows beyond the right edge of the canvas

### v2.6.2

Performance and audit fixes.

- **Threaded table loading** — the Evaluation tab now parses sdtab files in a background QThread; the Load button shows "Loading…" while parsing and the UI stays fully responsive on large files or slow network drives
- **IndFit row bounds guard** — ragged rows (fewer columns than the header) in the Individual Fits widget no longer raise IndexError; they are silently skipped
- **GOF replot error logging** — the silent `except Exception: pass` in the GOF 2×2 replot is replaced with a debug-level log entry so errors are visible with `--debug` without crashing

### v2.6.1

Bug fixes for the Sim Plot tab and the Models tab METHOD column.

- **SIM method label** — simulation-only runs (`$SIM` without `$EST`) now display **SIM** in the METHOD column of the Models tab instead of the incorrect default **FO**
- **Sim Plot layout** — PI band rows redesigned: label-free compact layout with a column header row, `%` suffix on spinboxes, wider panel (360 px default), compact Browse/Load buttons; filter rows similarly updated

### v2.6.0

New **Simulation Plot** tab for Monte Carlo prediction interval visualisation.

- **Sim Plot tab** — a dedicated tab (Ctrl+6) for plotting prediction intervals from NONMEM Monte Carlo simulation output. Load any NONMEM table file or CSV (no row-count cap), configure PI bands, and generate publication-ready plots in seconds
- **Unlimited file loading** — the table parser now accepts `max_rows=None` so large simulation files (50k–500k rows typical for 1 000 replicates × 500 time points) load fully without truncation
- **Replicate auto-detection** — the tab recognises explicit replicate columns (`REP`, `IREP`, `SIM`, `SIMNO`, `REP_NO`, `SIM_NUM`, etc.) and also detects ID-cycling automatically when no explicit column is present
- **Configurable PI bands** — up to 4 simultaneous prediction interval ribbons, each with its own percentile pair (Lo/Hi %), colour (colour picker), alpha and visibility toggle. Four presets cover the most common pharmacometric conventions (5/95 + 25/75, 2.5/97.5 + 10/90, etc.)
- **Multiple filters** — up to 6 independent column filters (`==`, `!=`, `>`, `<`, `>=`, `<=`), ANDed together, to subset by compartment, dose group, sex, or any other column before plotting
- **Median line** — configurable colour and line width; computed as the 50th percentile across replicates
- **Log/linear Y-axis** — one checkbox toggles between linear and logarithmic scale, essential for PK concentration-time plots
- **MDV=1 exclusion** — dosing-only rows filtered out by default before quantile computation
- **Observed data overlay** — optional second file load; observed DV points are overlaid as a semi-transparent scatter on the simulated ribbons, with independent X/Y column selectors
- **Background computation** — all quantile calculations run in a QThread so the UI stays responsive on large datasets
- **Save PNG** — 300 DPI export via matplotlib `savefig`
- **Model context** — selecting a model in the Models tab sets the browse directory for the Sim Plot file dialog, consistent with Evaluation and VPC tabs

### v2.5.8

Bug fix for the ETA vs Covariate plot.

- **ET\d+ columns now recognised as ETAs** — NONMEM truncates `ETA(12)` to `ET12` in TABLE output. The ETA dropdown previously required the full `ETA` prefix, so `ET12`, `ET13`, `ET14` etc. were silently placed in the covariates list and the dropdown stayed empty. Fixed by also accepting `ET\d+` and `PHI\d+` column names as ETAs
- **Residual columns excluded from covariates** — `NPDE`, `IWRES` and `WRES` added to the covariate skip-list (alongside the existing `CWRES`, `PRED`, `IPRED` etc.) so they no longer appear as candidate covariates

### v2.5.7

New GOF features.

- **NPDE distribution plot** — a new "NPDE Dist" pill appears in the GOF sub-strip whenever the loaded table file contains an NPDE column. Shows a histogram with a normal density overlay and mean/SD statistics, identical in style to the CWRES Hist panel. When NPDE is absent the button is hidden automatically
- **PNG export on all matplotlib GOF panels** — CWRES Hist, QQ Plot and NPDE Dist each now have a "Save PNG…" button that saves a 300 DPI PNG via matplotlib's `savefig`; the button is disabled until a plot has been rendered

### v2.5.6

Bug fix for the Ron Keizer `vpc` backend.

- **Three CI bands now visible** — `pi_as_area` was incorrectly set to `TRUE`, which collapsed the three separate confidence ribbons (around the 5th, 50th and 95th simulated percentiles) into a single filled slab. Changed to `FALSE` (the vpc package default) so a proper three-band VPC is displayed
- **Readr parsing warnings suppressed** — NONMEM simulation files embed a `TABLE NO.` header row every N records; readr emits ~2000 parsing-failure warnings per VPC run (one per simulation replicate). These are harmless but were alarming. The vpc() call is now wrapped in `withCallingHandlers` to muffle only those specific warnings while keeping real R errors visible

### v2.5.5

VPC tab overhaul — fixes implausible plots from the Ron Keizer `vpc` backend and removes the outdated `xpose4` backend.

- **xpose4 backend removed** — xpose4 is no longer maintained and produced implausible VPCs; the modern `xpose` package is a strict improvement
- **"Use PsN settings" mode (default on)** — when checked, binning, stratification, pred-corr and LLOQ are inherited directly from the PsN output folder for both the `vpc` and `xpose` backends. Previously the tab always forced `bins="auto"` and explicit `pred_corr`/`stratify` args that overrode PsN's values, misaligning observations and simulated prediction intervals
- **Correct bins argument** — when overriding manually, `bins="jenks"` is used instead of the invalid `"auto"` string
- **Workflow hint** — a one-line note at the top of the VPC settings panel explains that a PsN `vpc` run must be completed first
- **Validation gate fix** — stratification column validation is now skipped when "Use PsN settings" is checked (the column is inherited from PsN and may not appear literally in the widget)
- **R status bar** now shows only the two current backends: `vpc` and `xpose`

### v2.5.4

Bug-fix release (Tier 1 audit items + R availability check).

- **Python 3.9 compatibility** — `detached_runs.py` used `int | None`, `list[dict]` and `tuple[list, list]` type annotations introduced in Python 3.10. Added `from __future__ import annotations` so the file imports cleanly on Python 3.9 (common on HPC clusters running CentOS/RHEL 8)
- **VPC column name sanitisation** — stratification column names are now cleaned with `_r_col()` before embedding in the generated R script; control characters and embedded quotes that would break the R string literal are stripped. A separate `_sanitize_r` improvement also strips newlines and other control characters from path strings
- **Config directory creation** — `CONFIG_DIR.mkdir()` is now wrapped in `try/except OSError`; on HPC systems with a read-only home directory the app previously raised `PermissionError` at import time and refused to start
- **R availability check at startup** — if `Rscript` is not found on PATH, a status bar message is shown immediately on startup explaining that VPC and RStudio features are unavailable; previously the first indication was an opaque error when actually trying to use those features

### v2.5.3

Bug-fix release (continued audit follow-up).

- **Parameter export status message** — the "Parameters exported" status bar message no longer crashes when the widget tree is not in the expected shape; the `hasattr(self,'parent')` guard was always True and gave false safety
- **GOF axis column fallback** — when a previously-selected X-axis column (e.g. CWRES) is absent from a newly-loaded table, the plot now falls back to the panel default (PRED or TIME) instead of silently selecting column 0 (which was typically ID or TIME at random)
- **GOF file-open imports** — `__import__('os')` / `__import__('subprocess')` inline hacks in the "Open exported PNG?" handler replaced with normal top-level imports
- **History tab run I/O** — `_load_runs` / `_save_runs` local duplicates removed; history tab now calls the canonical locked versions from `config.py`, so thread-safety fixes and future bug fixes apply consistently
- **Unused import removed** — `APP_VERSION` was imported but never used in `detached_runs.py`
- **RStudio .Rproj creation** — `write_text()` is now wrapped in a `try/except OSError`; read-only project directories (common on shared drives) now return a user-visible error instead of raising an unhandled exception

### v2.5.2

Bug-fix release addressing findings from a thorough internal audit.

- **Force-kill fixed** — the "Force kill (SIGKILL)" stop option in run popups now works correctly; previously it called a non-existent method and silently did nothing
- **Boundary warning restored** — "Parameter near boundary" warnings are now correctly recorded in run history; a key-name mismatch was preventing this flag from ever being stored
- **Median statistics corrected** — bootstrap and SIR results (bias, RSE, median parameter, dOFV median) now use a proper median calculation; the previous index-based approach produced a systematic upward bias for even-sized samples (7 call sites fixed)
- **Splitter layout persists** — panel splitter sizes are now correctly restored on startup; an early-return in geometry restore was skipping the splitter step
- **Detached run reconciliation fixed (macOS)** — `_boot_time()` previously returned `0.0` on non-Linux platforms, causing every detached run to be marked finished immediately after restart; it now returns `None` and the start-time cross-check is skipped when unavailable
- **Config write thread-safety** — all config file writers (`save_settings`, `save_bookmarks`, `save_runs`) now hold the same lock as `save_meta`, preventing rare corruption from concurrent worker and main-thread writes
- **Subprocess session handling** — `RunWorker` now uses `start_new_session=True` (was `preexec_fn=os.setsid`, which is unsafe with Python threads and can deadlock on macOS); `import signal` moved to module scope
- **LRT method-mismatch guard** — the workbench comparison table now shows "N/A" with a tooltip instead of a p-value when the reference and candidate models used different estimation methods (e.g. FOCE vs SAEM); exported CSV emits `method_mismatch` in that column
- **Waterfall plot at OBJ=0** — subjects with an individual OBJ of exactly 0.0 were excluded from the waterfall plot because the value is falsy; corrected to `is not None`
- **ETA–covariate plot filters MDV rows** — dosing records (MDV=1) are now excluded from ETA vs covariate scatter plots, consistent with all other diagnostic plots

### v2.5.1

- **Detached runs (SSH/MobaXterm)** — a new "Run detached" checkbox in the Run panel launches PsN under `nohup` in a new session so the job keeps running even if NMGUI2 is closed or the SSH connection drops. Automatically pre-checked when an SSH session is detected. Output is saved to a per-run `.nmgui.log` file in the project folder. Click the detached row in the Active & Recent Runs table to tail the log in a Watch Log window. On the next NMGUI2 startup, finished detached runs are automatically reconciled (status, timestamps, OFV) without relying on any shutdown hooks. Linux and macOS only.

### v2.5.0

- **Concurrent popup runs** — clicking Run now opens a dedicated floating window per model run; multiple models run simultaneously in independent windows, each with its own live console, iteration/OFV progress indicator, elapsed timer, and gentle/force stop controls; on completion the window title and status bar update with the termination result
- **Active & Recent Runs panel** — the Run sub-tab now shows a persistent table of active and recent runs for the current project folder; click a live row to raise its popup window; historical rows are loaded from `nmgui_run_records.json` in the project directory and survive app restarts; interrupted runs are shown as "? Interrupted"
- **Theme overhaul** — forced Fusion style across all platforms for consistent dark-mode behaviour; migrated ~20 widgets from per-widget stylesheets to object-name + global QSS so theme toggle reliably refreshes every label, separator, spin-box, combo-box and highlighter in the app
- **QC report** — right-click any completed model → *QC Report…* to open a self-contained HTML report with a PASS / WARN / FAIL checklist covering termination, covariance, condition number, %RSE, parameter correlations, shrinkage, ETABAR and omega boundary checks
- **Model workbench** — *Workbench…* button opens a sortable table of all completed models with ΔOFV, ΔAIC, ΔBIC, LRT p-value and reference-model selector for quick multi-model comparison
- **Enhanced compare dialog** — the two-model comparison dialog now shows a statistics strip with ΔOFV, ΔAIC, ΔBIC, Δ parameters, LRT p-value and a significance verdict
- **Dataset integrity checks** — at scan time, each model's data file is automatically checked for missing file, column-count mismatches, non-monotonic TIME, duplicate doses, extreme DV values and high BLQ proportion; issues appear in the Info tab's Dataset card
- **Collapsible layout** — the Info panel uses collapsible cards (Dataset / Annotation / Notes); the Parameters tab THETA / OMEGA / SIGMA blocks collapse and expand by clicking the section header
- **Multi-$EST chain parsing** — the `.lst` Output tab now renders one row per estimation step with per-step OFV, ΔOFV, runtime, significant digits and termination status
- **Run records** — immutable audit trail for every run (UUID, SHA-256 hashes of control stream and dataset, NONMEM/PsN/NMGUI versions, duration, final OFV and status) accessible from the right-click menu
- **Correctness fixes** — LRT p-value now correctly signed when the reference model has fewer parameters; VPC "Save PDF…" reliably produces a PDF; run record and workbench display OFV = 0.0 correctly; GitHub update-check uses numeric version comparison instead of lexicographic
