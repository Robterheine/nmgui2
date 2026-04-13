# NMGUI2

**A standalone desktop application for NONMEM pharmacometric modelling workflows**

NMGUI2 is a PyQt6 desktop application that brings together everything a pharmacometrician needs in one window: browse and compare NONMEM models, evaluate goodness-of-fit, run PsN tools, read `.lst` output, and visualise model lineage — without switching between terminals, text editors and R.

It runs entirely offline on macOS, Windows and Linux. No browser. No server. No internet connection required during use.

![NMGUI2 Models tab](screenshots/screenshot2.png)

---

## Table of contents

- [Features](#features)
- [Dependencies overview](#dependencies-overview)
- [Installation — macOS](#installation--macos)
- [Installation — Windows](#installation--windows)
- [Installation — Linux](#installation--linux)
- [First use](#first-use)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Configuration files](#configuration-files)
- [Contributing](#contributing)
- [Author](#author)
- [Acknowledgements](#acknowledgements)
- [License](#license)

---


## Features

### Models tab
- Scans a directory for `.mod` files and displays all models in a sortable table
- Columns: OFV, ΔOFV (relative to best or user-selected reference), minimisation status, covariance step, condition number, estimation method, individuals, observations, parameters, AIC, runtime
- Colour-coded: green = successful, red = failed/terminated, orange = boundary/stale
- **Right-click context menu** on any model: toggle star, duplicate, set reference model, compare with another model, view `.lst`, show NM-TRAN messages
- Keyboard navigation: ↑↓ move rows, Space toggles star, Enter jumps to Output

### Model detail panel
**Parameters** — full THETA/OMEGA/SIGMA table with names, estimates, SE, RSE%, 95% CI, SD. Handles `BLOCK(n) SAME` designs correctly. Export to CSV and HTML report.

**Editor** — syntax-highlighted `.mod` editor with save.

**Run** — launch any PsN tool with live console output and stop button.

**Info** — comment, status tag (base/candidate/final), notes — all persisted.

**Output** — structured HTML rendering of the `.lst` file in-app: summary card, NM-TRAN warnings, convergence table, parameters, ETABAR/shrinkage, correlation and covariance matrices, eigenvalues and condition number. "Open in browser" exports full HTML.

### Ancestry tree
Interactive node graph of model lineage based on `";; 1. Based on:"` PsN metadata. Zoom, pan, double-click to select a model.

### Model Evaluation
GOF 2×2, CWRES histogram, QQ plot with Shapiro-Wilk, ETA vs covariate, individual fits, OFV waterfall, convergence traces, and a reactive data explorer with multi-filter scatter plots.

### VPC tab
Generate VPCs via vpc, xpose or xpose4 R backends. Editable R script, PNG/PDF export.

### Run History
Full history of PsN runs with status, duration, and command preview.

### Settings
Dark/light theme, path configuration, bookmarks — all persisted between sessions.

---

## Dependencies overview

### Always required

| Dependency | Minimum version | Purpose |
|---|---|---|
| Python | 3.10 | Runtime |
| PyQt6 | 6.4 | GUI framework |
| pyqtgraph | 0.13 | Interactive plots |
| numpy | 1.24 | Numerical operations |
| matplotlib | 3.7 | CWRES histogram, QQ plot |

### Required for running models

| Dependency | Minimum version | Notes |
|---|---|---|
| NONMEM | 7.4 | Must be installed and licensed |
| PsN (Perl-speaks-NONMEM) | 5.6 | Must be on system PATH |
| Perl | 5.16 | Required by PsN |

### Required for VPC generation

| Dependency | Notes |
|---|---|
| R ≥ 4.0 | Must be on system PATH (`Rscript` command must work) |
| RStudio | Optional but recommended |
| R package: vpc | `install.packages("vpc")` |
| R package: xpose | `install.packages("xpose")` |
| R package: xpose4 | `install.packages("xpose4")` |
| R package: tidyverse | `install.packages("tidyverse")` — required by xpose |
| R package: ggplot2 | `install.packages("ggplot2")` — required by vpc/xpose |

> NMGUI2 (browsing, evaluating, comparing results) works without NONMEM, PsN, R or RStudio. These are only needed if you want to run models or generate VPCs from within the app.

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

### 4. Install R

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

Make sure RStudio is accessible from the command line — NMGUI2 can launch it directly.

### 6. Install required R packages

Open Terminal and run:

```bash
Rscript -e 'install.packages(c("vpc","xpose","xpose4","tidyverse","ggplot2"), repos="https://cran.r-project.org")'
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

### 9. Clone NMGUI2

```bash
git clone https://github.com/robterheine/nmgui2.git
cd nmgui2
```

### 10. Install Python dependencies

```bash
pip3 install PyQt6 pyqtgraph numpy matplotlib
```

### 11. Run NMGUI2

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

### 2. Install R

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
Rscript -e "install.packages(c('vpc','xpose','xpose4','tidyverse','ggplot2'), repos='https://cran.r-project.org')"
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

### 8. Clone NMGUI2

Open Command Prompt:

```cmd
git clone https://github.com/robterheine/nmgui2.git
cd nmgui2
```

### 9. Install Python dependencies

```cmd
pip install PyQt6 pyqtgraph numpy matplotlib
```

### 10. Run NMGUI2

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
sudo apt install -y python3 python3-pip git curl perl
python3 --version
```

### 2. Install Qt system libraries (required by PyQt6)

```bash
sudo apt install -y libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0 \
    libgl1-mesa-glx libegl1
```

### 3. Install R

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
Rscript -e 'install.packages(c("vpc","xpose","xpose4","tidyverse","ggplot2"), repos="https://cran.r-project.org")'
```

### 6. Install PsN

Follow the official guide at https://uupharmacometrics.github.io/PsN/install.html

Verify:
```bash
execute --version
```

### 7. Clone NMGUI2

```bash
git clone https://github.com/robterheine/nmgui2.git
cd nmgui2
```

### 8. Install Python dependencies

```bash
pip3 install PyQt6 pyqtgraph numpy matplotlib
```

Or with a virtual environment (recommended):

```bash
python3 -m venv venv
source venv/bin/activate
pip install PyQt6 pyqtgraph numpy matplotlib
```

### 9. Run NMGUI2

```bash
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
```

No reinstallation of Python packages is needed unless a new dependency has been added.

---

## First use

1. Launch the app (`python3 nmgui2.py`)
2. Click **Browse…** or **File → Open Directory** (⌘O / Ctrl+O) and navigate to a folder containing `.mod` files
3. Click **+ Bookmark** to save the directory for quick access
4. Select a model row to view its parameters, output, and diagnostic plots
5. Go to **Settings** (⌘6 / Ctrl+6) to configure PsN, NONMEM, and RStudio paths if they are not auto-detected from PATH

---

## Keyboard shortcuts

| Action | macOS | Windows / Linux |
|---|---|---|
| Models tab | ⌘1 | Ctrl+1 |
| Tree tab | ⌘2 | Ctrl+2 |
| Evaluation tab | ⌘3 | Ctrl+3 |
| VPC tab | ⌘4 | Ctrl+4 |
| History tab | ⌘5 | Ctrl+5 |
| Settings tab | ⌘6 | Ctrl+6 |
| Open directory | ⌘O | Ctrl+O |
| Rescan directory | ⌘R | Ctrl+R |
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

To reset all settings: delete the `~/.nmgui/` folder.

---

## Contributing

Contributions are very welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

Areas particularly in need of help:
- Windows and Linux testing and bug reports
- Additional NONMEM output parsing (multiple estimation steps, SAEM, IMP, BAYES)
- New diagnostic plot types
- Documentation and tutorials

---

## Author

**Rob ter Heine**
Hospital pharmacist – clinical pharmacologist
[Radboud Applied Pharmacometrics](https://www.radboudumc.nl/en/research/research-groups/radboud-applied-pharmacometrics) · Radboudumc, Nijmegen, the Netherlands

---

## Acknowledgements

Developed with [Claude Sonnet 4.6](https://www.anthropic.com) by Anthropic.

---

## License

[MIT License](LICENSE) — free to use, modify and distribute.
