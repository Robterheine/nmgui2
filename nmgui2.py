#!/usr/bin/env python3
"""
NMGUI v2 — Standalone PyQt6 NONMEM Run Manager
Rob ter Heine | Radboudumc | 2026

Drop next to parser.py and run:
    python3 nmgui2.py
"""

import os, sys, json, re, time, math, shlex, subprocess, signal, threading
from pathlib import Path
from datetime import datetime

# ── Qt ────────────────────────────────────────────────────────────────────────
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QLabel, QPushButton, QLineEdit, QFileDialog, QPlainTextEdit, QTextEdit,
    QComboBox, QCheckBox, QDoubleSpinBox, QGroupBox, QSizePolicy,
    QDialog, QMessageBox, QDialogButtonBox, QRadioButton, QButtonGroup,
    QAbstractItemView, QMenu, QInputDialog, QFormLayout,
    QListWidget, QListWidgetItem, QStackedWidget,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QAbstractTableModel, QModelIndex,
)
from PyQt6.QtGui import (
    QColor, QFont, QAction, QBrush, QPixmap,
    QSyntaxHighlighter, QTextCharFormat, QKeySequence,
)

# ── Plotting ──────────────────────────────────────────────────────────────────
try:
    import numpy as np
    HAS_NP = True
except ImportError:
    HAS_NP = False
    np = None

try:
    import pyqtgraph as pg
    pg.setConfigOptions(antialias=True, background='#1e1e1e', foreground='#cccccc')
    HAS_PG = True
except ImportError:
    HAS_PG = False

try:
    import matplotlib
    matplotlib.use('QtAgg')
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

# ── SciPy (for statistical tests) ─────────────────────────────────────────────
try:
    from scipy.stats import chi2 as scipy_chi2, kstest as scipy_kstest
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    scipy_chi2 = None
    scipy_kstest = None

# ── Parser ────────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
_PARSER_ERR = ''
try:
    from parser import (
        parse_lst, find_runs, read_table_file, inject_estimates,
        parse_nmtran_errors, extract_param_names, parse_ext_file,
        extract_table_files, parse_phi_file,
    )
    HAS_PARSER = True
except Exception as _pe:
    HAS_PARSER = False
    _PARSER_ERR = str(_pe)

# ── Constants ─────────────────────────────────────────────────────────────────
IS_WIN  = sys.platform == 'win32'
IS_MAC  = sys.platform == 'darwin'
HOME    = Path.home()
CONFIG_DIR = HOME / '.nmgui'
CONFIG_DIR.mkdir(exist_ok=True)
META_FILE      = CONFIG_DIR / 'model_meta.json'
SETTINGS_FILE  = CONFIG_DIR / 'settings.json'
BOOKMARKS_FILE = CONFIG_DIR / 'bookmarks.json'
RUNS_FILE      = CONFIG_DIR / 'runs.json'
APP_VERSION    = '2.1.0'
_cfg_lock      = threading.Lock()

# ── Parameter Uncertainty Diagnostic Thresholds ──────────────────────────────
# Bootstrap thresholds
BOOT_COMPLETION_PASS = 0.90
BOOT_COMPLETION_WARN = 0.80
BOOT_COMPLETION_FAIL = 0.70
BOOT_BIAS_PASS = 0.10
BOOT_BIAS_WARN = 0.20
BOOT_BIAS_FAIL = 0.50
BOOT_CORR_WARN = 0.90
BOOT_CORR_FAIL = 0.99

# SIR thresholds
SIR_KS_PASS = 0.05
SIR_KS_WARN = 0.01
SIR_MEDIAN_PASS = 0.15
SIR_MEDIAN_WARN = 0.30
SIR_ESS_PASS = 0.50
SIR_ESS_WARN = 0.30
SIR_ESS_FAIL = 0.10
SIR_ESS_ABS_WARN = 500
SIR_ESS_ABS_FAIL = 200

# ── Theme system ─────────────────────────────────────────────────────────────
# All colours come from the active theme dict — never hard-coded elsewhere.

THEMES = {
    'dark': {
        'bg':        '#1a1a20',
        'bg2':       '#22222c',
        'bg3':       '#2a2a36',
        'bg4':       '#32323f',
        'border':    '#3a3a50',
        'fg':        '#dde0ee',
        'fg2':       '#7a7d9a',
        'fg3':       '#55586e',
        'accent':    '#4c8aff',
        'accent_h':  '#6aa0ff',
        'accent_bg': '#1a2a4a',
        'green':     '#3ec97a',
        'red':       '#e85555',
        'orange':    '#e89540',
        'yellow':    '#d4c060',
        'star':      '#f0c040',
        'sel':       '#1e3a5a',
        'pg_bg':     '#1a1a20',
        'pg_fg':     '#9090aa',
    },
    'light': {
        'bg':        '#f2f2f7',
        'bg2':       '#ffffff',
        'bg3':       '#e8e8f0',
        'bg4':       '#d8d8e8',
        'border':    '#c0c0d0',
        'fg':        '#1a1a2e',
        'fg2':       '#5a5a70',
        'fg3':       '#9090a0',
        'accent':    '#2563eb',
        'accent_h':  '#1d4ed8',
        'accent_bg': '#eff6ff',
        'green':     '#16a34a',
        'red':       '#dc2626',
        'orange':    '#d97706',
        'yellow':    '#b45309',
        'star':      '#d97706',
        'sel':       '#dbeafe',
        'pg_bg':     '#ffffff',   # white plot background — max contrast
        'pg_fg':     '#1a1a2e',   # near-black axes, labels, titles
    }
}

_active_theme = 'dark'

def T(key):
    """Get colour from active theme."""
    return THEMES[_active_theme][key]

# Legacy aliases — keep these so existing code doesn't break
def _set_theme_aliases():
    global C_BG, C_BG2, C_BG3, C_BORDER, C_FG, C_FG2
    global C_GREEN, C_RED, C_ORANGE, C_BLUE, C_YELLOW, C_STAR, C_STALE
    t = THEMES[_active_theme]
    C_BG     = t['bg'];    C_BG2   = t['bg2'];   C_BG3    = t['bg3']
    C_BORDER = t['border']; C_FG   = t['fg'];    C_FG2    = t['fg2']
    C_GREEN  = t['green']; C_RED   = t['red'];   C_ORANGE = t['orange']
    C_BLUE   = t['accent']; C_YELLOW= t['yellow']; C_STAR  = t['star']
    C_STALE  = t['orange']

_set_theme_aliases()


def build_stylesheet(theme_name='dark'):
    t = THEMES[theme_name]
    return f"""
/* ── Base ─────────────────────────────────────── */
QMainWindow, QWidget, QDialog {{
    background: {t['bg']}; color: {t['fg']};
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 13px;
}}

/* ── Tabs ─────────────────────────────────────── */
QTabBar::tab {{
    background: {t['bg2']};
    color: {t['fg2']};
    padding: 7px 18px;
    border: 1px solid {t['border']};
    border-bottom: none;
    margin-right: 1px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    font-size: 13px;
}}
QTabBar::tab:selected {{
    background: {t['bg']};
    color: {t['fg']};
    border-bottom: 2px solid {t['accent']};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{ color: {t['fg']}; background: {t['bg3']}; }}

/* ── Tables ───────────────────────────────────── */
QTableWidget, QListWidget {{
    background: {t['bg2']};
    color: {t['fg']};
    gridline-color: {t['bg3']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    selection-background-color: {t['sel']};
    selection-color: {t['fg']};
    alternate-background-color: {t['bg3']};
    outline: none;
}}
QTableWidget::item {{ padding: 3px 6px; border: none; }}
QTableWidget::item:selected {{ background: {t['sel']}; color: {t['fg']}; }}
QHeaderView {{ background: {t['bg2']}; border: none; }}
QHeaderView::section {{
    background: {t['bg3']};
    color: {t['fg2']};
    padding: 5px 8px;
    border: none;
    border-right: 1px solid {t['border']};
    border-bottom: 1px solid {t['border']};
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QHeaderView::section:first {{ border-top-left-radius: 5px; }}

/* ── Buttons ──────────────────────────────────── */
QPushButton {{
    background: {t['bg3']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    padding: 5px 16px;
    min-width: 72px;
    border-radius: 5px;
    font-size: 13px;
}}
QPushButton:hover {{ background: {t['bg4']}; border-color: {t['fg3']}; }}
QPushButton:pressed {{ background: {t['accent_bg']}; border-color: {t['accent']}; }}
QPushButton:disabled {{ color: {t['fg3']}; }}
QPushButton#primary {{
    background: {t['accent']};
    color: #ffffff;
    border: none;
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {t['accent_h']}; }}
QPushButton#danger {{
    background: transparent;
    color: {t['red']};
    border: 1px solid {t['red']};
}}
QPushButton#danger:hover {{ background: {t['red']}; color: #fff; }}

/* ── Inputs ───────────────────────────────────── */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {t['bg2']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    padding: 4px 8px;
    border-radius: 5px;
    selection-background-color: {t['accent_bg']};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {t['accent']};
}}
QComboBox {{
    background: {t['bg2']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    padding: 4px 8px;
    border-radius: 5px;
}}
QComboBox:focus {{ border-color: {t['accent']}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{ width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {t['bg2']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    selection-background-color: {t['sel']};
}}

/* ── Scrollbars ───────────────────────────────── */
QScrollBar:vertical {{
    background: {t['bg']};
    width: 8px;
    margin: 0;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {t['border']};
    min-height: 24px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{ background: {t['fg3']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {t['bg']};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {t['border']};
    min-width: 24px;
    border-radius: 4px;
}}

/* ── Splitter ─────────────────────────────────── */
QSplitter::handle {{
    background: {t['border']};
}}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

/* ── Misc ─────────────────────────────────────── */
QStatusBar {{
    background: {t['bg2']};
    color: {t['fg2']};
    border-top: 1px solid {t['border']};
    font-size: 12px;
    padding: 2px 8px;
}}
QGroupBox {{
    border: 1px solid {t['border']};
    border-radius: 6px;
    margin-top: 10px;
    padding: 12px 8px 8px 8px;
    color: {t['fg2']};
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}}
QLabel {{ color: {t['fg']}; }}
QLabel#muted {{ color: {t['fg2']}; font-size: 12px; }}
QLabel#section {{ color: {t['fg2']}; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
QCheckBox {{ color: {t['fg']}; spacing: 6px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {t['border']};
    border-radius: 3px;
    background: {t['bg2']};
}}
QCheckBox::indicator:checked {{
    background: {t['accent']};
    border-color: {t['accent']};
}}
QRadioButton {{ color: {t['fg']}; spacing: 6px; }}
QRadioButton::indicator {{
    width: 14px; height: 14px;
    border: 2px solid {t['fg3']};
    border-radius: 8px;
    background: {t['bg2']};
}}
QRadioButton::indicator:hover {{
    border-color: {t['fg2']};
}}
QRadioButton::indicator:checked {{
    background: {t['accent']};
    border-color: {t['accent']};
}}
QMenu {{
    background: {t['bg2']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 20px;
    border-radius: 4px;
}}
QMenu::item:selected {{ background: {t['sel']}; }}
QMenu::separator {{
    height: 1px;
    background: {t['border']};
    margin: 4px 8px;
}}
QToolTip {{
    background: {t['bg3']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}}
/* ── Evaluation pill nav ──────────────────────── */
QWidget#pillBar {{
    background: {t['bg2']};
    border-bottom: 1px solid {t['border']};
}}
QWidget#evalTopBar {{
    background: {t['bg2']};
    border-bottom: 1px solid {t['border']};
}}
QPushButton#pillBtn {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    color: {t['fg2']};
    padding: 3px 14px;
    font-size: 12px;
    min-width: 0;
}}
QPushButton#pillBtn:hover {{
    background: {t['bg3']};
    color: {t['fg']};
}}
QPushButton#pillBtn:checked {{
    background: {t['accent']};
    color: #ffffff;
    font-weight: 600;
    border-color: {t['accent']};
}}
QPushButton#innerPillBtn {{
    background: transparent;
    border: 1px solid {t['border']};
    border-radius: 5px;
    color: {t['fg2']};
    padding: 2px 10px;
    font-size: 11px;
    min-width: 0;
}}
QPushButton#innerPillBtn:hover {{
    background: {t['bg3']};
    color: {t['fg']};
}}
QPushButton#innerPillBtn:checked {{
    background: {t['bg3']};
    color: {t['fg']};
    border-color: {t['accent']};
    font-weight: 600;
}}
/* ── Sidebar navigation ───────────────────────── */
QWidget#sidebar {{
    background: {t['bg3']};
    border-right: 1px solid {t['border']};
}}
QPushButton#navBtn {{
    background: transparent;
    border: none;
    border-radius: 8px;
    color: {t['fg2']};
    padding: 0;
    margin: 2px 6px;
}}
QPushButton#navBtn:hover {{
    background: {t['bg3']};
    color: {t['fg']};
}}
QPushButton#navBtn:checked {{
    background: {t['accent_bg']};
    color: {t['accent']};
    border-left: 3px solid {t['accent']};
}}
QPushButton#navBtn QLabel {{
    background: transparent;
    color: {t['fg2']};
}}
QPushButton#navBtn:hover QLabel {{
    color: {t['fg']};
}}
QPushButton#navBtn:checked QLabel {{
    color: {t['accent']};
}}
QWidget#appHeader {{
    background: {t['bg2']};
    border-bottom: 1px solid {t['border']};
}}
QWidget#appHeader QLabel {{
    background: transparent;
}}
QMenuBar {{
    background: {t['bg2']};
    color: {t['fg']};
    border-bottom: 1px solid {t['border']};
    padding: 2px 4px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{
    background: {t['bg3']};
}}
"""


# ══════════════════════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════════════════════

def _parse_param_names_from_mod(mod_path: str) -> dict:
    """
    Re-parse the .mod file to produce correctly-aligned omega/sigma/theta name lists.
    Returns dict with keys: theta_names, omega_names, sigma_names.

    The parser.py can return misaligned omega_names when BLOCK(n) SAME blocks are
    present, because SAME blocks contribute values (positions) but no comments.
    This function reads the block structure directly and builds the correct mapping.
    """
    try:
        text = Path(mod_path).read_text('utf-8', errors='replace')
    except Exception:
        return {}

    def _extract_comment(token: str) -> str:
        m = re.search(r';([^\n]*)', token)
        return m.group(1).strip() if m else ''

    def _parse_block(raw: str, block_name: str):
        """Parse one $THETA/$OMEGA/$SIGMA block, return list of (value, name) pairs."""
        results = []
        # SAME block: repeat the size of the previous block, no new names
        if re.search(r'\bSAME\b', raw, re.IGNORECASE):
            return None  # sentinel meaning "SAME as previous"

        is_block = re.search(r'BLOCK\s*\(\s*(\d+)\s*\)', raw, re.IGNORECASE)
        if is_block:
            dim = int(is_block.group(1))
            # Lower-triangular: dim*(dim+1)/2 elements
            # We only want the diagonal (dim elements) for display
            # Find all numeric tokens with optional comment
            tokens = re.findall(r'([\d\.Ee\+\-]+(?:\s*FIX)?)\s*(?:;([^\n]*))?', raw)
            n_lower = dim*(dim+1)//2
            diag_indices = []  # 0-based positions of diagonal elements in lower triangle
            pos = 0
            for row in range(dim):
                for col in range(row+1):
                    if col == row:
                        diag_indices.append(pos)
                    pos += 1
            for idx, tok_idx in enumerate(diag_indices):
                if tok_idx < len(tokens):
                    nm = tokens[tok_idx][1].strip() if tokens[tok_idx][1] else ''
                    results.append(nm)
                else:
                    results.append('')
            return results

        # Simple diagonal: each value on its own line with optional comment
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith('$') or line.startswith(';'): continue
            if re.match(r'[\d\.Ee\+\-\(]', line):
                nm = _extract_comment(line)
                results.append(nm)
        return results

    def _parse_all_blocks(keyword: str):
        """Collect all $KEYWORD blocks and build a flat name list."""
        pattern = re.compile(
            r'\$' + keyword + r'\b(.*?)(?=\$[A-Z]|\Z)',
            re.DOTALL | re.IGNORECASE)
        names = []
        last_block_names = []
        for m in pattern.finditer(text):
            raw = m.group(1)
            result = _parse_block(raw, keyword)
            if result is None:
                # SAME — repeat last block structure with empty names
                names.extend([''] * len(last_block_names))
            else:
                names.extend(result)
                last_block_names = result
        return names

    return {
        'theta_names': _parse_all_blocks('THETA'),
        'omega_names': _parse_all_blocks('OMEGA'),
        'sigma_names': _parse_all_blocks('SIGMA'),
    }


def _align_param_names(model: dict) -> dict:
    """
    Return a copy of model with omega/sigma/theta names correctly aligned
    to their values. Reads the .mod file if name lists are misaligned.
    """
    mod_path = model.get('path', '')
    if not mod_path or not Path(mod_path).is_file():
        return model

    needs_fix = False
    for block, val_key, name_key in [
        ('theta', 'thetas', 'theta_names'),
        ('omega', 'omegas', 'omega_names'),
        ('sigma', 'sigmas', 'sigma_names'),
    ]:
        vals  = model.get(val_key, [])
        names = model.get(name_key, [])
        if vals and len(names) != len(vals):
            needs_fix = True; break

    if not needs_fix:
        return model

    fresh = _parse_param_names_from_mod(mod_path)
    if not fresh:
        return model

    patched = dict(model)
    for val_key, name_key, fresh_key in [
        ('thetas', 'theta_names', 'theta_names'),
        ('omegas', 'omega_names', 'omega_names'),
        ('sigmas', 'sigma_names', 'sigma_names'),
    ]:
        vals       = model.get(val_key, [])
        fresh_list = fresh.get(fresh_key, [])
        if len(fresh_list) >= len(vals):
            patched[name_key] = fresh_list[:len(vals)]
        elif fresh_list:
            # Pad with empty strings
            patched[name_key] = fresh_list + [''] * (len(vals) - len(fresh_list))
    return patched


def fmt_ofv(v):
    return '' if v is None else f'{v:.3f}'

def fmt_num(v, d=4):
    if v is None: return ''
    return f'{v:.{d}g}' if isinstance(v, float) else str(v)

def fmt_rse(est, se):
    if est is None or se is None or abs(est) < 1e-12: return ''
    return f'{abs(se/est)*100:.1f}%'

def loess(x, y, frac=0.4, n_out=80):
    if not HAS_NP: return None, None
    try:
        x = np.asarray(x, float); y = np.asarray(y, float)
        ok = np.isfinite(x) & np.isfinite(y)
        x, y = x[ok], y[ok]
        if len(x) < 6: return None, None
        order = np.argsort(x); xs, ys = x[order], y[order]
        k = max(5, int(frac * len(xs)))
        xo = np.linspace(xs[0], xs[-1], n_out); yo = np.empty(n_out)
        for i, xi in enumerate(xo):
            d = np.abs(xs - xi); idx = np.argsort(d)[:k]
            h = d[idx[-1]] or 1e-10
            w = np.clip(1-(d[idx]/h)**3, 0, None)**3
            A = np.column_stack([np.ones(k), xs[idx]])
            try:
                W = np.diag(w)
                b = np.linalg.lstsq(W @ A, W @ ys[idx], rcond=None)[0]
                yo[i] = b[0] + b[1]*xi
            except Exception:
                yo[i] = np.average(ys[idx], weights=w+1e-12)
        return xo, yo
    except Exception:
        return None, None


# ── Config I/O ────────────────────────────────────────────────────────────────

def load_meta():
    with _cfg_lock:
        if META_FILE.exists():
            try: return json.loads(META_FILE.read_text('utf-8'))
            except Exception: pass
    return {}

def save_meta(meta):
    with _cfg_lock:
        META_FILE.write_text(json.dumps(meta, indent=2), encoding='utf-8')

def get_meta_entry(meta, path):
    e = meta.get(str(path), {})
    if isinstance(e, str): e = {'comment': e, 'star': False, 'based_on': None}
    return {'comment': e.get('comment',''), 'star': e.get('star', False),
            'based_on': e.get('based_on', None), 'status': e.get('status',''),
            'notes': e.get('notes','')}

def load_settings():
    if SETTINGS_FILE.exists():
        try: return json.loads(SETTINGS_FILE.read_text('utf-8'))
        except Exception: pass
    return {'working_directory': str(HOME), 'psn_path': '', 'nonmem_path': ''}

def save_settings(s):
    SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding='utf-8')

def load_bookmarks():
    if BOOKMARKS_FILE.exists():
        try: return json.loads(BOOKMARKS_FILE.read_text('utf-8'))
        except Exception: pass
    return []

def save_bookmarks(b):
    BOOKMARKS_FILE.write_text(json.dumps(b, indent=2), encoding='utf-8')

def load_runs():
    if RUNS_FILE.exists():
        try: return json.loads(RUNS_FILE.read_text('utf-8'))
        except Exception: pass
    return []

def save_runs(runs):
    RUNS_FILE.write_text(json.dumps(runs, indent=2, default=str), encoding='utf-8')

def get_login_env():
    env = os.environ.copy()
    if not IS_WIN:
        try:
            shell = os.environ.get('SHELL','/bin/sh')
            r = subprocess.run([shell,'-l','-c','echo $PATH'],
                               capture_output=True, text=True, timeout=5)
            if r.stdout.strip(): env['PATH'] = r.stdout.strip()
        except Exception: pass
    return env

def find_tool(name):
    import shutil as sh
    t = sh.which(name)
    if t: return t
    if not IS_WIN:
        try:
            shell = os.environ.get('SHELL','/bin/sh')
            r = subprocess.run([shell,'-l','-c',f'which {name}'],
                               capture_output=True, text=True, timeout=5)
            found = r.stdout.strip()
            if found and Path(found).is_file(): return found
        except Exception: pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Syntax highlighter
# ══════════════════════════════════════════════════════════════════════════════

class NMHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)
        def fmt(color, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:   f.setFontWeight(QFont.Weight.Bold)
            if italic: f.setFontItalic(True)
            return f

        # Record blocks — blue bold
        record_kw = (r'\$(PROB(?:LEM)?|DATA|INPUT|SUBROUTINES|MODEL|ABBR|'
                     r'PK|ERROR|DES|AES|PRED|MIX|INFN|'
                     r'THETA|OMEGA|SIGMA|'
                     r'EST(?:IMATION)?|COV(?:ARIANCE)?|SIM(?:ULATION)?|'
                     r'TABLE|SCATTER|SCAT|'
                     r'MSFI|THETAI|OMEGAI|SIGMAI|THETAP|OMEGAP|SIGMAP|'
                     r'PRIOR|LEVEL|CONTR|'
                     r'SIZE|BIND|ABBR)\b')

        # Fortran/NM control flow — yellow
        flow_kw = (r'\b(IF|THEN|ELSE|ELSEIF|ENDIF|END IF|'
                   r'DO|WHILE|ENDDO|END DO|'
                   r'CALL|RETURN|SUBROUTINE|FUNCTION|'
                   r'COMMON|DIMENSION|DOUBLE PRECISION|REAL|INTEGER|'
                   r'WRITE|READ|FORMAT|CONTINUE|EXIT|CYCLE)\b')

        # NM built-ins — cyan
        nm_builtins = (r'\b(EXP|LOG|SQRT|ABS|INT|MOD|MAX|MIN|SIGN|'
                       r'SIN|COS|TAN|ASIN|ACOS|ATAN|ATAN2|'
                       r'F|R|D|A|S|T|DADT|Y|W|IPRED|PRED|RES|WRES|'
                       r'THETA|ETA|ERR|EPS|DETA|IETA|PHI|LOG10)\b')

        # BLOCK / SAME / FIX keywords — orange
        block_kw = r'\b(BLOCK|SAME|DIAGONAL|FIX(?:ED)?|BAND|CHOLESKY|UNINT|VARIANCE|CORRELATION|SD)\b'

        self._rules = [
            (re.compile(record_kw, re.IGNORECASE),  fmt('#569cd6', bold=True)),
            (re.compile(flow_kw,   re.IGNORECASE),  fmt('#dcdcaa')),
            (re.compile(nm_builtins, re.IGNORECASE),fmt('#9cdcfe')),
            (re.compile(block_kw,  re.IGNORECASE),  fmt('#ce9178')),
            (re.compile(r';[^\n]*'),                 fmt('#6a9955', italic=True)),
            (re.compile(r'\b[-+]?\d*\.?\d+(?:[eEdD][+-]?\d+)?\b'), fmt('#b5cea8')),
            # Quoted strings
            (re.compile(r'"[^"]*"'),                 fmt('#ce9178')),
        ]

    def highlightBlock(self, text):
        for pat, fmt in self._rules:
            for m in pat.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ══════════════════════════════════════════════════════════════════════════════
# Worker threads
# ══════════════════════════════════════════════════════════════════════════════

class ScanWorker(QThread):
    result = pyqtSignal(list)
    error  = pyqtSignal(str)

    def __init__(self, directory, meta):
        super().__init__()
        self.directory = directory
        self.meta = meta

    def run(self):
        if not HAS_PARSER:
            self.error.emit('parser.py not found'); return
        try:
            models = []
            p = Path(self.directory)
            for f in sorted(p.iterdir()):
                if not f.is_file() or f.suffix.lower() not in ('.mod','.ctl'):
                    continue
                m = {k: v for k, v in {
                    'name':f.name,'path':str(f),'stem':f.stem,
                    'has_run':False,'lst_path':'','stale':False,
                    'ofv':None,'minimization_successful':None,'minimization_message':'',
                    'covariance_step':None,'n_individuals':None,'n_observations':None,
                    'n_estimated_params':None,'aic':None,'bic':None,'runtime':None,
                    'estimation_method':'','thetas':[],'omegas':[],'sigmas':[],
                    'theta_ses':[],'omega_ses':[],'sigma_ses':[],
                    'omega_se_matrix':[],'sigma_se_matrix':[],
                    'theta_names':[],'omega_names':[],'sigma_names':[],
                    'theta_units':[],'omega_units':[],'sigma_units':[],
                    'theta_fixed':[],'omega_fixed':[],'sigma_fixed':[],
                    'eta_shrinkage':[],'eps_shrinkage':[],
                    'condition_number':None,'boundary':False,
                    'etabar':[],'etabar_se':[],'etabar_pval':[],
                    'cov_failure_reason':'','correlation_matrix':[],'cor_labels':[],
                    'table_files':[],'table_runno':'','problem':'','data_file':'',
                    'comment':'','star':False,'based_on':None,'status_tag':'',
                    'notes':'','n_thetas':0,'n_omegas':0,
                }.items()}
                mod_mtime = f.stat().st_mtime
                data_mtime = None
                try:
                    content = f.read_text('utf-8', errors='replace')
                    prob = re.search(r'\$PROB(?:LEM)?\s+(.*?)(?:\n|\$)', content, re.IGNORECASE)
                    if prob: m['problem'] = prob.group(1).strip()[:120]
                    dat = re.search(r'\$DATA\s+(\S+)', content, re.IGNORECASE)
                    if dat:
                        m['data_file'] = dat.group(1)
                        dp = p / m['data_file']
                        if dp.is_file(): data_mtime = dp.stat().st_mtime
                    pn = extract_param_names(content)
                    for k in ('theta_names','omega_names','sigma_names',
                              'theta_units','omega_units','sigma_units',
                              'theta_fixed','omega_fixed','sigma_fixed'):
                        m[k] = pn.get(k,[])
                    # Parse parent model from PsN convention: ";; 1. Based on: runXX"
                    based_m = re.search(r'^;;\s*1\.\s*Based on:\s*(\S+)', content, re.MULTILINE | re.IGNORECASE)
                    if based_m:
                        m['based_on'] = based_m.group(1).strip()
                    tf = extract_table_files(content)
                    m['table_files'] = tf['table_files']
                    m['table_runno'] = tf['runno']
                except Exception:
                    pass
                # Find .lst
                lst_same = p/(f.stem+'.lst'); lst_sub = None
                rd = p/f.stem
                if rd.is_dir():
                    cands = list(rd.glob('*.lst'))
                    if cands: lst_sub = cands[0]
                lst_path = lst_same if lst_same.is_file() else lst_sub
                if lst_path:
                    m['has_run'] = True; m['lst_path'] = str(lst_path)
                    try:
                        r = parse_lst(str(lst_path))
                        for k in ('ofv','minimization_successful','minimization_message',
                                  'covariance_step','n_individuals','n_observations',
                                  'n_estimated_params','aic','bic','runtime',
                                  'estimation_method','thetas','omegas','sigmas',
                                  'theta_ses','omega_ses','sigma_ses',
                                  'omega_se_matrix','sigma_se_matrix',
                                  'condition_number','boundary','etabar','etabar_se',
                                  'etabar_pval','cov_failure_reason','eta_shrinkage',
                                  'eps_shrinkage','correlation_matrix','cor_labels'):
                            m[k] = r.get(k)
                        m['n_thetas'] = len(r.get('thetas',[])); m['n_omegas'] = len(r.get('omegas',[]))
                        lst_mtime = lst_path.stat().st_mtime
                        if mod_mtime > lst_mtime+2: m['stale'] = True
                        elif data_mtime and data_mtime > lst_mtime+2: m['stale'] = True
                    except Exception: pass
                meta_e = get_meta_entry(self.meta, f)
                m.update({'comment':meta_e['comment'],'star':meta_e['star'],
                          'based_on':meta_e['based_on'],'status_tag':meta_e['status'],
                          'notes':meta_e['notes']})
                models.append(m)
            self.result.emit(models)
        except Exception as e:
            self.error.emit(str(e))


class RunWorker(QThread):
    line_out = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, cmd, cwd):
        super().__init__()
        self.cmd = cmd; self.cwd = cwd
        self._proc = None; self._env = get_login_env()

    def run(self):
        try:
            kw = dict(shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      cwd=self.cwd, text=True, bufsize=1, env=self._env)
            if not IS_WIN: kw['preexec_fn'] = os.setsid
            else: kw['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
            self._proc = subprocess.Popen(self.cmd, **kw)
            for line in iter(self._proc.stdout.readline, ''):
                self.line_out.emit(line.rstrip())
            self._proc.wait()
            self.finished.emit(self._proc.returncode)
        except Exception as e:
            self.line_out.emit(f'[ERROR] {e}'); self.finished.emit(-1)

    def stop(self):
        if self._proc:
            try:
                if IS_WIN: self._proc.terminate()
                else: os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except Exception: pass


# ══════════════════════════════════════════════════════════════════════════════
# Dark stylesheet
# ══════════════════════════════════════════════════════════════════════════════


def _make_logo_pixmap(size=32):
    """Draw the NM logo using QPainter — no SVG dependency."""
    from PyQt6.QtGui import QPainter, QFont, QFontMetrics
    from PyQt6.QtCore import QRect, QRectF

    # Use device-pixel-ratio-aware pixmap for sharp rendering on HiDPI
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)

    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # Blue rounded rectangle
    radius = size * 0.22
    painter.setBrush(QColor('#4c8aff'))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    # White "NM" text — use a bold system font, slightly off-white for crispness
    painter.setPen(QColor('#eef2ff'))
    font = QFont()
    font.setPixelSize(max(10, int(size * 0.42)))
    font.setWeight(QFont.Weight.Black)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.5)
    painter.setFont(font)
    painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, 'NM')

    painter.end()
    return px


def _make_nav_icon(name: str, size: int = 28, color: str = '#cccccc') -> QPixmap:
    """
    Draw a sidebar nav icon using QPainter — no image files, no emoji, no fonts.
    Works identically on macOS, Windows, Linux at any DPI.
    name: 'models' | 'tree' | 'evaluation' | 'vpc' | 'history' | 'settings'
    color: hex colour string, should match current theme fg
    """
    from PyQt6.QtGui import QPainter, QPainterPath, QPen, QBrush
    from PyQt6.QtCore import QPointF, QRectF

    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    pen = QPen(c); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    s = size

    if name == 'models':
        # Folder: tab on top-left, rectangle body
        sw = max(1.5, s * 0.07); pen.setWidthF(sw); p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        m = s * 0.12  # margin
        tab_w = s * 0.35; tab_h = s * 0.16
        body_t = m + tab_h * 0.8
        # folder tab
        path = QPainterPath()
        path.moveTo(m, body_t)
        path.lineTo(m, m + tab_h)
        path.lineTo(m + tab_w, m + tab_h)
        path.lineTo(m + tab_w + tab_h * 0.6, body_t)
        p.drawPath(path)
        # folder body
        p.drawRoundedRect(QRectF(m, body_t, s - 2*m, s - body_t - m), s*0.06, s*0.06)
        # three horizontal lines inside
        pen2 = QPen(c); pen2.setWidthF(sw * 0.8); pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen2)
        for i, frac in enumerate([0.42, 0.57, 0.72]):
            y = s * frac
            p.drawLine(QPointF(s*0.28, y), QPointF(s*0.82, y))

    elif name == 'tree':
        # Lineage tree: root node top-centre, two children below
        sw = max(1.5, s * 0.07); pen.setWidthF(sw); p.setPen(pen)
        r = s * 0.11  # node radius
        # root
        rx, ry = s*0.5, s*0.18
        p.setBrush(QBrush(c))
        p.drawEllipse(QPointF(rx, ry), r, r)
        # left child
        lx, ly = s*0.25, s*0.75
        p.drawEllipse(QPointF(lx, ly), r, r)
        # right child
        rx2, ry2 = s*0.75, s*0.75
        p.drawEllipse(QPointF(rx2, ry2), r, r)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # trunk down
        mid_y = s * 0.52
        p.drawLine(QPointF(s*0.5, ry+r), QPointF(s*0.5, mid_y))
        # horizontal bar
        p.drawLine(QPointF(lx, mid_y), QPointF(rx2, mid_y))
        # drops to children
        p.drawLine(QPointF(lx,  mid_y), QPointF(lx,  ly-r))
        p.drawLine(QPointF(rx2, mid_y), QPointF(rx2, ry2-r))

    elif name == 'evaluation':
        # Bar chart: three bars of increasing height
        sw = max(1.5, s * 0.07); pen.setWidthF(sw); p.setPen(pen)
        m = s * 0.12; bw = (s - 2*m) / 4.2
        heights = [0.35, 0.55, 0.78]
        baseline = s - m
        for i, h in enumerate(heights):
            x = m + i * (bw + bw*0.4)
            bar_h = s * h
            rect = QRectF(x, baseline - bar_h, bw, bar_h)
            p.setBrush(QBrush(c)); p.drawRoundedRect(rect, bw*0.2, bw*0.2)
        # baseline
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(m*0.6, baseline), QPointF(s-m*0.6, baseline))

    elif name == 'vpc':
        # Scatter plot with observation dots + prediction band
        sw = max(1.2, s * 0.06); pen.setWidthF(sw); p.setPen(pen)
        m = s * 0.13
        # axes
        p.drawLine(QPointF(m, m*0.8), QPointF(m, s-m))
        p.drawLine(QPointF(m, s-m), QPointF(s-m*0.8, s-m))
        # prediction band (filled, semi-transparent)
        band = QPainterPath()
        band.moveTo(m, s - m - s*0.1)
        band.cubicTo(s*0.35, s - m - s*0.35, s*0.55, s - m - s*0.25, s-m*0.9, s - m - s*0.55)
        band.lineTo(s-m*0.9, s - m - s*0.45)
        band.cubicTo(s*0.55, s - m - s*0.15, s*0.35, s - m - s*0.22, m, s - m - s*0.02)
        band.closeSubpath()
        band_color = QColor(color); band_color.setAlphaF(0.25)
        p.setBrush(QBrush(band_color)); p.setPen(Qt.PenStyle.NoPen); p.drawPath(band)
        # median line
        pen2 = QPen(c); pen2.setWidthF(sw*1.3)
        p.setPen(pen2); p.setBrush(Qt.BrushStyle.NoBrush)
        med = QPainterPath()
        med.moveTo(m, s - m - s*0.06)
        med.cubicTo(s*0.35, s - m - s*0.28, s*0.55, s - m - s*0.20, s-m*0.9, s - m - s*0.50)
        p.drawPath(med)
        # scatter dots
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
        for dx, dy in [(0.25,0.52),(0.38,0.35),(0.52,0.42),(0.65,0.28),(0.75,0.20)]:
            p.drawEllipse(QPointF(m + dx*(s-2*m), s-m - dy*(s-2*m)), s*0.04, s*0.04)

    elif name == 'history':
        # Clock face
        sw = max(1.5, s * 0.07); pen.setWidthF(sw); p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy, r = s*0.5, s*0.5, s*0.38
        p.drawEllipse(QPointF(cx, cy), r, r)
        # hour hand (pointing ~10 o'clock)
        import math
        h_angle = math.radians(-60); h_len = r * 0.55
        p.drawLine(QPointF(cx, cy),
                   QPointF(cx + h_len*math.sin(h_angle), cy - h_len*math.cos(h_angle)))
        # minute hand (pointing ~12)
        m_angle = math.radians(0); m_len = r * 0.75
        p.drawLine(QPointF(cx, cy),
                   QPointF(cx + m_len*math.sin(m_angle), cy - m_len*math.cos(m_angle)))
        # centre dot
        p.setBrush(QBrush(c)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), s*0.05, s*0.05)

    elif name == 'settings':
        # Gear: circle with teeth
        import math
        sw = max(1.2, s * 0.06); pen.setWidthF(sw); p.setPen(pen)
        cx, cy = s*0.5, s*0.5
        outer_r = s * 0.38; inner_r = s * 0.24; hole_r = s * 0.12
        teeth = 8; tooth_h = s * 0.09
        path = QPainterPath()
        for i in range(teeth * 2):
            angle = math.radians(i * 180 / teeth)
            r = outer_r if i % 2 == 0 else outer_r - tooth_h
            x = cx + r * math.cos(angle); y = cy + r * math.sin(angle)
            if i == 0: path.moveTo(x, y)
            else: path.lineTo(x, y)
        path.closeSubpath()
        p.setBrush(QBrush(c)); p.setPen(Qt.PenStyle.NoPen); p.drawPath(path)
        # inner cutout (draw in bg colour — transparent workaround)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.drawEllipse(QPointF(cx, cy), inner_r, inner_r)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        # centre hole
        p.setBrush(QBrush(c)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), hole_r, hole_r)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.drawEllipse(QPointF(cx, cy), hole_r * 0.5, hole_r * 0.5)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

    elif name == 'uncertainty':
        # Bell curve with confidence interval whiskers
        import math
        sw = max(1.5, s * 0.07); pen.setWidthF(sw); p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        m = s * 0.12
        cx, cy = s * 0.5, s * 0.65
        # Bell curve via bezier
        path = QPainterPath()
        path.moveTo(m, cy)
        path.cubicTo(s*0.25, cy, s*0.32, s*0.18, cx, s*0.18)
        path.cubicTo(s*0.68, s*0.18, s*0.75, cy, s-m, cy)
        p.drawPath(path)
        # Baseline
        p.drawLine(QPointF(m - s*0.02, cy + s*0.12), QPointF(s - m + s*0.02, cy + s*0.12))
        # Whiskers for CI
        whisker_y_top = cy - s*0.05
        whisker_y_bot = cy + s*0.12
        # Left whisker
        left_x = s * 0.28
        p.drawLine(QPointF(left_x, whisker_y_top), QPointF(left_x, whisker_y_bot))
        p.drawLine(QPointF(left_x - s*0.04, whisker_y_top), QPointF(left_x + s*0.04, whisker_y_top))
        # Right whisker
        right_x = s * 0.72
        p.drawLine(QPointF(right_x, whisker_y_top), QPointF(right_x, whisker_y_bot))
        p.drawLine(QPointF(right_x - s*0.04, whisker_y_top), QPointF(right_x + s*0.04, whisker_y_top))
        # Centre dot (mean)
        p.setBrush(QBrush(c)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy + s*0.12), s*0.04, s*0.04)

    p.end()
    return px


DARK_SS = build_stylesheet('dark')   # kept as alias; MainWindow uses build_stylesheet directly


# ══════════════════════════════════════════════════════════════════════════════
# Parameter table widget
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Run report generator
# ══════════════════════════════════════════════════════════════════════════════

def generate_html_report(model: dict) -> str:
    """Generate a self-contained HTML run report for a model."""
    from datetime import datetime as _dt
    stem = model.get('stem','')
    now  = _dt.now().strftime('%Y-%m-%d %H:%M')

    # ── CSS ──────────────────────────────────────────────────────────────────
    css = """
    *{box-sizing:border-box;}
    body{font-family:-apple-system,Segoe UI,Arial,sans-serif;font-size:13px;
         color:#1a1a2e;background:#f4f4f8;margin:0;padding:24px 32px;}
    h1{font-size:22px;font-weight:800;margin:0 0 2px;letter-spacing:-.5px;}
    h2{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
       color:#4c8aff;margin:28px 0 10px;padding-left:12px;
       border-left:3px solid #4c8aff;}
    .header{background:#fff;border:1px solid #e0e0ea;border-radius:10px;
            padding:20px 24px;margin-bottom:24px;
            display:flex;align-items:center;gap:20px;
            box-shadow:0 1px 4px rgba(0,0,0,.06);}
    .logo{background:#4c8aff;color:#fff;font-weight:900;font-size:17px;
          width:42px;height:42px;border-radius:10px;
          display:flex;align-items:center;justify-content:center;flex-shrink:0;}
    .meta{color:#7a7d9a;font-size:12px;margin-top:3px;}
    .card{background:#fff;border:1px solid #e0e0ea;border-radius:10px;
          padding:18px 22px;margin-bottom:16px;
          box-shadow:0 1px 4px rgba(0,0,0,.04);}
    .card-scroll{overflow-x:auto;}
    table{border-collapse:collapse;font-size:12px;min-width:100%;}
    thead th{background:#f0f0f8;font-weight:700;text-align:left;padding:7px 12px;
             border-bottom:2px solid #dde;color:#5a5a70;text-transform:uppercase;
             font-size:10.5px;letter-spacing:.4px;white-space:nowrap;}
    td{padding:6px 12px;border-bottom:1px solid #eeeef4;white-space:nowrap;}
    tr:last-child td{border-bottom:none;}
    tr:nth-child(even) td{background:#fafafd;}
    .block-sep td,.block-sep th{border-top:2px solid #4c8aff;padding-top:8px;
                                 font-weight:700;color:#4c8aff;font-size:10px;
                                 text-transform:uppercase;letter-spacing:.5px;}
    .good{color:#16a34a;font-weight:700;}
    .bad{color:#dc2626;font-weight:700;}
    .warn{color:#d97706;font-weight:700;}
    .fix{color:#b0b0c0;font-style:italic;font-size:11px;}
    .num{text-align:right;font-variant-numeric:tabular-nums;font-family:
         ui-monospace,Menlo,Consolas,monospace;}
    .summary-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;}
    .summary-item{background:#f8f8fc;border:1px solid #e8e8f0;border-radius:8px;padding:12px 14px;}
    .summary-label{font-size:10px;color:#9090a0;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;}
    .summary-value{font-size:17px;font-weight:800;letter-spacing:-.3px;}
    .sticky-col{position:sticky;left:0;background:#f0f0f8;z-index:1;font-weight:700;}
    @media print{
      body{background:#fff;padding:16px;}
      .header{box-shadow:none;border:1px solid #ccc;}
      .card{box-shadow:none;page-break-inside:avoid;}
      h2{page-break-after:avoid;}
    }
    """

    # ── Summary values ────────────────────────────────────────────────────────
    ofv   = model.get('ofv')
    status= model.get('minimization_message','')
    cov   = model.get('covariance_step')
    cn    = model.get('condition_number')
    meth  = model.get('estimation_method','')
    rt    = model.get('runtime')
    nind  = model.get('n_individuals')
    nobs  = model.get('n_observations')
    npar  = model.get('n_estimated_params')
    aic   = model.get('aic')

    def _cls(v, good_fn, warn_fn=None):
        if v is None: return ''
        if good_fn(v): return 'good'
        if warn_fn and warn_fn(v): return 'warn'
        return 'bad'

    status_cls = 'good' if ('SUCCESSFUL' in status or 'COMPLETED' in status) else 'bad'
    cov_str    = ('OK' if cov else 'FAILED') if cov is not None else '—'
    cov_cls    = 'good' if cov else ('bad' if cov is False else '')
    cn_str     = f'{cn:.1f}' if cn else '—'
    cn_cls     = 'warn' if cn and cn > 1000 else ('good' if cn else '')
    rt_str     = f'{rt:.1f} s' if rt else '—'

    summary_items = [
        ('OFV',                f'{ofv:.4f}' if ofv is not None else '—', ''),
        ('AIC',                f'{aic:.2f}' if aic is not None else '—', ''),
        ('Status',             status[:30] or '—', status_cls),
        ('Covariance',         cov_str, cov_cls),
        ('Condition number',   cn_str, cn_cls),
        ('Method',             meth or '—', ''),
        ('Individuals',        str(nind) if nind else '—', ''),
        ('Observations',       str(nobs) if nobs else '—', ''),
        ('Est. parameters',    str(npar) if npar else '—', ''),
        ('Runtime',            rt_str, ''),
    ]
    summary_html = '<div class="summary-grid">' + ''.join(
        f'<div class="summary-item"><div class="summary-label">{lbl}</div>'
        f'<div class="summary-value {cls}">{val}</div></div>'
        for lbl,val,cls in summary_items) + '</div>'

    # ── Parameter table ───────────────────────────────────────────────────────
    blocks = [
        ('THETA', model.get('thetas',[]),  model.get('theta_ses',[]),
         model.get('theta_names',[]), model.get('theta_units',[]), model.get('theta_fixed',[])),
        ('OMEGA', model.get('omegas',[]),  model.get('omega_ses',[]),
         model.get('omega_names',[]), model.get('omega_units',[]), model.get('omega_fixed',[])),
        ('SIGMA', model.get('sigmas',[]),  model.get('sigma_ses',[]),
         model.get('sigma_names',[]), model.get('sigma_units',[]), model.get('sigma_fixed',[])),
    ]
    param_rows = ''
    current_block = None
    for block, ests, ses, names, units, fixed in blocks:
        if ests:
            if block != current_block:
                current_block = block
                param_rows += (f'<tr class="block-sep">'
                               f'<td colspan="6">{block}</td></tr>')
            for i, est in enumerate(ests):
                se   = ses[i]   if i < len(ses)   else None
                nm   = names[i] if i < len(names) else ''
                un   = units[i] if i < len(units) else ''
                fx   = fixed[i] if i < len(fixed) else False
                rse  = f'{abs(se/est)*100:.1f}%' if se is not None and est and abs(est)>1e-12 else ('...' if se is None else '—')
                lbl  = f'{block}({i+1})'
                fix_badge = ' <span class="fix">FIX</span>' if fx else ''
                rse_cls = ''
                if se is not None and est and abs(est)>1e-12:
                    pct = abs(se/est)*100
                    rse_cls = 'good' if pct<25 else ('warn' if pct<50 else 'bad')
                param_rows += (
                    f'<tr><td>{lbl}{fix_badge}</td><td>{nm}</td>'
                    f'<td class="num">{fmt_num(est)}</td>'
                    f'<td class="num">{fmt_num(se) if se is not None else "..."}</td>'
                    f'<td class="num {rse_cls}">{rse}</td>'
                    f'<td class="num">{un}</td></tr>')

    param_html = f'''<div class="card-scroll">
    <table><thead><tr>
    <th>Parameter</th><th>Name</th><th>Estimate</th><th>SE</th><th>RSE%</th><th>Units</th>
    </tr></thead><tbody>{param_rows}</tbody></table></div>'''

    # ── Correlation matrix ────────────────────────────────────────────────────
    cor_mat  = model.get('correlation_matrix',[])
    cor_lbls = model.get('cor_labels',[])
    cor_html = ''
    if cor_mat and cor_lbls:
        hdr = ''.join(f'<th>{l}</th>' for l in cor_lbls)
        rows_h = ''
        for i, row in enumerate(cor_mat):
            lbl = cor_lbls[i] if i < len(cor_lbls) else str(i)
            cells = ''
            for j, v in enumerate(row):
                if v is None: cells += '<td></td>'
                else:
                    cls = ''
                    if i != j:
                        a = abs(v)
                        cls = 'bad' if a>0.9 else ('warn' if a>0.7 else '')
                    cells += f'<td class="num {cls}">{v:.3f}</td>'
            rows_h += f'<tr><th class="sticky-col">{lbl}</th>{cells}</tr>'
        cor_html = (f'<div class="card-scroll"><table><thead>'
                    f'<tr><th class="sticky-col"></th>{hdr}</tr></thead>'
                    f'<tbody>{rows_h}</tbody></table></div>')
    else:
        cor_html = '<p style="color:#9090a0;margin:0;">Not available (requires successful covariance step)</p>'

    # ── ETABAR ────────────────────────────────────────────────────────────────
    etabar  = model.get('etabar',[])
    etase   = model.get('etabar_se',[])
    etapval = model.get('etabar_pval',[])
    eta_html = ''
    if etabar:
        eta_rows = ''
        for i, eb in enumerate(etabar):
            se_  = etase[i]   if i < len(etase)   else None
            pv   = etapval[i] if i < len(etapval) else None
            pv_cls = 'bad' if pv is not None and pv < 0.05 else ''
            eta_rows += (f'<tr><td>ETA({i+1})</td>'
                         f'<td class="num">{eb:.4f}</td>'
                         f'<td class="num">{fmt_num(se_) if se_ else "—"}</td>'
                         f'<td class="num {pv_cls}">{f"{pv:.4f}" if pv is not None else "—"}</td></tr>')
        eta_html = f'''<table><thead><tr>
        <th>ETA</th><th>ETABAR</th><th>SE</th><th>P-value</th>
        </tr></thead><tbody>{eta_rows}</tbody></table>'''
    else:
        eta_html = '<p style="color:#9090a0;">Not available</p>'

    # ── Shrinkage ─────────────────────────────────────────────────────────────
    eta_shr = model.get('eta_shrinkage',[])
    eps_shr = model.get('eps_shrinkage',[])
    shr_html = ''
    if eta_shr or eps_shr:
        shr_rows = ''
        for i, v in enumerate(eta_shr):
            cls = 'bad' if v > 30 else ('warn' if v > 20 else 'good')
            shr_rows += f'<tr><td>ETA({i+1})</td><td class="num {cls}">{v:.1f}%</td></tr>'
        for i, v in enumerate(eps_shr):
            cls = 'bad' if v > 30 else ('warn' if v > 20 else 'good')
            shr_rows += f'<tr><td>EPS({i+1})</td><td class="num {cls}">{v:.1f}%</td></tr>'
        shr_html = f'<table><thead><tr><th>Parameter</th><th>Shrinkage (SD%)</th></tr></thead><tbody>{shr_rows}</tbody></table>'
    else:
        shr_html = '<p style="color:#9090a0;">Not available</p>'

    # ── Assemble ──────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8">
<title>NMGUI Report — {stem}</title>
<style>{css}</style>
</head><body>
<div class="header">
  <div class="logo">NM</div>
  <div>
    <h1>{stem}</h1>
    <div class="meta">{model.get('problem','')}</div>
    <div class="meta">Generated by NMGUI v{APP_VERSION} · {now}</div>
  </div>
</div>
<h2>Summary</h2><div class="card">{summary_html}</div>
<h2>Parameter Estimates</h2><div class="card">{param_html}</div>
<h2>Correlation Matrix</h2><div class="card">{cor_html}</div>
<h2>ETABAR</h2><div class="card">{eta_html}</div>
<h2>Shrinkage</h2><div class="card">{shr_html}</div>
</body></html>"""
    return html


def launch_rstudio(directory: str, rstudio_path: str = '') -> str:
    """Launch RStudio with directory as project. Returns error string or ''."""
    import shutil as _sh
    # Find RStudio
    rs = None
    if rstudio_path and Path(rstudio_path).exists():
        rs = rstudio_path
    if not rs:
        rs = _sh.which('rstudio') or _sh.which('RStudio')
    if not rs and IS_MAC:
        for cand in ['/Applications/RStudio.app',
                     str(HOME/'Applications/RStudio.app')]:
            if Path(cand).exists(): rs = cand; break
    if not rs and IS_WIN:
        import glob as _gl
        for pat in [r'%LOCALAPPDATA%\Programs\Posit\RStudio\rstudio.exe',
                    r'%PROGRAMFILES%\Posit\RStudio\rstudio.exe',
                    r'%PROGRAMFILES%\RStudio\bin\rstudio.exe']:
            hits = _gl.glob(os.path.expandvars(pat))
            if hits: rs = hits[0]; break
    if not rs:
        return 'RStudio not found. Set the path in Settings → RStudio path.'
    # Create .Rproj if needed
    rproj_files = list(Path(directory).glob('*.Rproj'))
    if rproj_files:
        rproj = str(rproj_files[0])
    else:
        name  = Path(directory).name
        rproj = str(Path(directory) / (name + '.Rproj'))
        Path(rproj).write_text(
            'Version: 1.0\n\nRestoreWorkspace: Default\n'
            'SaveWorkspace: Default\nAlwaysSaveHistory: Default\n')
    try:
        if IS_MAC:
            subprocess.Popen(['open', '-a', rs, rproj])
        else:
            subprocess.Popen([rs, rproj])
        return ''
    except Exception as e:
        return str(e)


class ParameterTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = None
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)
        # Toolbar
        toolbar = QWidget(); toolbar.setFixedHeight(34)
        tl = QHBoxLayout(toolbar); tl.setContentsMargins(4,4,4,4); tl.setSpacing(6)
        tl.addStretch()
        self.open_report_btn = QPushButton('Open Report')
        self.open_report_btn.setToolTip('Generate run report and open in browser')
        self.open_report_btn.setFixedHeight(26); self.open_report_btn.setEnabled(False)
        self.save_report_btn = QPushButton('Save Report…')
        self.save_report_btn.setToolTip('Save run report as HTML file')
        self.save_report_btn.setFixedHeight(26); self.save_report_btn.setEnabled(False)
        self.csv_btn = QPushButton('Export CSV')
        self.csv_btn.setToolTip('Export parameter table to CSV')
        self.csv_btn.setFixedHeight(26); self.csv_btn.setEnabled(False)
        self.open_report_btn.clicked.connect(self._open_report)
        self.save_report_btn.clicked.connect(self._save_report)
        self.csv_btn.clicked.connect(self._export_csv)
        tl.addWidget(self.open_report_btn); tl.addWidget(self.save_report_btn)
        tl.addWidget(self.csv_btn)
        v.addWidget(toolbar)
        self.table = QTableWidget(0,6)
        self.table.setHorizontalHeaderLabels(['Param','Name','Estimate','SE','RSE%','Units'])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        # Sensible initial widths — all freely draggable
        hh.resizeSection(0, 90)   # Param
        hh.resizeSection(1, 180)  # Name — wide but draggable
        hh.resizeSection(2, 90)   # Estimate
        hh.resizeSection(3, 75)   # SE
        hh.resizeSection(4, 65)   # RSE%
        hh.resizeSection(5, 60)   # Units
        hh.setStretchLastSection(False)
        hh.setMinimumSectionSize(40)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        v.addWidget(self.table)
        self.shr_label = QLabel('')
        self.shr_label.setStyleSheet(f'color:{C_FG2};font-size:11px;padding:2px;')
        v.addWidget(self.shr_label)

    def _open_report(self):
        if not self._model: return
        import tempfile, webbrowser
        html = generate_html_report(_align_param_names(self._model))
        tmp = tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8')
        tmp.write(html); tmp.flush(); tmp_name = tmp.name; tmp.close()
        webbrowser.open(f'file://{tmp_name}')
        # Schedule cleanup after browser has had time to read the file
        QTimer.singleShot(30000, lambda: Path(tmp_name).unlink(missing_ok=True))

    def _save_report(self):
        if not self._model: return
        stem = self._model.get('stem','report')
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Save report', str(HOME / f'{stem}_report.html'),
            'HTML files (*.html)')
        if not dst: return
        Path(dst).write_text(generate_html_report(_align_param_names(self._model)), encoding='utf-8')
        if QMessageBox.question(self,'Saved',f'Report saved.\nOpen in browser?',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            import webbrowser; webbrowser.open(f'file://{dst}')

    def _export_csv(self):
        if not self._model: return
        stem = self._model.get('stem','model')
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Export parameters', str(HOME / f'{stem}_params.csv'),
            'CSV files (*.csv)')
        if not dst: return
        import csv as _csv
        rows = []
        for block, ests, ses, names, units, fixed in [
            ('THETA', self._model.get('thetas',[]), self._model.get('theta_ses',[]),
             self._model.get('theta_names',[]), self._model.get('theta_units',[]),
             self._model.get('theta_fixed',[])),
            ('OMEGA', self._model.get('omegas',[]), self._model.get('omega_ses',[]),
             self._model.get('omega_names',[]), self._model.get('omega_units',[]),
             self._model.get('omega_fixed',[])),
            ('SIGMA', self._model.get('sigmas',[]), self._model.get('sigma_ses',[]),
             self._model.get('sigma_names',[]), self._model.get('sigma_units',[]),
             self._model.get('sigma_fixed',[])),
        ]:
            for i, est in enumerate(ests):
                se  = ses[i]   if i < len(ses)   else None
                nm  = names[i] if i < len(names) else ''
                un  = units[i] if i < len(units) else ''
                fx  = fixed[i] if i < len(fixed) else False
                rse = f'{abs(se/est)*100:.2f}' if se and est and abs(est)>1e-12 else ''
                rows.append([f'{block}({i+1})', nm,
                              fmt_num(est), fmt_num(se) if se is not None else '',
                              rse, un, 'FIXED' if fx else ''])
        with open(dst, 'w', newline='', encoding='utf-8') as f:
            w = _csv.writer(f)
            w.writerow(['Parameter','Name','Estimate','SE','RSE_pct','Units','Fixed'])
            w.writerows(rows)
        self.parent().parent().status_msg.emit(f'Parameters exported: {Path(dst).name}') if hasattr(self,'parent') else None

    def load(self, model):
        self._model = model if model.get('has_run') else None
        has = self._model is not None
        self.open_report_btn.setEnabled(has)
        self.save_report_btn.setEnabled(has)
        self.csv_btn.setEnabled(has)
        self.table.setRowCount(0)
        blocks = [
            ('THETA', model.get('thetas',[]), model.get('theta_ses',[]),
             model.get('theta_names',[]), model.get('theta_units',[]), model.get('theta_fixed',[])),
            ('OMEGA', model.get('omegas',[]), model.get('omega_ses',[]),
             model.get('omega_names',[]), model.get('omega_units',[]), model.get('omega_fixed',[])),
            ('SIGMA', model.get('sigmas',[]), model.get('sigma_ses',[]),
             model.get('sigma_names',[]), model.get('sigma_units',[]), model.get('sigma_fixed',[])),
        ]
        rows = []
        for block, ests, ses, names, units, fixed in blocks:
            for i, est in enumerate(ests):
                se   = ses[i] if i < len(ses) else None
                nm   = names[i] if i < len(names) else ''
                un   = units[i] if i < len(units) else ''
                fx   = fixed[i] if i < len(fixed) else False
                rows.append((f'{block}({i+1})', nm, fmt_num(est), fmt_num(se) if se is not None else '...', fmt_rse(est,se), un, fx))
        self.table.setRowCount(len(rows))
        R = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        L = Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter
        grey = QBrush(QColor(C_FG2))
        for row, (lbl,nm,est,se,rse,un,fx) in enumerate(rows):
            for col, (txt, align) in enumerate([(lbl,L),(nm,L),(est,R),(se,R),(rse,R),(un,L)]):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(align)
                if fx: item.setForeground(grey); item.setToolTip('FIXED')
                self.table.setItem(row, col, item)
        # Shrinkage
        shr = model.get('eta_shrinkage',[])
        if shr:
            self.shr_label.setText('ETA shrinkage: ' + '  '.join(f'ETA{i+1}: {v:.1f}%' for i,v in enumerate(shr)))
        else:
            self.shr_label.setText('')


# ══════════════════════════════════════════════════════════════════════════════
# Model table
# ══════════════════════════════════════════════════════════════════════════════

COLS = ['*','Name','OFV','dOFV','Status','COV','CN','Method','nInd','nObs','nPar','AIC','Runtime']
(COL_STAR, COL_NAME, COL_OFV, COL_DOFV, COL_STATUS,
 COL_COV, COL_CN, COL_METHOD, COL_NIND, COL_NOBS, COL_NPAR, COL_AIC, COL_RT) = range(13)


class ModelTableModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._models = []; self._best_ofv = None; self._ref_path = None; self._ref_ofv = None

    def load(self, models):
        self.beginResetModel(); self._models = models
        ofvs = [m['ofv'] for m in models if m.get('ofv') is not None]
        self._best_ofv = min(ofvs) if ofvs else None
        # Refresh ref OFV in case model was re-run
        if self._ref_path:
            ref = next((m for m in models if m['path'] == self._ref_path), None)
            self._ref_ofv = ref['ofv'] if ref and ref.get('ofv') is not None else None
        self.endResetModel()

    def set_reference(self, model_path):
        """Set reference model for dOFV calculation. Pass None to revert to best model."""
        self._ref_path = model_path
        if model_path:
            ref = next((m for m in self._models if m['path'] == model_path), None)
            self._ref_ofv = ref['ofv'] if ref and ref.get('ofv') is not None else None
        else:
            self._ref_ofv = None
        self.beginResetModel(); self.endResetModel()

    def _dofv_base(self):
        """Return (ofv_base, is_reference) for dOFV calculation."""
        if self._ref_path and self._ref_ofv is not None:
            return self._ref_ofv, True
        return self._best_ofv, False

    def rowCount(self, _=QModelIndex()): return len(self._models)
    def columnCount(self, _=QModelIndex()): return len(COLS)

    def headerData(self, s, o, role=Qt.ItemDataRole.DisplayRole):
        if o == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLS[s]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        m = self._models[index.row()]; col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_STAR:   return '*' if m.get('star') else ''
            if col == COL_NAME:
                s = m['stem']
                if m.get('stale'): s += ' !'
                if m.get('status_tag'): s += f" [{m['status_tag']}]"
                if m['path'] == self._ref_path: s += ' [REF]'
                return s
            if col == COL_OFV:  return fmt_ofv(m.get('ofv'))
            if col == COL_DOFV:
                ofv = m.get('ofv')
                base, is_ref = self._dofv_base()
                if ofv is None or base is None: return ''
                if is_ref and m['path'] == self._ref_path: return 'REF'
                if not is_ref and abs(ofv - base) < 0.001: return '—'
                d = ofv - base
                return f'+{d:.3f}' if d > 0 else f'{d:.3f}'
            if col == COL_STATUS: return (m.get('minimization_message') or '')[:35]
            if col == COL_COV:
                cv = m.get('covariance_step')
                return '' if cv is None else ('OK' if cv else '--')
            if col == COL_CN:
                cn = m.get('condition_number')
                if cn is None: return ''
                if cn >= 10000: return f'{cn:.2e}'
                if cn >= 1000:  return f'{cn:.0f}'
                return f'{cn:.1f}'
            if col == COL_METHOD: return m.get('estimation_method','')
            if col == COL_NIND:  return str(m['n_individuals']) if m.get('n_individuals') else ''
            if col == COL_NOBS:  return str(m['n_observations']) if m.get('n_observations') else ''
            if col == COL_NPAR:  return str(m['n_estimated_params']) if m.get('n_estimated_params') else ''
            if col == COL_AIC:   return fmt_ofv(m.get('aic'))
            if col == COL_RT:
                rt = m.get('runtime')
                if rt is None: return ''
                return f'{rt:.0f}s' if rt < 3600 else f'{rt/3600:.1f}h'
        if role == Qt.ItemDataRole.ForegroundRole:
            if col == COL_STAR: return QBrush(QColor(C_STAR))
            if col == COL_STATUS:
                msg = m.get('minimization_message') or ''
                if 'SUCCESSFUL' in msg or 'COMPLETED' in msg: return QBrush(QColor(C_GREEN))
                if m.get('minimization_successful') is False: return QBrush(QColor(C_RED))
                if m.get('boundary'): return QBrush(QColor(C_ORANGE))
            if col == COL_COV:
                cv = m.get('covariance_step')
                if cv is True:  return QBrush(QColor(C_GREEN))
                if cv is False: return QBrush(QColor(C_RED))
            if col == COL_CN:
                cn = m.get('condition_number')
                if cn is None: return QBrush(QColor(C_FG2))
                if cn > 1000:  return QBrush(QColor(C_ORANGE))
                return None
            if col == COL_DOFV:
                ofv = m.get('ofv')
                base, is_ref = self._dofv_base()
                if ofv is not None and base is not None:
                    if is_ref and m['path'] == self._ref_path:
                        return QBrush(QColor(C_BLUE))
                    if not is_ref and abs(ofv - base) < 0.001:
                        return QBrush(QColor(C_GREEN))
            if col == COL_NAME and m.get('stale'): return QBrush(QColor(C_STALE))
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_NAME:
                tip = f"Path: {m['path']}"
                if m.get('problem'): tip += f"\n{m['problem']}"
                if m.get('comment'): tip += f"\n{m['comment']}"
                if m.get('based_on'): tip += f"\nBased on: {m['based_on']}"
                return tip
            if col == COL_STATUS and m.get('cov_failure_reason'): return m['cov_failure_reason']
            if col == COL_CN:
                cn = m.get('condition_number')
                if cn is None:
                    return 'Condition number not available.\nRequires successful $COV step with PRINT=E, or NONMEM versions that output it directly.'
                if cn > 1000:
                    return f'Condition number: {cn:.1f}\nWarning: CN > 1000 may indicate near-collinearity in the parameter space.'
                return f'Condition number: {cn:.1f}'
        return None

    def model_at(self, row): return self._models[row] if 0 <= row < len(self._models) else None


# ══════════════════════════════════════════════════════════════════════════════
# Models Tab
# ══════════════════════════════════════════════════════════════════════════════

class DuplicateDialog(QDialog):
    def __init__(self, stem, parent=None):
        super().__init__(parent); self.setWindowTitle('Duplicate Model'); self.setFixedWidth(360)
        f = QFormLayout(self)
        self.name_edit  = QLineEdit(stem+'_2')
        self.use_est    = QCheckBox('Inject final estimates from .lst')
        self.jitter_sb  = QDoubleSpinBox(); self.jitter_sb.setRange(0,1); self.jitter_sb.setSingleStep(0.05); self.jitter_sb.setDecimals(2)
        f.addRow('New filename:', self.name_edit)
        f.addRow('', self.use_est)
        f.addRow('Jitter ±fraction:', self.jitter_sb)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        f.addRow(btns)


class _ModelsTable(QTableWidget):
    """QTableWidget subclass — overrides contextMenuEvent so right-click
    is guaranteed to work via C++ virtual dispatch on all platforms."""
    right_clicked = pyqtSignal(int)   # emits row index in content coordinates

    def contextMenuEvent(self, event):
        # event.pos() is in viewport coordinates for QAbstractScrollArea subclasses.
        # QTableWidget.rowAt() accounts for the scroll offset internally.
        row = self.rowAt(event.pos().y())
        if row >= 0:
            self.right_clicked.emit(row)
        event.accept()   # prevent propagation


class ModelsTab(QWidget):
    model_selected = pyqtSignal(dict)
    status_msg     = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._directory = load_settings().get('working_directory', str(HOME))
        self._meta = load_meta(); self._scan_worker = None
        self._run_worker = None; self._current_model = None
        self._ref_model_path = None   # user-selected reference for dOFV
        self._table_model = ModelTableModel()
        self._all_models  = []
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self); v.setContentsMargins(4,4,4,4); v.setSpacing(4)
        # Dir bar
        top = QHBoxLayout()
        self.dir_edit = QLineEdit(self._directory); self.dir_edit.returnPressed.connect(self._scan)
        browse = QPushButton('Browse…'); browse.clicked.connect(self._browse)
        scan   = QPushButton('Rescan'); scan.clicked.connect(self._scan)
        top.addWidget(QLabel('Directory:')); top.addWidget(self.dir_edit,1)
        top.addWidget(browse); top.addWidget(scan)
        v.addLayout(top)
        # Bookmark bar
        bm = QHBoxLayout()
        self.bm_combo = QComboBox(); self.bm_combo.setMinimumWidth(200)
        self.bm_combo.activated.connect(self._go_bookmark)
        add_bm = QPushButton('+ Bookmark'); add_bm.clicked.connect(self._add_bookmark)
        bm.addWidget(QLabel('Bookmarks:')); bm.addWidget(self.bm_combo); bm.addWidget(add_bm); bm.addStretch()
        v.addLayout(bm); self._refresh_bookmarks()
        # Splitter
        spl = QSplitter(Qt.Orientation.Horizontal)
        # Left: table
        left = QWidget(); lv = QVBoxLayout(left); lv.setContentsMargins(0,0,0,0)
        left.setMinimumWidth(320)
        self.table = _ModelsTable()
        self.table.setColumnCount(len(COLS)); self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_CN, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        # Column header tooltips
        _col_tips = {
            COL_STAR:   '*  Starred / flagged model',
            COL_NAME:   'Model name (stem of .mod file)',
            COL_OFV:    'Objective Function Value',
            COL_DOFV:   'ΔOFV relative to the best model in this directory',
            COL_STATUS: 'Minimization status message',
            COL_COV:    'Covariance step  (✓ successful  ✗ failed)',
            COL_CN:     'Condition number — ratio of largest to smallest eigenvalue '
                        'of the correlation matrix.\nRequires $COV with PRINT=E or '
                        'a NONMEM version that outputs it directly.\nValues > 1000 '
                        'may indicate near-collinearity.',
            COL_METHOD: 'Estimation method  (FO, FOCE, FOCE-I, SAEM, SAEM→IMP, BAYES…)',
            COL_NIND:   'Number of individuals',
            COL_NOBS:   'Number of observation records (MDV=0 rows)',
            COL_NPAR:   'Number of estimated parameters  (non-fixed THETAs + OMEGA/SIGMA elements)',
            COL_AIC:    'Akaike Information Criterion  =  OFV + 2k',
            COL_RT:     'Estimation runtime (seconds or hours)',
        }
        for col, tip in _col_tips.items():
            item = self.table.horizontalHeaderItem(col)
            if item: item.setToolTip(tip)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setShowGrid(False)
        self.table.itemSelectionChanged.connect(self._on_select)
        # Right-click handled by _ModelsTable.contextMenuEvent via C++ virtual dispatch
        self.table.right_clicked.connect(self._on_right_click)
        # Keyboard navigation only — no viewport filter needed
        self.table.installEventFilter(self)
        lv.addWidget(self.table); spl.addWidget(left)
        # Prevent right panel from expanding at expense of model list

        # Right: detail panel with pill navigation
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(0,0,0,0); rv.setSpacing(0)
        # Ignored = splitter ignores this widget's size hint completely.
        # Without this, loading content into the parameter table changes the size hint
        # and Qt silently adjusts the splitter — squashing the model list.
        right.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)

        # Pill strip
        detail_pill_bar = QWidget(); detail_pill_bar.setObjectName('pillBar')
        detail_pill_bar.setFixedHeight(38)
        dpl = QHBoxLayout(detail_pill_bar); dpl.setContentsMargins(8,5,8,5); dpl.setSpacing(4)
        self._detail_btns = []
        for i, lbl in enumerate(['Parameters','Editor','Run','Info','Output']):
            btn = QPushButton(lbl); btn.setObjectName('pillBtn')
            btn.setCheckable(True); btn.setFixedHeight(26)
            btn.clicked.connect(lambda _, n=i: self._detail_switch(n))
            dpl.addWidget(btn); self._detail_btns.append(btn)
        dpl.addStretch()
        rv.addWidget(detail_pill_bar)

        sep2 = QWidget(); sep2.setFixedHeight(1); sep2.setStyleSheet(f'background:{C_BORDER};')
        rv.addWidget(sep2)

        self._detail_stack = QStackedWidget()

        # 0 — Parameters
        self.param_table = ParameterTable()
        self._detail_stack.addWidget(self.param_table)

        # 1 — Editor
        ed_w = QWidget(); ed_v = QVBoxLayout(ed_w); ed_v.setContentsMargins(0,0,0,0)
        ed_top = QHBoxLayout(); ed_top.setContentsMargins(4,4,4,0)
        self.save_btn = QPushButton('Save'); self.save_btn.setObjectName('primary')
        self.save_btn.clicked.connect(self._save_model)
        self.lst_btn  = QPushButton('View .lst'); self.lst_btn.clicked.connect(self._view_lst)
        ed_top.addWidget(self.save_btn); ed_top.addWidget(self.lst_btn); ed_top.addStretch()
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont('Menlo' if IS_MAC else 'Consolas',12))
        self._hl = NMHighlighter(self.editor.document())
        ed_v.addLayout(ed_top); ed_v.addWidget(self.editor)
        self._detail_stack.addWidget(ed_w)

        # 2 — Run
        run_w = QWidget(); run_v = QVBoxLayout(run_w); run_v.setContentsMargins(8,8,8,8)
        rf = QFormLayout(); rf.setVerticalSpacing(6); rf.setHorizontalSpacing(12)
        self.tool_combo = QComboBox()
        self.tool_combo.addItems(['execute','vpc','bootstrap','scm','sir','cdd','npc','sse'])
        self.args_edit = QLineEdit(); self.args_edit.setPlaceholderText('-threads=4  -seed=12345')
        self.clean_cb  = QCheckBox('Clean previous run directory first'); self.clean_cb.setChecked(True)
        rf.addRow('PsN tool:', self.tool_combo); rf.addRow('Extra args:', self.args_edit)
        rf.addRow('', self.clean_cb); run_v.addLayout(rf)
        run_btn_row = QHBoxLayout(); run_btn_row.setSpacing(8)
        self.run_btn  = QPushButton('Run');  self.run_btn.setObjectName('primary')
        self.run_btn.clicked.connect(self._run_model)
        self.stop_btn = QPushButton('Stop'); self.stop_btn.clicked.connect(self._stop_run)
        self.stop_btn.setEnabled(False)
        nmtran_btn = QPushButton('NMTRAN msgs…'); nmtran_btn.clicked.connect(self._show_nmtran)
        run_btn_row.addWidget(self.run_btn); run_btn_row.addWidget(self.stop_btn)
        run_btn_row.addWidget(nmtran_btn); run_btn_row.addStretch()
        run_v.addLayout(run_btn_row)
        self.console = QPlainTextEdit(); self.console.setReadOnly(True)
        self.console.setFont(QFont('Menlo' if IS_MAC else 'Consolas',11))
        self.console.setMaximumBlockCount(5000)
        run_v.addWidget(self.console,1)
        self._detail_stack.addWidget(run_w)

        # 3 — Info
        info_w = QWidget(); info_v = QVBoxLayout(info_w)
        info_v.setContentsMargins(10,10,10,10); info_v.setSpacing(8)
        info_v.addWidget(QLabel('Comment'))
        self.comment_edit = QLineEdit(); self.comment_edit.setPlaceholderText('Short label…')
        self.comment_edit.editingFinished.connect(self._save_meta_fields)
        info_v.addWidget(self.comment_edit)
        status_row = QHBoxLayout()
        status_row.addWidget(QLabel('Status:'))
        self.status_tag_combo = QComboBox()
        self.status_tag_combo.addItems(['','base','candidate','final'])
        self.status_tag_combo.currentTextChanged.connect(self._save_meta_fields)
        status_row.addWidget(self.status_tag_combo); status_row.addStretch()
        info_v.addLayout(status_row)
        info_v.addWidget(QLabel('Notes'))
        self.notes_edit = QTextEdit(); self.notes_edit.setPlaceholderText('Rationale, decisions…')
        self.notes_edit.setMaximumHeight(160)
        orig_focusOut = self.notes_edit.focusOutEvent
        self.notes_edit.focusOutEvent = lambda e: (self._save_meta_fields(), orig_focusOut(e))
        info_v.addWidget(self.notes_edit)
        info_v.addStretch()
        self._detail_stack.addWidget(info_w)

        # 4 — Output (.lst viewer)
        self.lst_output = LstOutputWidget()
        self._detail_stack.addWidget(self.lst_output)

        rv.addWidget(self._detail_stack, 1)
        spl.addWidget(right)
        spl.setSizes([620, 380])
        spl.setStretchFactor(0, 1)   # left grows with window
        spl.setStretchFactor(1, 0)   # right stays fixed
        spl.setCollapsible(0, False)  # left never collapses
        v.addWidget(spl,1)
        self._detail_switch(0)
        QTimer.singleShot(200, self._scan)

    def _detail_switch(self, index):
        self._detail_stack.setCurrentIndex(index)
        for i, btn in enumerate(self._detail_btns):
            btn.setChecked(i == index)

    # ── Bookmarks ──────────────────────────────────────────────────────────────
    def _refresh_bookmarks(self):
        self.bm_combo.clear(); self.bm_combo.addItem('— jump to bookmark —')
        for b in load_bookmarks(): self.bm_combo.addItem(b.get('name',''), b.get('path',''))
    def _go_bookmark(self, idx):
        if idx == 0: return
        path = self.bm_combo.itemData(idx)
        if path: self.dir_edit.setText(path); self._scan()
    def _add_bookmark(self):
        path = self.dir_edit.text().strip()
        if not Path(path).is_dir(): QMessageBox.warning(self,'Invalid','Directory does not exist.'); return
        name, ok = QInputDialog.getText(self,'Bookmark','Name:', text=Path(path).name)
        if not ok or not name: return
        bms = [b for b in load_bookmarks() if b.get('path') != path]
        bms.append({'path':path,'name':name,'description':''})
        save_bookmarks(bms); self._refresh_bookmarks()

    # ── Scan ──────────────────────────────────────────────────────────────────
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self,'Select directory', self._directory)
        if d: self.dir_edit.setText(d); self._scan()
    def _scan(self):
        d = self.dir_edit.text().strip()
        if not Path(d).is_dir(): self.status_msg.emit(f'Not a directory: {d}'); return
        # New directory — reset state
        if d != self._directory:
            self._ref_model_path = None
        self._directory = d; s = load_settings(); s['working_directory'] = d; save_settings(s)
        self._meta = load_meta(); self.status_msg.emit('Scanning…'); self.table.setRowCount(0)
        # Reset right panel
        self._current_model = None
        self.param_table.table.setRowCount(0)
        self.param_table.shr_label.setText('')
        self.editor.clear()
        self.comment_edit.clear()
        self.notes_edit.clear()
        self.lst_output._browser.clear()
        self.lst_output._status_lbl.setText('No model selected')
        self.lst_output._browser_btn.setEnabled(False)
        # Terminate any in-flight scan before starting a new one
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.result.disconnect()
            self._scan_worker.terminate()
            self._scan_worker.wait(0)
        w = ScanWorker(d, self._meta)
        w.result.connect(self._on_scan)
        w.error.connect(lambda e: self.status_msg.emit(f'Scan error: {e}'))
        self._scan_worker = w; w.start()

    def _on_scan(self, models):
        t0 = time.time()
        self._all_models = models; self._table_model.load(models)
        self.table.setRowCount(len(models)); self.table.setSortingEnabled(False)
        for row, m in enumerate(models):
            for col in range(len(COLS)):
                idx = self._table_model.index(row, col)
                txt = self._table_model.data(idx, Qt.ItemDataRole.DisplayRole) or ''
                fg  = self._table_model.data(idx, Qt.ItemDataRole.ForegroundRole)
                tip = self._table_model.data(idx, Qt.ItemDataRole.ToolTipRole)
                item = QTableWidgetItem(txt)
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter |
                    (Qt.AlignmentFlag.AlignRight if col >= COL_OFV else Qt.AlignmentFlag.AlignLeft))
                if fg:  item.setForeground(fg)
                if tip: item.setToolTip(tip)
                if col == 0: item.setData(Qt.ItemDataRole.UserRole, row)
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True); self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        n = len(models); nr = sum(1 for m in models if m['has_run'])
        elapsed = time.time() - t0
        self.status_msg.emit(
            f'{n} model{"s" if n!=1 else ""}, {nr} with results  ·  '
            f'{Path(self._directory).name}  ·  scanned in {elapsed:.1f}s')

    # ── Selection ─────────────────────────────────────────────────────────────
    def eventFilter(self, obj, event):
        """Keyboard navigation on the models table."""
        from PyQt6.QtCore import QEvent
        if obj is self.table and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            row = self.table.currentRow()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._detail_switch(4); return True
            elif key == Qt.Key.Key_Space:
                self._toggle_star(); return True
            elif key == Qt.Key.Key_Up:
                if row > 0:
                    self.table.setCurrentCell(row - 1, self.table.currentColumn())
                return True
            elif key == Qt.Key.Key_Down:
                if row < self.table.rowCount() - 1:
                    self.table.setCurrentCell(row + 1, self.table.currentColumn())
                return True
        return super().eventFilter(obj, event)

    def _on_right_click(self, row):
        """Called by _ModelsTable.contextMenuEvent via C++ virtual dispatch."""
        item0 = self.table.item(row, 0)
        if item0 is None: return
        model_row = item0.data(Qt.ItemDataRole.UserRole)
        if model_row is None: model_row = row
        m = self._table_model.model_at(model_row)
        if not m: return
        self.table.selectRow(row)
        self._current_model = m
        self._ctx_menu()

    def _on_select(self):
        row = self.table.currentRow()
        if row < 0: return
        item0 = self.table.item(row, 0)
        if item0 is None: return
        model_row = item0.data(Qt.ItemDataRole.UserRole)
        if model_row is None: model_row = row
        m = self._table_model.model_at(model_row)
        if m is None: return
        self._current_model = m; self._load_detail(m); self.model_selected.emit(m)
        # Feed the Output panel whenever a model is selected
        self.lst_output.load_model(m)

    def _load_detail(self, m):
        m = _align_param_names(m)  # fix misaligned omega/sigma names from SAME blocks
        self.param_table.load(m)
        try: self.editor.setPlainText(Path(m['path']).read_text('utf-8', errors='replace'))
        except Exception: self.editor.setPlainText('')
        meta_e = get_meta_entry(self._meta, m['path'])
        self.comment_edit.setText(meta_e['comment'])
        self.notes_edit.setPlainText(meta_e['notes'])
        idx = self.status_tag_combo.findText(meta_e['status'])
        self.status_tag_combo.setCurrentIndex(max(0, idx))

    # ── Context menu ──────────────────────────────────────────────────────────
    def _ctx_menu(self):
        from PyQt6.QtGui import QCursor
        m = self._current_model
        if not m: return
        menu = QMenu(self)
        menu.addAction('* Toggle star', self._toggle_star)
        menu.addAction('Duplicate…', self._duplicate)
        menu.addSeparator()
        is_ref = (m['path'] == self._ref_model_path)
        if is_ref:
            menu.addAction('[x] Clear reference model', self._clear_reference)
        else:
            menu.addAction('( ) Set as reference model', self._set_reference)
        if len(self._all_models) > 1:
            comp_menu = menu.addMenu('Compare with…')
            for other in self._all_models:
                if other['path'] != m['path'] and other.get('has_run'):
                    act = comp_menu.addAction(other['stem'])
                    act.triggered.connect(lambda _, o=other: self._compare(m, o))
        menu.addSeparator()
        menu.addAction('View .lst', self._view_lst)
        menu.addAction('NMTRAN messages…', self._show_nmtran)
        menu.exec(QCursor.pos())

    def _set_reference(self):
        m = self._current_model
        if not m: return
        self._ref_model_path = m['path']
        self._table_model.set_reference(m['path'])
        self._refresh_table_display()
        self.status_msg.emit(f'Reference model: {m["stem"]}  — dOFV now relative to this model')

    def _clear_reference(self):
        self._ref_model_path = None
        self._table_model.set_reference(None)
        self._refresh_table_display()
        self.status_msg.emit('Reference cleared — dOFV relative to best model')

    def _compare(self, model_a, model_b):
        model_a = _align_param_names(model_a)
        model_b = _align_param_names(model_b)
        dlg = ModelComparisonDialog(model_a, model_b, self)
        dlg.exec()

    def _refresh_table_display(self):
        """Refresh Name and dOFV columns in the table without a full rescan."""
        self.table.setSortingEnabled(False)
        for row in range(self.table.rowCount()):
            item0 = self.table.item(row, 0)
            if item0 is None: continue
            model_row = item0.data(Qt.ItemDataRole.UserRole)
            if model_row is None: continue  # item not properly initialised, skip
            for col in (COL_NAME, COL_DOFV):
                idx = self._table_model.index(model_row, col)
                txt = self._table_model.data(idx, Qt.ItemDataRole.DisplayRole) or ''
                fg  = self._table_model.data(idx, Qt.ItemDataRole.ForegroundRole)
                item = self.table.item(row, col)
                if item:
                    item.setText(txt)
                    if fg: item.setForeground(fg)
        self.table.setSortingEnabled(True)

    def _toggle_star(self):
        m = self._current_model
        if not m: return
        self._meta = load_meta(); e = get_meta_entry(self._meta, m['path'])
        e['star'] = not e['star']; self._meta[m['path']] = e
        save_meta(self._meta); self._scan()

    def _view_lst(self):
        m = self._current_model
        if not m or not m.get('lst_path'): return
        try:
            text = Path(m['lst_path']).read_text('utf-8', errors='replace')
        except Exception as e:
            QMessageBox.warning(self, 'Error', str(e)); return
        dlg = LstViewerDialog(m['stem'], text, self)
        dlg.show()  # non-modal so user can keep working

    def current_directory(self):
        return self._directory

    def _show_nmtran(self):
        m = self._current_model
        if not m: return
        dlg = NMTRANPanel(m, self); dlg.exec()

    # ── Save / duplicate ──────────────────────────────────────────────────────
    def _save_model(self):
        m = self._current_model
        if not m: return
        try: Path(m['path']).write_text(self.editor.toPlainText(), 'utf-8'); self.status_msg.emit(f"Saved {m['name']}")
        except Exception as e: QMessageBox.critical(self,'Error',str(e))

    def _save_meta_fields(self):
        m = self._current_model
        if not m: return
        self._meta = load_meta(); e = get_meta_entry(self._meta, m['path'])
        e['comment'] = self.comment_edit.text().strip()
        e['notes']   = self.notes_edit.toPlainText().strip()
        e['status']  = self.status_tag_combo.currentText()
        self._meta[m['path']] = e; save_meta(self._meta)

    def _duplicate(self):
        m = self._current_model
        if not m: return
        dlg = DuplicateDialog(m['stem'], self)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        new_name = dlg.name_edit.text().strip()
        if not new_name.endswith(('.mod','.ctl')): new_name += '.mod'
        dst = Path(m['path']).parent / new_name
        if dst.exists(): QMessageBox.warning(self,'Exists',f'{new_name} already exists.'); return
        try:
            content = Path(m['path']).read_text('utf-8', errors='replace')
            if dlg.use_est.isChecked() and m.get('lst_path'):
                content = inject_estimates(content, m['lst_path'], jitter=dlg.jitter_sb.value())
            dst.write_text(content, 'utf-8')
            meta_e = get_meta_entry(self._meta, dst)
            meta_e['based_on'] = m['stem']; self._meta[str(dst)] = meta_e; save_meta(self._meta)
            self.status_msg.emit(f'Created {new_name}'); self._scan()
        except Exception as e: QMessageBox.critical(self,'Error',str(e))

    # ── Run ──────────────────────────────────────────────────────────────────
    def _run_model(self):
        m = self._current_model
        if not m: return
        tool = self.tool_combo.currentText(); tool_path = find_tool(tool)
        if not tool_path: QMessageBox.warning(self,'Not found',f'"{tool}" not found. Is PsN on PATH?'); return
        model_path = m['path']; cwd = str(Path(model_path).parent)
        q = shlex.quote; cmd = f'{q(tool_path)} {q(model_path)}'
        if tool == 'execute': cmd += f' -directory={m["stem"]}'
        extra = self.args_edit.text().strip()
        if extra: cmd += ' ' + extra
        if self.clean_cb.isChecked():
            import shutil; rd = Path(cwd)/m['stem']
            if rd.is_dir():
                try: shutil.rmtree(rd)
                except Exception as e: QMessageBox.warning(self,'Clean failed',str(e)); return
        self.console.clear(); self.console.appendPlainText(f'$ {cmd}\n')
        self.run_btn.setEnabled(False); self.stop_btn.setEnabled(True)
        if self._run_worker:
            try: self._run_worker.line_out.disconnect()
            except Exception: pass
            try: self._run_worker.finished.disconnect()
            except Exception: pass
        self._run_worker = RunWorker(cmd, cwd)
        self._run_worker.line_out.connect(self.console.appendPlainText)
        self._run_worker.finished.connect(self._on_run_done)
        self._run_worker.start()
        runs = load_runs()
        runs.insert(0,{'id':f"{m['stem']}_{int(time.time())}","run_name":m['stem'],
                       "model":model_path,"tool":tool,"command":cmd,"working_dir":cwd,
                       "status":"running","started":datetime.now().isoformat(),"finished":None})
        save_runs(runs[:200])
    def _on_run_done(self, rc):
        self.run_btn.setEnabled(True); self.stop_btn.setEnabled(False)
        s = 'finished' if rc == 0 else f'failed (code {rc})'
        self.console.appendPlainText(f'\n[Process {s}]')
        self.status_msg.emit(f'Run {s}')
        # Update the most recent run record with final status and end time
        runs = load_runs()
        if runs:
            runs[0]['status']   = 'ok' if rc == 0 else f'failed ({rc})'
            runs[0]['finished'] = datetime.now().isoformat()
            runs[0]['exit_code'] = rc
            save_runs(runs)
        QTimer.singleShot(1500, self._scan)
    def _stop_run(self):
        if self._run_worker: self._run_worker.stop()
    def current_directory(self): return self._directory


# ══════════════════════════════════════════════════════════════════════════════
# Evaluation Tab
# ══════════════════════════════════════════════════════════════════════════════

def _placeholder(msg):
    lbl = QLabel(msg); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet(f'color:{C_FG2};font-size:14px;'); return lbl


class GOFWidget(QWidget):
    # Panel definitions: key → (row, col, y_label, default_x, refline)
    PANELS = {
        (0,0): ('DV',    'PRED',  True),
        (0,1): ('DV',    'IPRED', True),
        (1,0): ('CWRES', 'PRED',  False),
        (1,1): ('CWRES', 'TIME',  False),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._header = []; self._rows = []; self._mdv_filter = True
        self._arr = None; self._H = []
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)
        if not HAS_PG or not HAS_NP:
            v.addWidget(_placeholder('Install pyqtgraph and numpy:\npip3 install pyqtgraph numpy')); return

        # ── Toolbar ───────────────────────────────────────────────────────────
        tb = QWidget(); tb.setFixedHeight(36)
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(8,4,8,4); tbl.setSpacing(8)

        # X-axis dropdowns for each panel
        self._x_cbs = {}
        panel_labels = ['Top-left X:', 'Top-right X:', 'Bottom-left X:', 'Bottom-right X:']
        defaults     = ['PRED', 'IPRED', 'PRED', 'TIME']
        keys = [(0,0),(0,1),(1,0),(1,1)]
        for i, (key, lbl, dflt) in enumerate(zip(keys, panel_labels, defaults)):
            tbl.addWidget(QLabel(lbl))
            cb = QComboBox(); cb.setMinimumWidth(80); cb.addItem(dflt)
            cb.currentTextChanged.connect(self._replot)
            self._x_cbs[key] = cb
            tbl.addWidget(cb)
            if i < 3: tbl.addSpacing(4)

        tbl.addStretch()

        # Filter
        tbl.addWidget(QLabel('Filter:'))
        self._filt_col = QComboBox(); self._filt_col.setMinimumWidth(80); self._filt_col.addItem('')
        self._filt_val = QComboBox(); self._filt_val.setMinimumWidth(80); self._filt_val.setEditable(True)
        self._filt_col.currentTextChanged.connect(self._update_filter_vals)
        self._filt_val.currentTextChanged.connect(self._replot)
        tbl.addWidget(self._filt_col); tbl.addWidget(self._filt_val)

        # Export
        exp_btn = QPushButton('Export PNG…'); exp_btn.setFixedHeight(26)
        exp_btn.setToolTip('Save publication-ready 300 DPI PNG')
        exp_btn.clicked.connect(self._export)
        tbl.addWidget(exp_btn)
        v.addWidget(tb)

        sep = QWidget(); sep.setFixedHeight(1); sep.setStyleSheet(f'background:{C_BORDER};')
        v.addWidget(sep)

        # ── Plot grid ─────────────────────────────────────────────────────────
        self.gw = pg.GraphicsLayoutWidget(); v.addWidget(self.gw, 1)
        self._panels = {}; self._setup()

    def set_theme(self, bg, fg):
        if not HAS_PG: return
        self.gw.setBackground(bg)
        fg_color = pg.mkColor(fg)
        for (p, refline, xl, yl) in self._panels.values():
            for ax_name in ('left', 'bottom'):
                ax = p.getAxis(ax_name)
                ax.setPen(fg_color)
                ax.setTextPen(fg_color)

    def _setup(self):
        y_labels  = {(0,0):'DV',    (0,1):'DV',    (1,0):'CWRES', (1,1):'CWRES'}
        reflines  = {(0,0):True,    (0,1):True,     (1,0):False,   (1,1):False}
        for r in range(2):
            for c in range(2):
                key = (r,c)
                xl = self._x_cbs[key].currentText() if hasattr(self,'_x_cbs') else ['PRED','IPRED','PRED','TIME'][r*2+c]
                yl = y_labels[key]
                p = self.gw.addPlot(row=r, col=c)
                p.setLabel('bottom', xl); p.setLabel('left', yl)
                p.showGrid(x=True, y=True, alpha=0.2)
                p.getAxis('bottom').enableAutoSIPrefix(False)
                p.getAxis('left').enableAutoSIPrefix(False)
                self._panels[key] = (p, reflines[key], xl, yl)

    def _update_filter_vals(self):
        col = self._filt_col.currentText()
        self._filt_val.blockSignals(True)
        self._filt_val.clear(); self._filt_val.addItem('')
        if col and col in self._H:
            ci = self._H.index(col)
            vals = sorted(set(str(r[ci]) for r in self._rows if ci < len(r)))
            self._filt_val.addItems(vals[:200])
        self._filt_val.blockSignals(False)

    def _get_mask(self):
        if self._arr is None: return None
        mask = np.ones(len(self._arr), bool)
        if self._mdv_filter and 'MDV' in self._H:
            mask &= (self._arr[:, self._H.index('MDV')] == 0)
        col = self._filt_col.currentText(); val = self._filt_val.currentText().strip()
        if col and val and col in self._H:
            ci = self._H.index(col)
            try:
                fv = float(val)
                mask &= (self._arr[:, ci] == fv)
            except ValueError:
                # String filter on string column not supported in numpy array — skip
                pass
        return mask

    def _replot(self):
        if self._arr is None: return
        try:
            mask = self._get_mask()
            blue = pg.mkBrush(60, 120, 220, 140)
            y_cols = {(0,0):'DV', (0,1):'DV', (1,0):'CWRES', (1,1):'CWRES'}
            reflines = {(0,0):True, (0,1):True, (1,0):False, (1,1):False}
            for key, (p, _, old_xl, yl) in self._panels.items():
                xl = self._x_cbs[key].currentText()
                p.clear()
                if xl not in self._H or yl not in self._H: continue
                xd = self._arr[:, self._H.index(xl)]
                yd = self._arr[:, self._H.index(yl)]
                ok = mask & np.isfinite(xd) & np.isfinite(yd)
                x, y = xd[ok], yd[ok]
                if len(x) == 0: continue
                p.setLabel('bottom', xl)
                p.addItem(pg.ScatterPlotItem(x=x, y=y, pen=None, brush=blue, size=5))
                if reflines[key]:
                    mn=min(x.min(),y.min()); mx=max(x.max(),y.max())
                    p.plot([mn,mx],[mn,mx], pen=pg.mkPen(C_RED, width=1.5))
                else:
                    p.plot([x.min(),x.max()],[0,0],
                           pen=pg.mkPen('#aaaaaa',width=1.5,style=Qt.PenStyle.DashLine))
                xlo, ylo = loess(x, y)
                if xlo is not None: p.plot(xlo, ylo, pen=pg.mkPen('#ff9999', width=2))
        except Exception: pass  # replot errors are non-fatal

    def load(self, header, rows, mdv_filter=True):
        if not HAS_PG or not HAS_NP: return
        if not rows or not header: return
        self._header = header; self._rows = rows; self._mdv_filter = mdv_filter
        self._H = [h.upper() for h in header]
        def to_float(v):
            try: return float(v)
            except (ValueError, TypeError): return float('nan')
        self._arr = np.array([[to_float(v) for v in row] for row in rows], dtype=float)

        # Populate X dropdowns with all columns
        for key, cb in self._x_cbs.items():
            cur = cb.currentText(); cb.blockSignals(True); cb.clear()
            cb.addItems(self._H); idx = cb.findText(cur)
            cb.setCurrentIndex(max(0, idx)); cb.blockSignals(False)

        # Populate filter column combo
        self._filt_col.blockSignals(True); self._filt_col.clear()
        self._filt_col.addItems([''] + self._H); self._filt_col.blockSignals(False)

        self._replot()

    def _export(self):
        """Export the GOF 2×2 as a 300 DPI publication-ready PNG."""
        if not HAS_PG or not HAS_NP: return
        if self._arr is None:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self,'No data','Load data first.'); return
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Export GOF plot', str(HOME / 'gof_plot.png'),
            'PNG images (*.png)')
        if not dst: return
        try:
            from pyqtgraph.exporters import ImageExporter
            exp = ImageExporter(self.gw.scene())
            # Scale to ~3000px wide for ~300 DPI at 10 inches
            w = self.gw.width(); h = self.gw.height()
            scale = max(1, 3000 // max(w, 1))
            exp.parameters()['width']  = w * scale
            exp.parameters()['height'] = h * scale
            exp.export(dst)
            from PyQt6.QtWidgets import QMessageBox
            if QMessageBox.question(self,'Exported',f'GOF plot saved to:\n{dst}\n\nOpen?',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes:
                if IS_WIN:   __import__('os').startfile(dst)
                elif IS_MAC: __import__('subprocess').Popen(['open', dst])
                else:        __import__('subprocess').Popen(['xdg-open', dst])
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self,'Export failed',str(e))


class IndFitWidget(QWidget):
    GRIDS = {'2×2':2,'3×3':3,'4×4':4}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._header = None; self._rows = None; self._ids = []; self._page = 0
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0)
        if not HAS_PG or not HAS_NP: v.addWidget(_placeholder('Install pyqtgraph and numpy')); return
        ctrl = QHBoxLayout()
        self.grid_cb = QComboBox(); self.grid_cb.addItems(list(self.GRIDS.keys()))
        self.grid_cb.currentTextChanged.connect(self._render)
        self.prev_btn = QPushButton('<'); self.prev_btn.clicked.connect(self._prev)
        self.next_btn = QPushButton('>'); self.next_btn.clicked.connect(self._next)
        self.page_lbl = QLabel(''); self.page_lbl.setFixedWidth(80)
        ctrl.addWidget(QLabel('Grid:')); ctrl.addWidget(self.grid_cb)
        ctrl.addStretch(); ctrl.addWidget(self.prev_btn); ctrl.addWidget(self.page_lbl); ctrl.addWidget(self.next_btn)
        v.addLayout(ctrl)
        self.gw = pg.GraphicsLayoutWidget(); v.addWidget(self.gw,1)

    def set_theme(self, bg, fg):
        if HAS_PG and hasattr(self, 'gw'): self.gw.setBackground(bg)
        # Individual fit panels are recreated on each load so no axis pen update needed

    def load(self, header, rows):
        if not HAS_PG or not HAS_NP: return
        if not rows or not header: return
        self._header=[h.upper() for h in header]; self._rows=rows
        if 'ID' in self._header:
            col = self._header.index('ID'); seen = {}
            for row in rows:
                v = row[col]
                if v not in seen: seen[v] = True
            self._ids = list(seen.keys())
        else: self._ids = []
        self._page = 0; self._render()

    def _pp(self): g=self.GRIDS.get(self.grid_cb.currentText(),2); return g*g
    def _np(self): return max(1, math.ceil(len(self._ids)/self._pp()))
    def _prev(self):
        if self._page>0: self._page-=1; self._render()
    def _next(self):
        if self._page<self._np()-1: self._page+=1; self._render()

    def _render(self):
        if not HAS_PG or not HAS_NP or not self._ids: self.gw.clear() if HAS_PG else None; return
        pp=self._pp(); g=self.GRIDS.get(self.grid_cb.currentText(),2)
        ids_page=self._ids[self._page*pp:(self._page+1)*pp]
        self.page_lbl.setText(f'{self._page+1}/{self._np()}')
        self.prev_btn.setEnabled(self._page>0); self.next_btn.setEnabled(self._page<self._np()-1)
        self.gw.clear()
        H=self._header
        def gi(name): return H.index(name) if name in H else None
        ci=gi('ID'); ct=gi('TIME'); cd=gi('DV'); cp=gi('PRED'); ci2=gi('IPRED'); cm=gi('MDV')
        id_rows={}
        for row in self._rows:
            if ci is None: continue
            rid=row[ci]
            if rid not in id_rows: id_rows[rid]=[]
            id_rows[rid].append(row)
        dv_b=pg.mkBrush(60,120,220,160)
        ip_p=pg.mkPen('#1a1a2e' if _active_theme=='light' else '#ffffff',width=2)
        pr_p=pg.mkPen(C_RED,width=1,style=Qt.PenStyle.DashLine)
        for i,rid in enumerate(ids_page):
            ri,ci_=divmod(i,g); p=self.gw.addPlot(row=ri,col=ci_,title=f'ID {rid}')
            p.showGrid(x=True,y=True,alpha=0.15)
            rws=id_rows.get(rid,[]); ok=[cm is None or r[cm]==0 for r in rws]
            def cv(idx):
                if idx is None: return None
                try: return np.array([float(r[idx]) for r,o in zip(rws,ok) if o])
                except: return None
            def cv_all(idx):
                if idx is None: return None
                try: return np.array([float(r[idx]) for r in rws])
                except: return None
            to=cv(ct); dvo=cv(cd); ta=cv_all(ct); pra=cv_all(cp); ipa=cv_all(ci2)
            if to is not None and dvo is not None: p.addItem(pg.ScatterPlotItem(x=to,y=dvo,pen=None,brush=dv_b,size=6))
            if ta is not None and ipa is not None:
                o=np.argsort(ta); p.plot(ta[o],ipa[o],pen=ip_p)
            if ta is not None and pra is not None:
                o=np.argsort(ta); p.plot(ta[o],pra[o],pen=pr_p)


class WaterfallWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0)
        if not HAS_PG or not HAS_NP: v.addWidget(_placeholder('Install pyqtgraph and numpy')); return
        self.pw = pg.PlotWidget(title='Individual OFV Contributions')
        self.pw.setLabel('left','iOFV'); self.pw.setLabel('bottom','Subject rank')
        self.pw.showGrid(x=True,y=True,alpha=0.2)
        self.pw.getAxis('bottom').enableAutoSIPrefix(False)
        self.pw.getAxis('left').enableAutoSIPrefix(False)
        self._ids_sorted = []; self._obj_sorted = np.array([])
        # Tooltip box: dark fill + white text — readable on both themes
        self._hover_lbl = pg.TextItem(
            '', anchor=(0.5, 1.3),
            color='#ffffff',
            fill=pg.mkBrush(30, 30, 40, 220),
            border=pg.mkPen('#4c8aff', width=1))
        self._hover_lbl.setZValue(10)
        self.pw.addItem(self._hover_lbl); self._hover_lbl.hide()
        self.pw.scene().sigMouseMoved.connect(self._on_mouse)
        v.addWidget(self.pw)

    def set_theme(self, bg, fg):
        if not HAS_PG: return
        self.pw.setBackground(bg)
        fg_color = pg.mkColor(fg)
        for ax_name in ('left', 'bottom'):
            ax = self.pw.getAxis(ax_name)
            ax.setPen(fg_color)
            ax.setTextPen(fg_color)

    def load(self, phi):
        if not HAS_PG or not HAS_NP: return
        self.pw.clear()
        self.pw.addItem(self._hover_lbl); self._hover_lbl.hide()
        obj = np.array(phi.get('obj',[]), dtype=float)
        ids = phi.get('ids', [])
        if len(obj) == 0: return
        order = np.argsort(obj)
        self._obj_sorted = obj[order]
        self._ids_sorted = [ids[i] for i in order] if ids else list(range(len(order)))
        n = len(self._obj_sorted); mn,mx = self._obj_sorted.min(), self._obj_sorted.max()
        brushes = [pg.mkBrush(
            int(244*((v-mn)/(mx-mn+1e-12)) + 86*(1-((v-mn)/(mx-mn+1e-12)))),
            100,
            int(71*((v-mn)/(mx-mn+1e-12)) + 156*(1-((v-mn)/(mx-mn+1e-12)))),
            200) for v in self._obj_sorted]
        self.pw.addItem(pg.BarGraphItem(
            x=np.arange(n, dtype=float), height=self._obj_sorted, width=0.8, brushes=brushes))

    def _on_mouse(self, pos):
        if len(self._ids_sorted) == 0: return
        try:
            mp = self.pw.plotItem.vb.mapSceneToView(pos)
            xi = int(round(mp.x()))
            if 0 <= xi < len(self._ids_sorted):
                sid = self._ids_sorted[xi]; ov = self._obj_sorted[xi]
                self._hover_lbl.setText(f'ID {sid:.0f}\niOFV {ov:.3f}')
                self._hover_lbl.setPos(xi, ov)
                self._hover_lbl.show()
            else:
                self._hover_lbl.hide()
        except Exception:
            self._hover_lbl.hide()


class AncestryTreeWidget(QWidget):
    """Interactive model ancestry/lineage tree using QGraphicsScene."""
    model_clicked = pyqtSignal(str)   # emits model stem

    NODE_W = 130; NODE_H = 46; H_GAP = 60; V_GAP = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self._models = []
        self._current_stem = None
        self._selecting = False
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)
        from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene
        self._scene = QGraphicsScene()
        # Use app background colour — not pyqtgraph bg which can be white in light mode
        self._scene.setBackgroundBrush(QBrush(QColor(C_BG)))
        self._view  = QGraphicsView(self._scene)
        self._view.setRenderHint(self._view.renderHints().__class__.Antialiasing, True)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._view.wheelEvent = self._wheel
        v.addWidget(self._view)  # must be here, not in showEvent
        # Connect selection signal exactly once
        self._scene.selectionChanged.connect(self._on_selection)

    def showEvent(self, event):
        """Fit tree into view when tab becomes visible (after _rebuild has run)."""
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_view)

    def _fit_view(self):
        if self._scene.items():
            bounds = self._scene.itemsBoundingRect().adjusted(-20,-20,20,20)
            self._view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def set_theme(self, bg, fg):
        # Always use app background so nodes are visible in both themes
        self._scene.setBackgroundBrush(QBrush(QColor(THEMES[_active_theme]['bg'])))
        self._rebuild()  # redraw nodes with new theme colours

    def load(self, models, current_stem=None):
        self._models    = models
        self._current_stem = current_stem
        self._rebuild()

    def _rebuild(self):
        from PyQt6.QtWidgets import QGraphicsRectItem, QGraphicsTextItem, QGraphicsLineItem, QGraphicsEllipseItem
        from PyQt6.QtGui import QPen, QPainterPath
        from PyQt6.QtWidgets import QGraphicsPathItem

        self._scene.clear()
        if not self._models: return

        # Build stem → model map and adjacency
        by_stem  = {m['stem']: m for m in self._models}
        children = {m['stem']: [] for m in self._models}
        roots    = []
        for m in self._models:
            p = m.get('based_on')
            if p and p in by_stem:
                children[p].append(m['stem'])
            else:
                roots.append(m['stem'])

        if not roots:  # cycle or all have unknown parents — show all as roots
            roots = [m['stem'] for m in self._models]

        # Assign (col, row) positions using BFS level layout
        pos   = {}   # stem → (col, row) where col = depth, row = sibling index
        depth_counts = {}
        queue = [(r, 0) for r in sorted(roots)]
        visited = set()
        while queue:
            stem, depth = queue.pop(0)
            if stem in visited: continue
            visited.add(stem)
            row = depth_counts.get(depth, 0)
            depth_counts[depth] = row + 1
            pos[stem] = (depth, row)
            for ch in sorted(children.get(stem, [])):
                if ch not in visited:
                    queue.append((ch, depth+1))

        # Handle any models not reachable from roots (orphans)
        max_depth = max((v[0] for v in pos.values()), default=0) + 1
        orphan_row = 0
        for m in self._models:
            if m['stem'] not in pos:
                pos[m['stem']] = (max_depth, orphan_row)
                orphan_row += 1

        NW = self.NODE_W; NH = self.NODE_H; HG = self.H_GAP; VG = self.V_GAP

        def node_rect(stem):
            col, row = pos[stem]
            x = col * (NW + HG)
            y = row * (NH + VG)
            return x, y, NW, NH

        # Draw edges first (behind nodes)
        pen_edge = QPen(QColor(C_BORDER)); pen_edge.setWidth(2)
        for stem in pos:
            m = by_stem.get(stem)
            if not m: continue
            parent = m.get('based_on')
            if parent and parent in pos:
                px, py, pw, ph = node_rect(parent)
                cx, cy, cw, ch = node_rect(stem)
                # Elbow connector: right-centre of parent → left-centre of child
                x1 = px + pw; y1 = py + ph/2
                x2 = cx;      y2 = cy + ch/2
                mid_x = (x1 + x2) / 2
                path = QPainterPath()
                path.moveTo(x1, y1)
                path.cubicTo(mid_x, y1, mid_x, y2, x2, y2)
                pi = QGraphicsPathItem(path)
                pi.setPen(pen_edge)
                self._scene.addItem(pi)

        # Draw nodes
        for stem, (col, row) in pos.items():
            m  = by_stem.get(stem, {})
            x, y, w, h = node_rect(stem)
            is_current = (stem == self._current_stem)
            is_ok      = m.get('minimization_successful') is True
            is_fail    = m.get('minimization_successful') is False

            # Background colour
            if is_current:
                fill = QColor(C_BLUE)
            elif is_ok:
                fill = QColor('#1a3a2a') if _active_theme == 'dark' else QColor('#e6f4ed')
            elif is_fail:
                fill = QColor('#3a1a1a') if _active_theme == 'dark' else QColor('#fce8e8')
            else:
                # Neutral: use BG3 which contrasts against the scene background in both themes
                fill = QColor(C_BG3)

            border_col = QColor(C_BLUE if is_current else C_BORDER)
            pen_node   = QPen(border_col); pen_node.setWidth(2 if is_current else 1)

            rect = QGraphicsRectItem(x, y, w, h)
            rect.setBrush(QBrush(fill)); rect.setPen(pen_node)
            rect.setData(0, stem)
            rect.setAcceptHoverEvents(True)
            rect.setFlag(rect.GraphicsItemFlag.ItemIsSelectable, True)
            self._scene.addItem(rect)

            # Star
            if m.get('star'):
                star = self._scene.addText('*')
                star.setDefaultTextColor(QColor('#f5c518'))
                star.setPos(x + 4, y + 2)
                f = star.font(); f.setPointSize(9); star.setFont(f)
                sx = 16
            else:
                sx = 4

            # Status dot
            dot_col = QColor(C_GREEN if is_ok else C_RED if is_fail else C_FG2)
            dot = QGraphicsEllipseItem(x + w - 12, y + h/2 - 4, 8, 8)
            dot.setBrush(QBrush(dot_col)); dot.setPen(QPen(Qt.PenStyle.NoPen))
            self._scene.addItem(dot)

            # Stem label
            lbl = self._scene.addText(stem)
            lbl.setDefaultTextColor(QColor('#ffffff' if is_current else C_FG))
            lbl.setPos(x + sx, y + 2)
            f = lbl.font(); f.setPointSize(10); f.setBold(is_current); lbl.setFont(f)
            lbl.setTextWidth(w - sx - 16)

            # OFV
            ofv = m.get('ofv')
            if ofv is not None:
                olbl = self._scene.addText(f'{ofv:.2f}')
                olbl.setDefaultTextColor(QColor('#aaaacc' if is_current else C_FG2))
                f2 = olbl.font(); f2.setPointSize(8); olbl.setFont(f2)
                olbl.setPos(x + sx, y + h - 18)

        # Wire click via scene
        self._view.setScene(self._scene)  # ensure view tracks scene after clear
        bounds = self._scene.itemsBoundingRect().adjusted(-20,-20,20,20)
        self._scene.setSceneRect(bounds)
        # fitInView only works when widget is visible
        if self.isVisible():
            self._view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)
        else:
            QTimer.singleShot(50, self._fit_view)

    def _on_selection(self):
        if getattr(self, '_selecting', False): return
        items = self._scene.selectedItems()
        for item in items:
            stem = item.data(0)
            if stem:
                self._selecting = True
                # Defer emit — switching tabs inside selectionChanged causes segfault
                QTimer.singleShot(0, lambda s=stem: self._emit_clicked(s))
                return

    def _emit_clicked(self, stem):
        try:
            self.model_clicked.emit(stem)
        finally:
            self._selecting = False

    def _wheel(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1/1.15
        self._view.scale(factor, factor)

    def set_current(self, stem):
        self._current_stem = stem
        self._rebuild()


class ETACovWidget(QWidget):
    """ETA vs covariate scatter plots — reads patab/cotab columns."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._header = []; self._rows = []
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)
        if not HAS_PG or not HAS_NP:
            v.addWidget(_placeholder('Install pyqtgraph and numpy')); return

        # Controls
        ctrl = QWidget(); ctrl.setFixedHeight(36)
        cl = QHBoxLayout(ctrl); cl.setContentsMargins(8,4,8,4); cl.setSpacing(8)
        cl.addWidget(QLabel('ETAs:'))
        self.eta_cb = QComboBox(); self.eta_cb.setMinimumWidth(100)
        cl.addWidget(self.eta_cb)
        cl.addWidget(QLabel('vs Covariates:'))
        self.cov_list = QListWidget()
        self.cov_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.cov_list.setMaximumHeight(36)
        self.cov_list.setFlow(QListWidget.Flow.LeftToRight)
        self.cov_list.setFixedHeight(36)
        cl.addWidget(self.cov_list, 1)
        plot_btn = QPushButton('Plot'); plot_btn.setObjectName('primary')
        plot_btn.setFixedHeight(26); plot_btn.clicked.connect(self._plot)
        cl.addWidget(plot_btn)
        v.addWidget(ctrl)

        sep = QWidget(); sep.setFixedHeight(1); sep.setStyleSheet(f'background:{C_BORDER};')
        v.addWidget(sep)

        self.gw = pg.GraphicsLayoutWidget(); v.addWidget(self.gw, 1)

    def set_theme(self, bg, fg):
        if HAS_PG and hasattr(self,'gw'): self.gw.setBackground(bg)

    def load(self, header, rows):
        if not HAS_PG or not HAS_NP: return
        self._header = [h.upper() for h in header]; self._rows = rows
        # ETAs: columns starting with ETA or ETASHRINK excluded
        etas = [h for h in self._header if h.startswith('ETA') and 'SHRINK' not in h]
        # Covariates: numeric columns that are not ETAs, DV, PRED, IPRED, CWRES, MDV, EVID, AMT, TIME, ID
        skip = {'DV','PRED','IPRED','CWRES','MDV','EVID','AMT','CMT','SS','II','ADDL','RATE'}
        cov_candidates = [h for h in self._header if not h.startswith('ETA')
                          and h not in skip and not h.startswith('OMEGA')
                          and not h.startswith('SIGMA') and not h.startswith('THETA')]
        self.eta_cb.clear(); self.eta_cb.addItems(etas)
        self.cov_list.clear()
        for c in cov_candidates: self.cov_list.addItem(c)
        # Auto-select first 4 covariates
        for i in range(min(4, self.cov_list.count())):
            self.cov_list.item(i).setSelected(True)

    def _plot(self):
        if not HAS_PG or not HAS_NP: return
        eta = self.eta_cb.currentText()
        covs = [item.text() for item in self.cov_list.selectedItems()]
        if not eta or not covs or eta not in self._header: return
        H = self._header
        def to_float(v):
            try: return float(v)
            except: return float('nan')
        arr = np.array([[to_float(v) for v in row] for row in self._rows])
        ei = H.index(eta); eta_vals = arr[:,ei]
        self.gw.clear()
        nc = len(covs); ncols = min(nc, 3); nrows = math.ceil(nc/ncols)
        pal=['#569cd6','#4ec994','#ce9178','#dcdcaa','#c586c0','#9cdcfe']
        for idx, cov in enumerate(covs):
            if cov not in H: continue
            ci = H.index(cov); cov_vals = arr[:,ci]
            ok = np.isfinite(eta_vals) & np.isfinite(cov_vals)
            x, y = cov_vals[ok], eta_vals[ok]
            if len(x)==0: continue
            r, c = divmod(idx, ncols)
            p = self.gw.addPlot(row=r, col=c)
            p.setLabel('bottom', cov); p.setLabel('left', eta)
            p.showGrid(x=True, y=True, alpha=0.2)
            p.getAxis('bottom').enableAutoSIPrefix(False)
            p.getAxis('left').enableAutoSIPrefix(False)
            color = pal[idx % len(pal)]; qc = QColor(color)
            p.addItem(pg.ScatterPlotItem(x=x, y=y, pen=None,
                brush=pg.mkBrush(qc.red(),qc.green(),qc.blue(),120), size=5))
            # Y=0 line
            p.plot([x.min(),x.max()],[0,0],
                   pen=pg.mkPen('#aaaaaa',width=1,style=Qt.PenStyle.DashLine))
            # LOESS
            xlo, ylo = loess(x, y)
            if xlo is not None: p.plot(xlo, ylo, pen=pg.mkPen(color, width=2))


class ConvergenceWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0)
        if not HAS_PG or not HAS_NP: v.addWidget(_placeholder('Install pyqtgraph and numpy')); return
        self.gw = pg.GraphicsLayoutWidget(); v.addWidget(self.gw)

    def set_theme(self, bg, fg):
        if HAS_PG: self.gw.setBackground(bg)
        # Convergence panels recreated on each load

    def load(self, ext):
        if not HAS_PG or not HAS_NP or not ext: return
        self.gw.clear(); data=ext['data']; cols=ext['columns']
        if not data: return
        iters=np.array([r.get('ITERATION',i) for i,r in enumerate(data)])
        if 'OBJ' in cols:
            p1=self.gw.addPlot(row=0,col=0,title='OFV')
            p1.setLabel('left','OFV'); p1.setLabel('bottom','Iteration'); p1.showGrid(x=True,y=True,alpha=0.2)
            p1.plot(iters,np.array([r['OBJ'] for r in data]),pen=pg.mkPen(C_GREEN,width=2))
        pcols=[c for c in cols if c not in ('ITERATION','OBJ') and
               any(c.startswith(p) for p in ('THETA','OMEGA','SIGMA'))]
        if pcols:
            p2=self.gw.addPlot(row=1,col=0,title='Parameters')
            p2.setLabel('left','Value'); p2.setLabel('bottom','Iteration')
            p2.showGrid(x=True,y=True,alpha=0.2); p2.addLegend()
            pal=['#569cd6','#4ec994','#ce9178','#dcdcaa','#c586c0','#9cdcfe','#f44747','#6a9955','#4fc1ff','#d7ba7d']
            for i,c in enumerate(pcols[:10]):
                vals=np.array([r.get(c,float('nan')) for r in data])
                p2.plot(iters,vals,pen=pg.mkPen(pal[i%len(pal)],width=1.5),name=c)


class FilterRow(QWidget):
    """Single filter row: column  operator  value  🗑"""
    removed = pyqtSignal(object)
    changed = pyqtSignal()
    OPERATORS = ['=', '!=', '<', '<=', '>', '>=', 'contains']

    def __init__(self, columns, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self); h.setContentsMargins(0,0,0,0); h.setSpacing(4)
        self.col_cb = QComboBox(); self.col_cb.setMinimumWidth(100)
        self.col_cb.addItems([''] + columns)
        self.col_cb.currentTextChanged.connect(self._update_vals)
        self.col_cb.currentTextChanged.connect(self.changed)
        self.op_cb  = QComboBox(); self.op_cb.addItems(self.OPERATORS); self.op_cb.setFixedWidth(72)
        self.op_cb.currentTextChanged.connect(self.changed)
        self.val_cb = QComboBox(); self.val_cb.setMinimumWidth(110); self.val_cb.setEditable(True)
        self.val_cb.currentTextChanged.connect(self.changed)
        rem = QPushButton('[x]'); rem.setFixedWidth(36)
        rem.clicked.connect(lambda: self.removed.emit(self))
        h.addWidget(self.col_cb); h.addWidget(self.op_cb)
        h.addWidget(self.val_cb, 1); h.addWidget(rem)
        self._rows = []; self._header = []

    def set_rows(self, rows, header):
        self._rows = rows; self._header = header
        self._update_vals()

    def _update_vals(self):
        col = self.col_cb.currentText()
        self.val_cb.clear(); self.val_cb.addItem('')
        if col and col in self._header:
            ci = self._header.index(col)
            vals = sorted(set(str(r[ci]) for r in self._rows if ci < len(r)))
            self.val_cb.addItems(vals[:300])

    def matches(self, row, header):
        col = self.col_cb.currentText()
        val = self.val_cb.currentText().strip()
        op  = self.op_cb.currentText()
        if not col or not val: return True
        if col not in header: return True
        cell = str(row[header.index(col)])
        if op == 'contains': return val.lower() in cell.lower()
        # Try numeric comparison
        try:
            cv = float(cell); vv = float(val)
            if op == '=':  return cv == vv
            if op == '≠':  return cv != vv
            if op == '<':  return cv <  vv
            if op == '≤':  return cv <= vv
            if op == '>':  return cv >  vv
            if op == '≥':  return cv >= vv
        except ValueError:
            # String fallback
            if op == '=':  return cell == val
            if op == '≠':  return cell != val
            if op == '<':  return cell <  val
            if op == '≤':  return cell <= val
            if op == '>':  return cell >  val
            if op == '≥':  return cell >= val
        return True


class CWRESHistWidget(QWidget):
    """CWRES histogram with normal density overlay."""
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0)
        if not HAS_MPL or not HAS_NP:
            v.addWidget(_placeholder('Install matplotlib:\npip3 install matplotlib')); return
        self.fig = Figure(figsize=(6,4), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax = self.fig.add_subplot(111)
        v.addWidget(self.canvas)

    def load(self, header, rows, mdv_filter=True):
        if not HAS_MPL or not HAS_NP: return
        H = [h.upper() for h in header]
        if 'CWRES' not in H: return
        try:
            ci = H.index('CWRES'); mi = H.index('MDV') if 'MDV' in H else None
            cwres = np.array([float(r[ci]) for r in rows
                if (mi is None or not mdv_filter or r[mi]==0) and ci < len(r)
                and np.isfinite(float(r[ci]))])
            if len(cwres) < 3: return
            self.ax.clear()
            t = THEMES[_active_theme]; bg=t['bg2']; fg=t['fg']; fg2=t['fg2']
            self.fig.patch.set_facecolor(bg); self.ax.set_facecolor(bg)
            self.ax.tick_params(colors=fg2); self.ax.xaxis.label.set_color(fg2)
            self.ax.yaxis.label.set_color(fg2); self.ax.title.set_color(fg)
            for sp in self.ax.spines.values(): sp.set_color(fg2)
            self.ax.hist(cwres, bins=30, density=True, color=t['accent'], alpha=0.6, edgecolor='none')
            x = np.linspace(cwres.min(), cwres.max(), 200)
            mu, sigma = cwres.mean(), cwres.std()
            pdf = np.exp(-0.5*((x-mu)/sigma)**2) / (sigma*np.sqrt(2*np.pi))
            self.ax.plot(x, pdf, color=t['red'], linewidth=2, label='Normal')
            self.ax.axvline(0, color=fg2, linewidth=1, linestyle='--')
            self.ax.set_xlabel('CWRES'); self.ax.set_ylabel('Density')
            self.ax.set_title(f'CWRES Distribution  (n={len(cwres)}, mean={mu:.3f}, SD={sigma:.3f})')
            self.ax.legend(framealpha=0.3)
            self.canvas.draw()
        except Exception: pass  # render errors are non-fatal

    def set_theme(self, bg, fg): pass


class QQPlotWidget(QWidget):
    """Normal QQ plot of CWRES with normality statistics."""
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)
        if not HAS_MPL or not HAS_NP:
            v.addWidget(_placeholder('Install matplotlib:\npip3 install matplotlib')); return
        self.fig = Figure(figsize=(5,5), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax = self.fig.add_subplot(111)
        v.addWidget(self.canvas, 1)
        # Normality statistics label
        self.stats_lbl = QLabel('')
        self.stats_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_lbl.setWordWrap(True)
        self.stats_lbl.setStyleSheet('font-size:12px;padding:8px 16px;')
        v.addWidget(self.stats_lbl)

    @staticmethod
    def _norm_ppf(p):
        """Rational approximation for normal quantile (Beasley-Springer-Moro)."""
        a = np.array([2.515517, 0.802853, 0.010328])
        b = np.array([1.432788, 0.189269, 0.001308])
        p = np.clip(p, 1e-10, 1-1e-10)
        t = np.sqrt(-2*np.log(np.where(p < 0.5, p, 1-p)))
        num = a[0] + t*(a[1] + t*a[2])
        den = 1 + t*(b[0] + t*(b[1] + t*b[2]))
        z = t - num/den
        return np.where(p < 0.5, -z, z)

    @staticmethod
    def _shapiro_wilk_approx(x):
        """
        Approximate Shapiro-Wilk W statistic (numpy only, no scipy).
        Returns (W, p_value). Valid for n=3..5000.
        Uses the Royston (1992) approximation.
        """
        n = len(x)
        if n < 3: return None, None
        x = np.sort(x)
        # Expected order statistics
        m = np.arange(1, n+1, dtype=float)
        mi = (m - 3/8) / (n + 1/4)
        c = QQPlotWidget._norm_ppf(mi)
        c = c / np.sqrt((c**2).sum())
        # Weights (simplified Shapiro-Wilk)
        a = np.zeros(n)
        half = n // 2
        a[-half:] = c[-half:]
        # W statistic
        b = np.dot(a, x)
        W = b**2 / ((x - x.mean())**2).sum()
        W = min(max(W, 0.0), 1.0)
        # p-value via log normal approximation (Royston 1992 Table 1 approximation)
        # For n in [3, 11]: use polynomial
        if n <= 11:
            gamma = np.polyval([-2.706056, 4.434685, -2.071190, -0.147981, 0.221157, 0.0], W)
            mu_w  = np.polyval([0.0, 0.459, -2.273], n**(-0.5))
            sig_w = np.exp(np.polyval([0.0, -0.0006714, 0.025054, -0.6714, 1.3822], n**(-0.5)))
        else:
            u = np.log(1 - W)
            mu_w  = np.polyval([0.0, 0.0038915, -0.083751, -0.31082, -1.5861], np.log(n))
            sig_w = np.exp(np.polyval([0.0, -0.0023776, -0.0006714, 1.3822], np.log(n)))
            gamma = (u - mu_w) / sig_w
        # One-sided p-value from standard normal
        p = 1 - 0.5*(1 + np.sign(gamma)*
            (1 - np.exp(-gamma**2*(0.196854 + 0.115194*abs(gamma) +
             0.000344*gamma**2 + 0.019527*abs(gamma)**3)**(-4))))
        p = float(np.clip(p, 1e-6, 1.0))
        return float(W), p

    def load(self, header, rows, mdv_filter=True):
        if not HAS_MPL or not HAS_NP: return
        H = [h.upper() for h in header]
        if 'CWRES' not in H: return
        try:
            ci = H.index('CWRES'); mi = H.index('MDV') if 'MDV' in H else None
            cwres = np.sort(np.array([float(r[ci]) for r in rows
                if (mi is None or not mdv_filter or r[mi]==0) and ci < len(r)
                and np.isfinite(float(r[ci]))]))
            if len(cwres) < 3: return
            n = len(cwres)
            p = (np.arange(1, n+1) - 0.5) / n
            theoretical = self._norm_ppf(p)

            self.ax.clear()
            t = THEMES[_active_theme]; bg=t['bg2']; fg=t['fg']; fg2=t['fg2']
            self.fig.patch.set_facecolor(bg); self.ax.set_facecolor(bg)
            self.ax.tick_params(colors=fg2); self.ax.xaxis.label.set_color(fg2)
            self.ax.yaxis.label.set_color(fg2); self.ax.title.set_color(fg)
            for sp in self.ax.spines.values(): sp.set_color(fg2)
            self.ax.scatter(theoretical, cwres, s=8, alpha=0.5, color=t['accent'])
            mn = min(theoretical.min(), cwres.min())
            mx = max(theoretical.max(), cwres.max())
            self.ax.plot([mn,mx],[mn,mx], color=t['red'], linewidth=1.5)
            self.ax.set_xlabel('Theoretical quantiles')
            self.ax.set_ylabel('Sample quantiles (CWRES)')
            self.ax.set_title(f'Normal QQ Plot — CWRES  (n={n})')
            self.canvas.draw()

            # Normality statistics
            W, p_val = self._shapiro_wilk_approx(cwres)
            if W is not None:
                normal = p_val > 0.05
                color = t['green'] if normal else t['red']
                verdict = 'consistent with normality' if normal else 'significant departure from normality'
                self.stats_lbl.setText(
                    f'Shapiro-Wilk  W = {W:.4f},  p = {p_val:.4f}\n'
                    f'{"✓" if normal else "✗"}  CWRES {verdict} (α = 0.05)')
                self.stats_lbl.setStyleSheet(
                    f'font-size:12px;padding:8px 16px;color:{color};')
            else:
                self.stats_lbl.setText('')
        except Exception as e:
            pass  # render errors are non-fatal

    def set_theme(self, bg, fg): pass


class DataExplorerWidget(QWidget):
    """Merged Data Viewer + Custom Plot — file browser, table, and scatter plot."""
    PAGE_SIZE = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self._header = []; self._rows = []; self._filtered_rows = []
        self._page = 0; self._model_dir = None; self._filter_rows = []
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # ── Left: file browser ────────────────────────────────────────────────
        left = QWidget(); left.setFixedWidth(180)
        lv = QVBoxLayout(left); lv.setContentsMargins(6,6,6,6); lv.setSpacing(4)
        lv.addWidget(QLabel('Files:'))
        self.file_list = QListWidget()
        self.file_list.currentItemChanged.connect(self._on_file_select)
        lv.addWidget(self.file_list, 1)
        root.addWidget(left)

        sep = QWidget(); sep.setFixedWidth(1)
        sep.setStyleSheet(f'background:{C_BORDER};')
        root.addWidget(sep)

        # ── Right: pill strip + stacked ──────────────────────────────────────
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(0,0,0,0); rv.setSpacing(0)

        # Common toolbar / info label
        toolbar = QWidget(); toolbar.setObjectName('pillBar'); toolbar.setFixedHeight(38)
        tl = QHBoxLayout(toolbar); tl.setContentsMargins(8,5,8,5); tl.setSpacing(4)
        self._de_btns = []
        for i, lbl in enumerate(['Table', 'Plot']):
            btn = QPushButton(lbl); btn.setObjectName('pillBtn')
            btn.setCheckable(True); btn.setFixedHeight(26)
            btn.clicked.connect(lambda _, n=i: self._de_switch(n))
            tl.addWidget(btn); self._de_btns.append(btn)
        tl.addSpacing(12)
        self.info_lbl = QLabel('Load a file from the browser')
        self.info_lbl.setStyleSheet(f'color:{C_FG2};font-size:11px;')
        tl.addWidget(self.info_lbl, 1)
        rv.addWidget(toolbar)

        de_sep = QWidget(); de_sep.setFixedHeight(1); de_sep.setStyleSheet(f'background:{C_BORDER};')
        rv.addWidget(de_sep)

        self.sub_tabs = QStackedWidget()

        # ── TABLE view ────────────────────────────────────────────────────────
        table_w = QWidget(); tv = QVBoxLayout(table_w); tv.setContentsMargins(4,4,4,4); tv.setSpacing(4)

        filt_row = QHBoxLayout()
        self.tbl_col_cb = QComboBox(); self.tbl_col_cb.setMinimumWidth(100)
        self.tbl_col_cb.currentTextChanged.connect(self._update_tbl_filter_vals)
        self.tbl_val_cb = QComboBox(); self.tbl_val_cb.setMinimumWidth(100); self.tbl_val_cb.setEditable(True)
        apply_btn = QPushButton('Filter'); apply_btn.setFixedWidth(70); apply_btn.clicked.connect(self._apply_tbl_filter)
        clear_btn = QPushButton('Clear');  clear_btn.setFixedWidth(60);  clear_btn.clicked.connect(self._clear_tbl_filter)
        self.prev_btn = QPushButton('<'); self.prev_btn.setFixedWidth(28); self.prev_btn.clicked.connect(self._prev_page)
        self.next_btn = QPushButton('>'); self.next_btn.setFixedWidth(28); self.next_btn.clicked.connect(self._next_page)
        self.page_lbl = QLabel(''); self.page_lbl.setFixedWidth(80)
        filt_row.addWidget(QLabel('Filter:')); filt_row.addWidget(self.tbl_col_cb)
        filt_row.addWidget(QLabel('=')); filt_row.addWidget(self.tbl_val_cb)
        filt_row.addWidget(apply_btn); filt_row.addWidget(clear_btn); filt_row.addStretch()
        filt_row.addWidget(self.prev_btn); filt_row.addWidget(self.page_lbl); filt_row.addWidget(self.next_btn)
        tv.addLayout(filt_row)

        self.data_table = QTableWidget()
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.data_table.verticalHeader().setVisible(False)
        self.data_table.verticalHeader().setDefaultSectionSize(24)
        self.data_table.setShowGrid(False)
        tv.addWidget(self.data_table, 1)
        self.sub_tabs.addWidget(table_w)

        # ── PLOT view ─────────────────────────────────────────────────────────
        plot_w = QWidget(); pv = QVBoxLayout(plot_w); pv.setContentsMargins(8,8,8,8); pv.setSpacing(8)

        if not HAS_PG or not HAS_NP:
            pv.addWidget(_placeholder('Install pyqtgraph and numpy'))
        else:
            # ── Row 1: X / Y / Colour by ─────────────────────────────────────
            row1 = QHBoxLayout(); row1.setSpacing(12)
            self.x_cb   = QComboBox(); self.x_cb.setMinimumWidth(120)
            self.y_cb   = QComboBox(); self.y_cb.setMinimumWidth(120)
            self.grp_cb = QComboBox(); self.grp_cb.setMinimumWidth(120)
            for label, cb in [('X axis:', self.x_cb), ('Y axis:', self.y_cb), ('Colour by:', self.grp_cb)]:
                lbl = QLabel(label); lbl.setFixedWidth(60)
                row1.addWidget(lbl); row1.addWidget(cb)
                if cb is not self.grp_cb: row1.addSpacing(8)
            row1.addStretch()
            pv.addLayout(row1)

            # ── Row 2: options ────────────────────────────────────────────────
            row2 = QHBoxLayout(); row2.setSpacing(16)
            self.log_x_cb = QCheckBox('Log X')
            self.log_y_cb = QCheckBox('Log Y')
            self.loess_cb = QCheckBox('LOESS');  self.loess_cb.setChecked(True)
            self.ref0_cb  = QCheckBox('Y = 0')
            self.refyx_cb = QCheckBox('Y = X')
            self.mdv_cb   = QCheckBox('Excl. MDV=1'); self.mdv_cb.setChecked(True)
            for cb in (self.log_x_cb, self.log_y_cb, self.loess_cb,
                       self.ref0_cb, self.refyx_cb, self.mdv_cb):
                row2.addWidget(cb)
            row2.addStretch()
            pv.addLayout(row2)

            # ── Row 3: filters ────────────────────────────────────────────────
            filt_grp = QGroupBox('Filters  (all ANDed together)')
            self._fv = QVBoxLayout(filt_grp); self._fv.setSpacing(4)
            add_btn = QPushButton('+ Add filter'); add_btn.setFixedWidth(120)
            add_btn.clicked.connect(self._add_filter)
            self._fv.addWidget(add_btn)
            pv.addWidget(filt_grp)

            # Connect all controls to auto-replot
            for cb in (self.x_cb, self.y_cb, self.grp_cb):
                cb.currentTextChanged.connect(self._plot)
            for cb in (self.log_x_cb, self.log_y_cb, self.loess_cb,
                       self.ref0_cb, self.refyx_cb, self.mdv_cb):
                cb.stateChanged.connect(self._plot)

            self.pw = pg.PlotWidget()
            self.pw.showGrid(x=True, y=True, alpha=0.2)
            self.pw.getAxis('bottom').enableAutoSIPrefix(False)
            self.pw.getAxis('left').enableAutoSIPrefix(False)
            self._legend = self.pw.addLegend()
            pv.addWidget(self.pw, 1)

        self.sub_tabs.addWidget(plot_w)
        rv.addWidget(self.sub_tabs, 1)
        root.addWidget(right, 1)
        self._de_switch(0)  # start on Table view

    def _de_switch(self, index):
        self.sub_tabs.setCurrentIndex(index)
        for i, btn in enumerate(self._de_btns):
            btn.setChecked(i == index)

    # ── File browser ──────────────────────────────────────────────────────────

    def load_model(self, model):
        self._model_dir = str(Path(model['path']).parent)
        self._refresh_file_list()

    def _refresh_file_list(self):
        self.file_list.clear()
        if not self._model_dir: return
        exts = {'.tab','.csv','.dat','.txt'}
        prefixes = ('sdtab','patab','catab','cotab','mutab','wres','cwtab')
        p = Path(self._model_dir)
        for f in sorted(p.iterdir()):
            if f.is_file() and (f.suffix.lower() in exts or
               any(f.name.lower().startswith(px) for px in prefixes)):
                self.file_list.addItem(QListWidgetItem(f.name))
        for sub in sorted(p.iterdir()):
            if sub.is_dir():
                for f in sorted(sub.iterdir()):
                    if f.is_file() and (f.suffix.lower() in exts or
                       any(f.name.lower().startswith(px) for px in prefixes)):
                        item = QListWidgetItem(f'{sub.name}/{f.name}')
                        item.setData(Qt.ItemDataRole.UserRole, str(f))
                        self.file_list.addItem(item)

    def _on_file_select(self, current, _):
        if not current: return
        path = current.data(Qt.ItemDataRole.UserRole)
        if not path: path = str(Path(self._model_dir) / current.text())
        if not HAS_PARSER: return
        h, r = read_table_file(path, max_rows=10000)
        if h is None: return
        self._load_data(h, r, Path(path).name)

    def _load_data(self, header, rows, name=''):
        self._header = [h.upper() for h in header]; self._rows = rows
        self._filtered_rows = rows; self._page = 0
        # Update table filter combo
        self.tbl_col_cb.clear(); self.tbl_col_cb.addItems([''] + self._header)
        # Update plot column combos
        if HAS_PG and HAS_NP:
            cols = [''] + self._header
            for cb in (self.x_cb, self.y_cb, self.grp_cb):
                cur = cb.currentText(); cb.blockSignals(True); cb.clear()
                cb.addItems(cols); cb.setCurrentIndex(max(0, cb.findText(cur)))
                cb.blockSignals(False)
            for fr in self._filter_rows:
                cur = fr.col_cb.currentText(); fr.col_cb.blockSignals(True); fr.col_cb.clear()
                fr.col_cb.addItems(cols); fr.col_cb.setCurrentIndex(max(0, fr.col_cb.findText(cur)))
                fr.col_cb.blockSignals(False); fr.set_rows(rows, self._header)
            if self.x_cb.currentIndex()==0 and 'PRED' in self._header: self.x_cb.setCurrentText('PRED')
            if self.y_cb.currentIndex()==0  and 'DV'   in self._header: self.y_cb.setCurrentText('DV')
        self._render_table()
        self.info_lbl.setText(f'{name}  ·  {len(rows)} rows, {len(header)} columns')

    # Also accept (header, rows) directly (called from EvaluationTab for sdtab auto-load)
    def load(self, header, rows):
        if header: self._load_data(header, rows)

    # ── Table view ────────────────────────────────────────────────────────────

    def _update_tbl_filter_vals(self):
        col = self.tbl_col_cb.currentText()
        self.tbl_val_cb.clear(); self.tbl_val_cb.addItem('')
        if col and col in self._header:
            ci = self._header.index(col)
            vals = sorted(set(str(r[ci]) for r in self._rows if ci < len(r)))
            self.tbl_val_cb.addItems(vals[:300])

    def _apply_tbl_filter(self):
        col = self.tbl_col_cb.currentText(); val = self.tbl_val_cb.currentText().strip()
        if not col or not val:
            self._filtered_rows = self._rows
        elif col in self._header:
            ci = self._header.index(col)
            self._filtered_rows = [r for r in self._rows if str(r[ci]) == val]
        self._page = 0; self._render_table()

    def _clear_tbl_filter(self):
        self._filtered_rows = self._rows; self._page = 0
        self.tbl_val_cb.setCurrentText(''); self._render_table()

    def _n_pages(self): return max(1, math.ceil(len(self._filtered_rows)/self.PAGE_SIZE))
    def _prev_page(self):
        if self._page > 0: self._page -= 1; self._render_table()
    def _next_page(self):
        if self._page < self._n_pages()-1: self._page += 1; self._render_table()

    def _render_table(self):
        if not self._header: return
        start = self._page * self.PAGE_SIZE
        page_rows = self._filtered_rows[start:start+self.PAGE_SIZE]
        self.data_table.setColumnCount(len(self._header))
        self.data_table.setHorizontalHeaderLabels(self._header)
        self.data_table.setRowCount(len(page_rows))
        for row_i, row in enumerate(page_rows):
            for col_i, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
                self.data_table.setItem(row_i, col_i, item)
        self.data_table.resizeColumnsToContents()
        self.page_lbl.setText(f'{self._page+1}/{self._n_pages()}')
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < self._n_pages()-1)
        n_tot = len(self._filtered_rows); n_all = len(self._rows)
        filt_str = f' (filtered from {n_all})' if n_tot != n_all else ''
        self.info_lbl.setText(
            f'{n_tot} rows{filt_str}, {len(self._header)} cols  ·  '
            f'rows {start+1}–{min(start+self.PAGE_SIZE,n_tot)} of {n_tot}')

    # ── Plot view — filters ───────────────────────────────────────────────────

    def _add_filter(self):
        fr = FilterRow(self._header); fr.set_rows(self._rows, self._header)
        fr.removed.connect(self._remove_filter)
        fr.changed.connect(self._plot)
        self._filter_rows.append(fr)
        self._fv.insertWidget(self._fv.count()-1, fr)

    def _remove_filter(self, fr):
        self._filter_rows.remove(fr); self._fv.removeWidget(fr); fr.deleteLater()

    # ── Plot view — render ────────────────────────────────────────────────────

    def set_theme(self, bg, fg):
        if HAS_PG and hasattr(self, 'pw'): self.pw.setBackground(bg)

    def _plot(self):
        if not HAS_PG or not HAS_NP: return
        xcol = self.x_cb.currentText(); ycol = self.y_cb.currentText()
        if not xcol or not ycol: return
        H = self._header
        if xcol not in H or ycol not in H: return
        self.pw.clear()
        try: self._legend.clear()
        except Exception: pass
        xi = H.index(xcol); yi = H.index(ycol)

        def passes(row):
            if self.mdv_cb.isChecked() and 'MDV' in H:
                try:
                    if float(row[H.index('MDV')]) != 0: return False
                except (ValueError, TypeError): pass
            return all(fr.matches(row, H) for fr in self._filter_rows)

        rows_f = [r for r in self._rows if passes(r)]
        if not rows_f: return

        gcol = self.grp_cb.currentText()
        if gcol and gcol in H:
            gi = H.index(gcol); groups = {}
            for row in rows_f:
                k = str(row[gi])
                if k not in groups: groups[k] = []
                groups[k].append(row)
        else: groups = {'All': rows_f}

        pal = ['#569cd6','#4ec994','#ce9178','#dcdcaa','#c586c0',
               '#9cdcfe','#f44747','#6a9955','#4fc1ff','#d7ba7d']

        for gi_, (gname, grows) in enumerate(groups.items()):
            color = pal[gi_ % len(pal)]
            try:
                x = np.array([float(r[xi]) for r in grows])
                y = np.array([float(r[yi]) for r in grows])
            except Exception: continue
            ok = np.isfinite(x) & np.isfinite(y); x,y = x[ok],y[ok]
            if len(x)==0: continue
            lbl = gname if len(groups)>1 else None
            qc = QColor(color)
            self.pw.addItem(pg.ScatterPlotItem(x=x,y=y,pen=None,
                brush=pg.mkBrush(qc.red(),qc.green(),qc.blue(),110),size=6,name=lbl))
            if self.loess_cb.isChecked():
                xlo,ylo = loess(x,y)
                if xlo is not None: self.pw.plot(xlo,ylo,pen=pg.mkPen(color,width=2))

        self.pw.setLogMode(x=self.log_x_cb.isChecked(), y=self.log_y_cb.isChecked())
        self.pw.setLabel('bottom',xcol); self.pw.setLabel('left',ycol)

        if self.ref0_cb.isChecked():
            try:
                ax = np.array([float(r[xi]) for r in rows_f])
                self.pw.plot([ax[np.isfinite(ax)].min(), ax[np.isfinite(ax)].max()],[0,0],
                             pen=pg.mkPen('#aaaaaa',width=1.5,style=Qt.PenStyle.DashLine))
            except Exception: pass

        if self.refyx_cb.isChecked():
            try:
                ax=np.array([float(r[xi]) for r in rows_f]); ay=np.array([float(r[yi]) for r in rows_f])
                mn=min(ax[np.isfinite(ax)].min(),ay[np.isfinite(ay)].min())
                mx=max(ax[np.isfinite(ax)].max(),ay[np.isfinite(ay)].max())
                self.pw.plot([mn,mx],[mn,mx],pen=pg.mkPen(C_RED,width=1.5))
            except Exception: pass

        filt_desc = '  '.join(
            f'[{fr.col_cb.currentText()} {fr.op_cb.currentText()} {fr.val_cb.currentText()}]'
            for fr in self._filter_rows
            if fr.col_cb.currentText() and fr.val_cb.currentText())
        self.pw.setTitle(f'{ycol} vs {xcol}  {filt_desc}')

class EvaluationTab(QWidget):
    status_msg = pyqtSignal(str)

    # Section indices
    SEC_GOF   = 0
    SEC_INDF  = 1
    SEC_WFALL = 2
    SEC_CONV  = 3
    SEC_DATA  = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._header=None; self._rows=None; self._model=None
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        # ── Context + file bar ────────────────────────────────────────────────
        top_bar = QWidget(); top_bar.setObjectName('evalTopBar')
        tbl = QVBoxLayout(top_bar); tbl.setContentsMargins(8,6,8,6); tbl.setSpacing(4)

        ctx_row = QHBoxLayout()
        self._model_lbl = QLabel('No model selected')
        self._model_lbl.setStyleSheet(f'color:{C_FG2};font-size:12px;font-weight:600;')
        self._table_lbl = QLabel('')
        self._table_lbl.setStyleSheet(f'color:{C_FG2};font-size:12px;')
        ctx_row.addWidget(self._model_lbl); ctx_row.addSpacing(12)
        ctx_row.addWidget(self._table_lbl); ctx_row.addStretch()
        tbl.addLayout(ctx_row)

        file_row = QHBoxLayout(); file_row.setSpacing(6)
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText('sdtab / output table file…')
        br = QPushButton('Browse…'); br.clicked.connect(self._browse)
        ld = QPushButton('Load'); ld.setObjectName('primary'); ld.clicked.connect(self._load)
        self.mdv_cb = QCheckBox('Exclude MDV=1'); self.mdv_cb.setChecked(True)
        self.mdv_cb.stateChanged.connect(self._reload)
        file_row.addWidget(self.file_edit, 1)
        file_row.addWidget(br); file_row.addWidget(ld); file_row.addWidget(self.mdv_cb)
        tbl.addLayout(file_row)
        v.addWidget(top_bar)

        # ── Pill navigation strip ─────────────────────────────────────────────
        pill_bar = QWidget(); pill_bar.setObjectName('pillBar'); pill_bar.setFixedHeight(40)
        pl = QHBoxLayout(pill_bar); pl.setContentsMargins(12,6,12,6); pl.setSpacing(4)

        self._pill_btns = []
        pill_labels = ['GOF', 'Individual Fits', 'OFV Waterfall', 'Convergence', 'Data Explorer']
        for i, lbl in enumerate(pill_labels):
            btn = QPushButton(lbl)
            btn.setObjectName('pillBtn')
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda _, n=i: self._switch_section(n))
            pl.addWidget(btn)
            self._pill_btns.append(btn)
        pl.addStretch()
        v.addWidget(pill_bar)

        # ── Thin separator ────────────────────────────────────────────────────
        sep = QWidget(); sep.setFixedHeight(1)
        sep.setStyleSheet(f'background:{C_BORDER};')
        v.addWidget(sep)

        # ── Stacked content ───────────────────────────────────────────────────
        self._stack = QStackedWidget()

        # 0 — GOF panel (GOF 2×2 + CWRES Hist + QQ Plot via inner pill)
        gof_panel = QWidget(); gv = QVBoxLayout(gof_panel); gv.setContentsMargins(0,0,0,0); gv.setSpacing(0)
        # Inner sub-strip for GOF
        inner_bar = QWidget(); inner_bar.setFixedHeight(34)
        il = QHBoxLayout(inner_bar); il.setContentsMargins(8,4,8,4); il.setSpacing(3)
        self._gof_btns = []
        for i, lbl in enumerate(['GOF 2×2', 'CWRES Hist', 'QQ Plot', 'ETA vs Cov']):
            btn = QPushButton(lbl); btn.setObjectName('innerPillBtn')
            btn.setCheckable(True); btn.setFixedHeight(24)
            btn.clicked.connect(lambda _, n=i: self._switch_gof(n))
            il.addWidget(btn); self._gof_btns.append(btn)
        il.addStretch()
        gv.addWidget(inner_bar)
        self._gof_stack = QStackedWidget()
        self.gof       = GOFWidget()
        self.cwres_hist= CWRESHistWidget()
        self.qq_plot   = QQPlotWidget()
        self.eta_cov   = ETACovWidget()
        self._gof_stack.addWidget(self.gof)
        self._gof_stack.addWidget(self.cwres_hist)
        self._gof_stack.addWidget(self.qq_plot)
        self._gof_stack.addWidget(self.eta_cov)
        gv.addWidget(self._gof_stack, 1)
        self._stack.addWidget(gof_panel)

        # 1 — Individual Fits
        self.indfit = IndFitWidget()
        self._stack.addWidget(self.indfit)

        # 2 — OFV Waterfall
        self.waterfall = WaterfallWidget()
        self._stack.addWidget(self.waterfall)

        # 3 — Convergence
        self.conv = ConvergenceWidget()
        self._stack.addWidget(self.conv)

        # 4 — Data Explorer
        self.data_explorer = DataExplorerWidget()
        self._stack.addWidget(self.data_explorer)

        v.addWidget(self._stack, 1)

        # Initialise selection
        self._switch_section(0)
        self._switch_gof(0)

    def _switch_section(self, index):
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._pill_btns):
            btn.setChecked(i == index)

    def _switch_gof(self, index):
        self._gof_stack.setCurrentIndex(index)
        for i, btn in enumerate(self._gof_btns):
            btn.setChecked(i == index)

    def _browse(self):
        d = str(Path(self._model['path']).parent) if self._model else str(HOME)
        f,_ = QFileDialog.getOpenFileName(self,'Select table file',d,'All files (*)')
        if f: self.file_edit.setText(f)

    def _load(self):
        path=self.file_edit.text().strip()
        if not path or not Path(path).is_file(): self.status_msg.emit('File not found'); return
        if not HAS_PARSER: self.status_msg.emit('parser.py not available'); return
        h,r=read_table_file(path,max_rows=15000)
        if h is None: self.status_msg.emit('Could not parse file'); return
        self._header=h; self._rows=r; self._reload()
        fname = Path(path).name
        self._table_lbl.setText(f'·  {fname}  ({len(r)} rows, {len(h)} cols)')
        self.status_msg.emit(f'Loaded {len(r)} rows, {len(h)} columns — {fname}')

    def _reload(self):
        if self._header is None: return
        mdv = self.mdv_cb.isChecked()
        self.gof.load(self._header, self._rows, mdv)
        self.indfit.load(self._header, self._rows)
        self.cwres_hist.load(self._header, self._rows, mdv)
        self.qq_plot.load(self._header, self._rows, mdv)
        self.eta_cov.load(self._header, self._rows)
        self.data_explorer.load(self._header, self._rows)

    def load_model(self, model):
        self._model = model
        self._model_lbl.setText(f'Model: {model.get("stem","")}')
        self._table_lbl.setText('')
        if not model.get('lst_path'): return

        # Search for sdtab in both lst directory AND model directory
        # (PSN puts .lst in a subdir; sdtab usually lives next to the .mod file)
        search_dirs = []
        lst_dir = Path(model['lst_path']).parent
        mod_dir = Path(model['path']).parent
        search_dirs.append(lst_dir)
        if mod_dir != lst_dir:
            search_dirs.append(mod_dir)

        runno = model.get('table_runno', '')
        stem  = model.get('stem', '')

        # Build candidate prefixes — case-insensitive glob
        prefixes = []
        if runno:
            prefixes += [f'sdtab{runno}', f'sdtabrun{runno}']
        prefixes += [f'sdtab{stem}', 'sdtab']

        found = None
        for d in search_dirs:
            if not d.is_dir(): continue
            all_files = sorted(d.iterdir())
            for prefix in prefixes:
                for f in all_files:
                    if f.is_file() and f.name.lower().startswith(prefix.lower()):
                        found = f; break
                if found: break
            if found: break

        if found:
            self.file_edit.setText(str(found))
            self._load()
        self._try_phi(model)
        self._try_ext(model)
        self.data_explorer.load_model(model)

    def _try_phi(self, model):
        if not HAS_PARSER: return
        stem=model['stem']
        for base in [Path(model['lst_path']).parent, Path(model['path']).parent]:
            for fn in [f'{stem}.phi', f'{stem}/{stem}.phi']:
                p=base/fn
                if p.is_file():
                    try:
                        r=parse_phi_file(str(p))
                        if r.get('obj'): self.waterfall.load(r)
                    except Exception: pass
                    return

    def _try_ext(self, model):
        if not HAS_PARSER: return
        stem=model['stem']
        for base in [Path(model['lst_path']).parent, Path(model['path']).parent]:
            for fn in [f'{stem}.ext', f'{stem}/{stem}.ext']:
                p=base/fn
                if p.is_file():
                    try:
                        r=parse_ext_file(str(p))
                        if r: self.conv.load(r)
                    except Exception: pass
                    return


# ══════════════════════════════════════════════════════════════════════════════
# VPC Tab
# ══════════════════════════════════════════════════════════════════════════════

def _find_rscript():
    import shutil as sh
    r = sh.which('Rscript')
    if r: return r
    if not IS_WIN:
        try:
            shell = os.environ.get('SHELL','/bin/sh')
            rv = subprocess.run([shell,'-l','-c','which Rscript'],
                                capture_output=True, text=True, timeout=5)
            found = rv.stdout.strip()
            if found and Path(found).is_file(): return found
        except Exception: pass
    return None

def _sanitize_r(s):
    return s.replace('\\','/').replace('"','\\"')

def _check_r_packages():
    rscript = _find_rscript()
    if not rscript: return False, {}
    try:
        rv = subprocess.run(
            [rscript,'-e',
             'pkgs<-rownames(installed.packages());'
             'cat(paste(c("vpc","xpose","xpose4")[c("vpc","xpose","xpose4")%in%pkgs],collapse=","))'],
            capture_output=True, text=True, timeout=15, env=get_login_env())
        installed = [p.strip() for p in rv.stdout.strip().split(',') if p.strip()]
        avail = {p: p in installed for p in ('vpc','xpose','xpose4')}
        return True, avail
    except Exception:
        return False, {}


class VPCWorker(QThread):
    line_out  = pyqtSignal(str)
    finished  = pyqtSignal(bool, str)   # success, image_path_or_error

    def __init__(self, script_path, output_png, rscript, env):
        super().__init__()
        self._script = script_path
        self._png    = output_png
        self._rs     = rscript
        self._env    = env

    def run(self):
        try:
            proc = subprocess.Popen(
                [self._rs, self._script],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, env=self._env,
                cwd=str(Path(self._script).parent))
            stdout_lines = []
            for line in iter(proc.stdout.readline,''):
                self.line_out.emit(line.rstrip())
                stdout_lines.append(line)
            try:
                proc.wait(timeout=300)  # 5 minute hard timeout
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()
                self.finished.emit(False, 'R script timed out after 5 minutes')
                return
            stdout_all = ''.join(stdout_lines)
            png_ok = Path(self._png).is_file() and Path(self._png).stat().st_size > 1000
            if 'NMGUI_VPC_OK' in stdout_all and png_ok:
                self.finished.emit(True, self._png)
            elif png_ok:
                # Script succeeded but didn't print protocol token (some R setups)
                self.finished.emit(True, self._png)
            else:
                # Extract error
                err = ''
                for line in stdout_lines:
                    if 'NMGUI_VPC_ERROR:' in line:
                        err = line.split('NMGUI_VPC_ERROR:',1)[1].strip(); break
                if not err: err = 'R script did not produce a valid image'
                self.finished.emit(False, err)
        except Exception as e:
            self.finished.emit(False, str(e))


class VPCTab(QWidget):
    status_msg = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model   = None
        self._worker  = None
        self._rscript = None
        self._pkg_avail = {'vpc': False, 'xpose': False, 'xpose4': False}
        self._build_ui()
        QTimer.singleShot(500, self._check_r)

    def _build_ui(self):
        v = QVBoxLayout(self); v.setContentsMargins(6,6,6,6); v.setSpacing(6)

        # ── Settings panel ────────────────────────────────────────────────────
        settings_grp = QGroupBox('VPC settings')
        sg = QGridLayout(settings_grp); sg.setSpacing(6)

        # Tool
        self.tool_cb = QComboBox()
        self.tool_cb.addItems(['vpc','xpose','xpose4'])
        self.tool_cb.currentTextChanged.connect(self._on_tool_change)

        # VPC folder (PsN output)
        self.vpc_folder_edit = QLineEdit()
        self.vpc_folder_edit.setPlaceholderText('PsN vpc output folder (contains m1/, vpc_results.csv…)')
        vpc_browse = QPushButton('Browse…'); vpc_browse.clicked.connect(self._browse_vpc)

        # Run directory (for xpose sdtab files)
        self.run_dir_edit = QLineEdit()
        self.run_dir_edit.setPlaceholderText('Run directory with sdtab files (xpose only)')
        run_browse = QPushButton('Browse…'); run_browse.clicked.connect(self._browse_run)

        # Run number
        self.runno_edit = QLineEdit(); self.runno_edit.setPlaceholderText('e.g. 001')
        self.runno_edit.setFixedWidth(80)

        # Options
        self.pred_corr_cb = QCheckBox('Prediction-corrected (pcVPC)')
        self.log_y_cb     = QCheckBox('Log Y axis')
        self.stratify_edit = QLineEdit(); self.stratify_edit.setPlaceholderText('Stratify by column (optional)')
        self.stratify_edit.setFixedWidth(180)

        # PI / CI
        self.pi_lo = QDoubleSpinBox(); self.pi_lo.setRange(0,0.5); self.pi_lo.setValue(0.05); self.pi_lo.setSingleStep(0.025); self.pi_lo.setDecimals(3); self.pi_lo.setFixedWidth(70)
        self.pi_hi = QDoubleSpinBox(); self.pi_hi.setRange(0.5,1); self.pi_hi.setValue(0.95); self.pi_hi.setSingleStep(0.025); self.pi_hi.setDecimals(3); self.pi_hi.setFixedWidth(70)
        self.ci_lo = QDoubleSpinBox(); self.ci_lo.setRange(0,0.5); self.ci_lo.setValue(0.05); self.ci_lo.setSingleStep(0.025); self.ci_lo.setDecimals(3); self.ci_lo.setFixedWidth(70)
        self.ci_hi = QDoubleSpinBox(); self.ci_hi.setRange(0.5,1); self.ci_hi.setValue(0.95); self.ci_hi.setSingleStep(0.025); self.ci_hi.setDecimals(3); self.ci_hi.setFixedWidth(70)
        self.lloq_edit = QLineEdit(); self.lloq_edit.setPlaceholderText('LLOQ (optional)'); self.lloq_edit.setFixedWidth(100)
        self.nbins_sb  = QDoubleSpinBox(); self.nbins_sb.setRange(3,50); self.nbins_sb.setValue(10); self.nbins_sb.setDecimals(0); self.nbins_sb.setFixedWidth(60)

        row = 0
        sg.addWidget(QLabel('Backend:'),      row,0); sg.addWidget(self.tool_cb,         row,1)
        sg.addWidget(QLabel('Run no:'),       row,2); sg.addWidget(self.runno_edit,       row,3)
        sg.addWidget(self.pred_corr_cb,       row,4); sg.addWidget(self.log_y_cb,         row,5)
        row+=1
        sg.addWidget(QLabel('VPC folder:'),   row,0)
        vpc_row = QHBoxLayout(); vpc_row.addWidget(self.vpc_folder_edit,1); vpc_row.addWidget(vpc_browse)
        vpc_w = QWidget(); vpc_w.setLayout(vpc_row)
        sg.addWidget(vpc_w,                   row,1,1,5)
        row+=1
        self.run_dir_lbl = QLabel('Run dir:')
        sg.addWidget(self.run_dir_lbl,        row,0)
        run_row = QHBoxLayout(); run_row.addWidget(self.run_dir_edit,1); run_row.addWidget(run_browse)
        run_w = QWidget(); run_w.setLayout(run_row)
        self.run_dir_w = run_w
        sg.addWidget(run_w,                   row,1,1,5)
        row+=1
        sg.addWidget(QLabel('Stratify:'),     row,0); sg.addWidget(self.stratify_edit,   row,1)
        sg.addWidget(QLabel('PI:'),           row,2)
        pi_row=QHBoxLayout(); pi_row.addWidget(self.pi_lo); pi_row.addWidget(QLabel('–')); pi_row.addWidget(self.pi_hi)
        pi_w=QWidget(); pi_w.setLayout(pi_row); sg.addWidget(pi_w, row,3)
        sg.addWidget(QLabel('CI:'),           row,4)
        ci_row=QHBoxLayout(); ci_row.addWidget(self.ci_lo); ci_row.addWidget(QLabel('–')); ci_row.addWidget(self.ci_hi)
        ci_w=QWidget(); ci_w.setLayout(ci_row); sg.addWidget(ci_w, row,5)
        row+=1
        sg.addWidget(QLabel('LLOQ:'),         row,0); sg.addWidget(self.lloq_edit,       row,1)
        sg.addWidget(QLabel('Bins:'),         row,2); sg.addWidget(self.nbins_sb,         row,3)

        v.addWidget(settings_grp)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self.run_btn  = QPushButton('Generate VPC'); self.run_btn.clicked.connect(self._run)
        self.run_btn.setStyleSheet(f'background:{C_GREEN};color:#000;font-weight:bold;padding:5px 18px;')
        self.stop_btn = QPushButton('Stop'); self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)
        self.r_status_lbl = QLabel('Checking R…')
        self.r_status_lbl.setStyleSheet(f'color:{C_FG2};')
        btn_row.addWidget(self.run_btn); btn_row.addWidget(self.stop_btn)
        btn_row.addStretch(); btn_row.addWidget(self.r_status_lbl)
        v.addLayout(btn_row)

        # ── Splitter: image | console+script ─────────────────────────────────
        spl = QSplitter(Qt.Orientation.Horizontal)

        # VPC image panel
        img_w = QWidget(); img_v = QVBoxLayout(img_w); img_v.setContentsMargins(0,0,0,0); img_v.setSpacing(0)

        # Toolbar above image
        img_toolbar = QWidget(); img_toolbar.setFixedHeight(36)
        itl = QHBoxLayout(img_toolbar); itl.setContentsMargins(8,4,8,4); itl.setSpacing(8)
        self.tool_lbl = QLabel('')
        self.tool_lbl.setStyleSheet(f'color:{C_FG2};font-size:11px;')
        self._open_btn   = QPushButton('Open in viewer')
        self._savepng_btn = QPushButton('Save high-res PNG…')
        self._savepdf_btn = QPushButton('Save PDF…')
        for b in (self._open_btn, self._savepng_btn, self._savepdf_btn):
            b.setEnabled(False)
            b.setFixedHeight(26)
        self._open_btn.clicked.connect(self._open_in_viewer)
        self._savepng_btn.clicked.connect(self._export_hires_png)
        self._savepdf_btn.clicked.connect(self._export_pdf)
        itl.addWidget(self.tool_lbl, 1)
        itl.addWidget(self._open_btn)
        itl.addWidget(self._savepng_btn)
        itl.addWidget(self._savepdf_btn)

        self.img_lbl = QLabel('No VPC generated yet')
        self.img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_lbl.setStyleSheet(f'color:{C_FG2};font-size:14px;')
        self.img_lbl.setMinimumSize(400,300)
        self.img_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._last_png = None   # path to most recently generated PNG
        self._last_script_txt = ''  # R script text for re-running at higher res

        img_v.addWidget(img_toolbar); img_v.addWidget(self.img_lbl, 1)
        spl.addWidget(img_w)

        # Right panel: console + R script with pill navigation
        right_panel = QWidget(); rp_v = QVBoxLayout(right_panel); rp_v.setContentsMargins(0,0,0,0); rp_v.setSpacing(0)

        vpc_pill_bar = QWidget(); vpc_pill_bar.setObjectName('pillBar'); vpc_pill_bar.setFixedHeight(36)
        vpl = QHBoxLayout(vpc_pill_bar); vpl.setContentsMargins(8,4,8,4); vpl.setSpacing(4)
        self._vpc_btns = []
        for i, lbl in enumerate(['Console', 'R Script']):
            btn = QPushButton(lbl); btn.setObjectName('pillBtn')
            btn.setCheckable(True); btn.setFixedHeight(26)
            btn.clicked.connect(lambda _, n=i: self._vpc_panel_switch(n))
            vpl.addWidget(btn); self._vpc_btns.append(btn)
        vpl.addStretch()
        rp_v.addWidget(vpc_pill_bar)

        vpc_sep = QWidget(); vpc_sep.setFixedHeight(1); vpc_sep.setStyleSheet(f'background:{C_BORDER};')
        rp_v.addWidget(vpc_sep)

        self._right_tabs = QStackedWidget()

        self.console = QPlainTextEdit(); self.console.setReadOnly(True)
        self.console.setFont(QFont('Menlo' if IS_MAC else 'Consolas',11))
        self.console.setMaximumBlockCount(2000)
        self._right_tabs.addWidget(self.console)

        # R Script panel — editable, with controls
        rscript_w = QWidget(); rv = QVBoxLayout(rscript_w); rv.setContentsMargins(0,0,0,0); rv.setSpacing(0)
        rscript_ctrl = QWidget(); rscript_ctrl.setFixedHeight(34)
        rcl = QHBoxLayout(rscript_ctrl); rcl.setContentsMargins(8,4,8,4); rcl.setSpacing(8)
        self.custom_script_cb = QCheckBox('Use custom script (edits below)')
        self.custom_script_cb.setToolTip(
            'When checked, the script below is used as-is.\n'
            'When unchecked, the script is rebuilt from settings on each run.')
        reset_btn = QPushButton('Reset from settings')
        reset_btn.setFixedHeight(24)
        reset_btn.setToolTip('Regenerate the R script from the current settings panel')
        reset_btn.clicked.connect(self._reset_r_script)
        rcl.addWidget(self.custom_script_cb); rcl.addStretch(); rcl.addWidget(reset_btn)
        self.r_script_edit = QPlainTextEdit()
        self.r_script_edit.setFont(QFont('Menlo' if IS_MAC else 'Consolas',11))
        self.r_script_edit.setPlaceholderText('Generate a VPC to see and edit the R script here…')
        rv.addWidget(rscript_ctrl); rv.addWidget(self.r_script_edit, 1)
        self._right_tabs.addWidget(rscript_w)

        rp_v.addWidget(self._right_tabs, 1)
        spl.addWidget(right_panel)
        spl.setSizes([640, 400])
        v.addWidget(spl,1)
        self._vpc_panel_switch(0)
        self._on_tool_change(self.tool_cb.currentText())

    def _on_tool_change(self, tool):
        show_run_dir = (tool == 'xpose')
        self.run_dir_lbl.setVisible(show_run_dir)
        self.run_dir_w.setVisible(show_run_dir)

    def _check_r(self):
        def _do():
            has_r, pkgs = _check_r_packages()
            self._rscript = _find_rscript()
            self._pkg_avail = pkgs
            if not has_r:
                self.r_status_lbl.setText('R not found'); return
            parts = []
            for p in ('vpc','xpose','xpose4'):
                parts.append(f'{p} ✓' if pkgs.get(p) else f'{p} ✗')
                # Grey out unavailable tools
            self.r_status_lbl.setText('R: ' + '  '.join(parts))
            # Update tool combo
            for i in range(self.tool_cb.count()):
                t = self.tool_cb.itemText(i)
                # Can't easily grey items in QComboBox without delegates; just update label
        threading.Thread(target=_do, daemon=True).start()

    def _browse_vpc(self):
        d = str(Path(self._model['path']).parent) if self._model else str(HOME)
        folder = QFileDialog.getExistingDirectory(self,'Select PsN VPC output folder',d)
        if folder: self.vpc_folder_edit.setText(folder)

    def _browse_run(self):
        d = str(Path(self._model['path']).parent) if self._model else str(HOME)
        folder = QFileDialog.getExistingDirectory(self,'Select run directory',d)
        if folder: self.run_dir_edit.setText(folder)

    def load_model(self, model):
        self._model = model
        # Run number: prefer table_runno from sdtab, fall back to stem digits
        runno = model.get('table_runno','')
        if not runno:
            # Extract trailing digits from stem e.g. run104 -> 104
            m = re.search(r'(\d+)$', model.get('stem',''))
            if m: runno = m.group(1)
        if runno:
            self.runno_edit.setText(runno)
        # Auto-populate VPC folder: look for vpc_* subdirs near the model
        if model.get('lst_path'):
            lst_dir = Path(model['lst_path']).parent
            vpc_dirs = sorted(lst_dir.glob('vpc_*'))
            if vpc_dirs: self.vpc_folder_edit.setText(str(vpc_dirs[-1]))
            # Run dir for xpose — use lst directory (where sdtabs live)
            self.run_dir_edit.setText(str(lst_dir))

    def _build_r_script(self):
        tool       = self.tool_cb.currentText()
        vpc_folder = self.vpc_folder_edit.text().strip()
        run_dir    = self.run_dir_edit.text().strip() or vpc_folder
        runno      = self.runno_edit.text().strip() or '001'
        pred_corr  = 'TRUE' if self.pred_corr_cb.isChecked() else 'FALSE'
        log_y      = self.log_y_cb.isChecked()
        strat      = self.stratify_edit.text().strip()
        pi_lo      = self.pi_lo.value(); pi_hi = self.pi_hi.value()
        ci_lo      = self.ci_lo.value(); ci_hi = self.ci_hi.value()
        lloq_raw   = self.lloq_edit.text().strip()
        lloq       = lloq_raw if lloq_raw else 'NULL'
        nbins      = int(self.nbins_sb.value())

        r_vpc   = _sanitize_r(vpc_folder)
        r_run   = _sanitize_r(run_dir)
        r_out   = _sanitize_r(str(Path(vpc_folder) / 'nmgui_vpc.png'))

        strat_line = ''
        if strat:
            vars_ = [_sanitize_r(v.strip()) for v in strat.split(',') if v.strip()]
            if len(vars_)==1:
                strat_line = f'stratify = "{vars_[0]}",'
            else:
                strat_line = 'stratify = c(' + ','.join(f'"{v}"' for v in vars_) + '),'
        log_line = 'log_y = TRUE,' if log_y else ''

        if tool == 'vpc':
            script = f'''# NMGUI VPC — tool: vpc
library(vpc)
library(ggplot2)

tryCatch({{
  vpc_plot <- vpc(
    psn_folder = "{r_vpc}",
    pred_corr  = {pred_corr},
    lloq       = {lloq},
    bins       = "auto",
    n_bins     = {nbins},
    {strat_line}
    pi         = c({pi_lo}, {pi_hi}),
    ci         = c({ci_lo}, {ci_hi}),
    {log_line}
    show = list(obs_dv=TRUE, obs_ci=TRUE, pi=TRUE, pi_as_area=TRUE, pi_ci=TRUE, obs_median=TRUE)
  )
  if (is.null(vpc_plot)) stop("vpc() returned NULL")
  ggsave("{r_out}", vpc_plot, width=8, height=6, dpi=150)
  cat("NMGUI_VPC_OK\\n")
}}, error=function(e) {{
  cat("NMGUI_VPC_ERROR:", conditionMessage(e), "\\n")
}})
'''
        elif tool == 'xpose':
            vpc_opt_parts = [f'n_bins={nbins}']
            if lloq_raw: vpc_opt_parts.append(f'lloq={lloq_raw}')
            if pred_corr=='TRUE': vpc_opt_parts.append('pred_corr=TRUE')
            vpc_data_parts = [f'opt=vpc_opt({",".join(vpc_opt_parts)})',
                              f'psn_folder="{r_vpc}"']
            if strat:
                vars_=[_sanitize_r(v.strip()) for v in strat.split(',') if v.strip()]
                if len(vars_)==1: vpc_data_parts.append(f'stratify="{vars_[0]}"')
                else: vpc_data_parts.append('stratify=c('+','.join(f'"{v}"' for v in vars_)+')')
            vpc_call = 'vpc()'
            if log_y: vpc_call = 'vpc() + ggplot2::scale_y_log10()'
            script = f'''# NMGUI VPC — tool: xpose
library(xpose)
library(ggplot2)

tryCatch({{
  xpdb <- xpose_data(runno="{runno}", dir="{r_run}/")
  vpc_plot <- xpdb %>%
    vpc_data({", ".join(vpc_data_parts)}) %>%
    {vpc_call}
  if (is.null(vpc_plot)) stop("xpose vpc() returned NULL")
  ggsave("{r_out}", vpc_plot, width=8, height=6, dpi=150)
  cat("NMGUI_VPC_OK\\n")
}}, error=function(e) {{
  cat("NMGUI_VPC_ERROR:", conditionMessage(e), "\\n")
  cat("  sdtab files in run dir:", paste(list.files("{r_run}", pattern="^sdtab"), collapse=", "), "\\n")
}})
'''
        else:  # xpose4
            script = f'''# NMGUI VPC — tool: xpose4
library(xpose4)

tryCatch({{
  vpctab_files <- list.files("{r_vpc}", pattern="^vpctab", full.names=TRUE)
  if (length(vpctab_files)==0) stop("No vpctab file found in VPC folder")
  vpc_info <- file.path("{r_vpc}", "vpc_results.csv")
  if (!file.exists(vpc_info)) stop("vpc_results.csv not found in VPC folder")
  png("{r_out}", width=1200, height=900, res=150)
  print(xpose.VPC(vpctab=vpctab_files[1], vpc.info=vpc_info))
  dev.off()
  cat("NMGUI_VPC_OK\\n")
}}, error=function(e) {{
  try(dev.off(), silent=TRUE)
  cat("NMGUI_VPC_ERROR:", conditionMessage(e), "\\n")
}})
'''
        return script, str(Path(vpc_folder) / 'nmgui_vpc.png')

    def _run(self):
        vpc_folder = self.vpc_folder_edit.text().strip()
        if not vpc_folder or not Path(vpc_folder).is_dir():
            QMessageBox.warning(self,'Missing folder','Select a valid PsN VPC output folder first.')
            return
        if not self._rscript:
            QMessageBox.warning(self,'R not found','Rscript not found. Is R installed and on PATH?')
            return

        _, output_png = self._build_r_script()   # always need output_png

        if self.custom_script_cb.isChecked():
            # Use whatever is in the editor — user may have tweaked it
            script_txt = self.r_script_edit.toPlainText().strip()
            if not script_txt:
                QMessageBox.warning(self,'Empty script',
                    'Custom script is empty. Uncheck "Use custom script" to rebuild from settings.')
                return
        else:
            # Rebuild from settings
            script_txt, output_png = self._build_r_script()
            self._last_script_txt = script_txt
            self.r_script_edit.setPlainText(script_txt)

        script_path = str(Path(vpc_folder) / 'nmgui_vpc_script.R')
        # Delete stale PNG
        if Path(output_png).is_file():
            try: Path(output_png).unlink()
            except Exception: pass
        try:
            Path(script_path).write_text(script_txt, 'utf-8')
        except Exception as e:
            QMessageBox.critical(self,'Error',f'Cannot write R script:\n{e}'); return
        self.console.clear()
        self.console.appendPlainText(
            f'Running {self.tool_cb.currentText()} VPC'
            f'{"  [custom script]" if self.custom_script_cb.isChecked() else ""}…\n')
        self.run_btn.setEnabled(False); self.stop_btn.setEnabled(True)
        self.tool_lbl.setText(f'Backend: {self.tool_cb.currentText()}')
        if self._worker:
            try: self._worker.line_out.disconnect()
            except Exception: pass
            try: self._worker.finished.disconnect()
            except Exception: pass
        self._worker = VPCWorker(script_path, output_png, self._rscript, get_login_env())
        self._worker.line_out.connect(self._on_line)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _reset_r_script(self):
        """Rebuild the R script from current settings and populate the editor."""
        vpc_folder = self.vpc_folder_edit.text().strip()
        if not vpc_folder or not Path(vpc_folder).is_dir():
            QMessageBox.warning(self,'Missing folder','Set the VPC folder first.'); return
        script_txt, _ = self._build_r_script()
        self._last_script_txt = script_txt
        self.r_script_edit.setPlainText(script_txt)
        self._vpc_panel_switch(1)   # switch to R Script tab
        self.status_msg.emit('R script reset from settings')

    def _vpc_panel_switch(self, index):
        self._right_tabs.setCurrentIndex(index)
        for i, btn in enumerate(self._vpc_btns):
            btn.setChecked(i == index)

    def _on_line(self, line):
        self.console.appendPlainText(line)
        if 'NMGUI_VPC_ERROR' in line:
            self._vpc_panel_switch(0)

    def _on_done(self, success, path_or_err):
        self.run_btn.setEnabled(True); self.stop_btn.setEnabled(False)
        if success:
            self._last_png = path_or_err
            self._load_image(path_or_err)
            for b in (self._open_btn, self._savepng_btn, self._savepdf_btn):
                b.setEnabled(True)
            self.status_msg.emit('VPC generated successfully')
        else:
            self.console.appendPlainText(f'\n[FAILED] {path_or_err}')
            self.img_lbl.setText(f'VPC failed.\nSee Console tab for details.\n\n{path_or_err}')
            self._vpc_panel_switch(0)
            self.status_msg.emit('VPC failed — see console')

    def _load_image(self, path):
        try:
            self._orig_px = QPixmap(path)   # keep original for resize
            if self._orig_px.isNull(): raise ValueError('QPixmap could not load image')
            self._scale_image()
        except Exception as e:
            self.img_lbl.setText(f'Image load error: {e}')
            self._orig_px = None

    def _scale_image(self):
        if not hasattr(self, '_orig_px') or self._orig_px is None: return
        scaled = self._orig_px.scaled(
            self.img_lbl.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.img_lbl.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_image()

    # ── Export methods ────────────────────────────────────────────────────────

    def _open_in_viewer(self):
        """Open the generated PNG in the OS default image viewer."""
        if not self._last_png or not Path(self._last_png).is_file():
            QMessageBox.warning(self,'No image','No VPC image available.'); return
        try:
            if IS_WIN:
                os.startfile(self._last_png)
            elif IS_MAC:
                subprocess.Popen(['open', self._last_png])
            else:
                subprocess.Popen(['xdg-open', self._last_png])
        except Exception as e:
            QMessageBox.warning(self,'Error',f'Could not open viewer:\n{e}')

    def _export_hires_png(self):
        """Re-run the VPC R script at 300 DPI and save to a user-chosen path."""
        if not self._last_script_txt or not self._rscript:
            QMessageBox.warning(self,'Not available','No VPC script available. Generate a VPC first.'); return
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Save high-res PNG', str(HOME / 'vpc_hires.png'),
            'PNG images (*.png)')
        if not dst: return
        # Patch the script: replace dpi=150 with dpi=300 and the output path
        r_dst = _sanitize_r(dst)
        script = self._last_script_txt
        script = re.sub(r'dpi\s*=\s*\d+', 'dpi=300', script)
        script = re.sub(r'res\s*=\s*\d+',  'res=300', script)
        # Replace output path in ggsave / png()
        if self._last_png:
            r_orig = _sanitize_r(self._last_png)
            script = script.replace(f'"{r_orig}"', f'"{r_dst}"')
        # Write temp script and run
        tmp = Path(dst).parent / '_nmgui_vpc_hires_tmp.R'
        try:
            tmp.write_text(script, 'utf-8')
            self.console.appendPlainText(f'\nExporting 300 DPI PNG to {dst}…')
            self.run_btn.setEnabled(False)
            worker = VPCWorker(str(tmp), dst, self._rscript, get_login_env())
            worker.line_out.connect(self.console.appendPlainText)
            worker.finished.connect(lambda ok, p: self._on_export_done(ok, p, 'PNG', dst, tmp))
            self._export_worker = worker
            worker.start()
        except Exception as e:
            QMessageBox.critical(self,'Error',str(e))

    def _export_pdf(self):
        """Re-run the VPC R script saving as a vector PDF."""
        if not self._last_script_txt or not self._rscript:
            QMessageBox.warning(self,'Not available','No VPC script available. Generate a VPC first.'); return
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Save PDF', str(HOME / 'vpc.pdf'),
            'PDF files (*.pdf)')
        if not dst: return
        r_dst = _sanitize_r(dst)
        script = self._last_script_txt
        tool = self.tool_cb.currentText()
        if tool in ('vpc', 'xpose'):
            # ggsave with pdf device
            if self._last_png:
                r_orig = _sanitize_r(self._last_png)
                script = script.replace(f'ggsave("{r_orig}"', f'ggsave("{r_dst}"')
            # Remove dpi= arg (not needed for PDF)
            script = re.sub(r',\s*dpi\s*=\s*\d+', '', script)
        elif tool == 'xpose4':
            # Base R: replace png() with pdf()
            if self._last_png:
                r_orig = _sanitize_r(self._last_png)
                script = script.replace(
                    f'png("{r_orig}", width = 1200, height = 900, res = 150)',
                    f'pdf("{r_dst}", width = 10, height = 7.5)')
        tmp = Path(dst).parent / '_nmgui_vpc_pdf_tmp.R'
        try:
            tmp.write_text(script, 'utf-8')
            self.console.appendPlainText(f'\nExporting PDF to {dst}…')
            self.run_btn.setEnabled(False)
            worker = VPCWorker(str(tmp), dst, self._rscript, get_login_env())
            worker.line_out.connect(self.console.appendPlainText)
            worker.finished.connect(lambda ok, p: self._on_export_done(ok, p, 'PDF', dst, tmp))
            self._export_worker = worker
            worker.start()
        except Exception as e:
            QMessageBox.critical(self,'Error',str(e))

    def _on_export_done(self, success, path_or_err, kind, dst, tmp):
        self.run_btn.setEnabled(True)
        try: tmp.unlink()
        except Exception: pass
        if success and Path(dst).is_file():
            self.console.appendPlainText(f'[OK] {kind} saved to {dst}')
            self.status_msg.emit(f'{kind} exported: {Path(dst).name}')
            if QMessageBox.question(self, f'{kind} saved',
                f'{kind} saved to:\n{dst}\n\nOpen now?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes:
                self._open_file(dst)
        else:
            self.console.appendPlainText(f'[FAILED] {kind} export: {path_or_err}')
            self.status_msg.emit(f'{kind} export failed')

    def _open_file(self, path):
        try:
            if IS_WIN:   os.startfile(path)
            elif IS_MAC: subprocess.Popen(['open', path])
            else:        subprocess.Popen(['xdg-open', path])
        except Exception: pass

    def _stop(self):
        if self._worker: self._worker.terminate()
        self.run_btn.setEnabled(True); self.stop_btn.setEnabled(False)


# ══════════════════════════════════════════════════════════════════════════════
# Parameter Uncertainty Tab (Bootstrap & SIR)
# ══════════════════════════════════════════════════════════════════════════════

def _check_psn_tools():
    """Check which PsN tools are available on PATH."""
    import shutil as sh
    available = {}
    for tool in ('bootstrap', 'sir', 'psn'):
        available[tool] = sh.which(tool) is not None
    return available


class BootstrapParser:
    """Parse PsN bootstrap output folder and compute diagnostics."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.raw_df = None
        self.samples_df = None
        self.original = {}
        self.param_cols = []
        self.n_requested = 0
        self.n_successful = 0

    def parse(self) -> dict:
        # Find raw_results file
        raw_files = list(self.folder.glob('raw_results_*.csv'))
        if not raw_files:
            raise FileNotFoundError('No raw_results_*.csv found in bootstrap folder')

        # Read CSV
        import csv
        with open(raw_files[0], 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            raise ValueError('raw_results file is empty')

        # Identify parameter columns
        all_cols = list(rows[0].keys())
        self.param_cols = [c for c in all_cols
                          if c.startswith(('THETA', 'OMEGA', 'SIGMA'))
                          and not c.endswith(('SE', 'RSE', '_SE'))]

        # Find original model row (usually model==0 or 'original')
        orig_row = None
        for row in rows:
            model_val = row.get('model', '').lower()
            if model_val in ('0', 'original', 'input') or 'original' in model_val:
                orig_row = row
                break
        if not orig_row:
            orig_row = rows[0]  # fallback

        # Extract original estimates
        self.original = {}
        for col in self.param_cols:
            try:
                self.original[col] = float(orig_row.get(col, 'nan'))
            except (ValueError, TypeError):
                self.original[col] = float('nan')

        # Filter to bootstrap samples only
        sample_rows = []
        for row in rows:
            model_val = row.get('model', '').lower()
            if model_val in ('0', 'original', 'input') or 'original' in model_val:
                continue
            sample_rows.append(row)

        self.n_requested = len(sample_rows)

        # Check minimization success and extract parameter values
        successful_samples = []
        for row in sample_rows:
            # Check for successful minimization
            min_ok = row.get('minimization_successful', '1')
            try:
                is_ok = int(float(min_ok)) == 1
            except (ValueError, TypeError):
                is_ok = True  # assume success if not specified

            # Also check if parameters are valid (not NA)
            params_valid = True
            param_vals = {}
            for col in self.param_cols:
                try:
                    val = float(row.get(col, 'nan'))
                    if math.isnan(val) or math.isinf(val):
                        params_valid = False
                        break
                    param_vals[col] = val
                except (ValueError, TypeError):
                    params_valid = False
                    break

            if is_ok and params_valid:
                successful_samples.append(param_vals)

        self.n_successful = len(successful_samples)
        self.samples_df = successful_samples  # list of dicts

        # Compute diagnostics
        diagnostics = self._assess()

        return {
            'method': 'bootstrap',
            'folder': str(self.folder),
            'n_requested': self.n_requested,
            'n_successful': self.n_successful,
            'param_cols': self.param_cols,
            'original': self.original,
            'samples': successful_samples,
            'diagnostics': diagnostics
        }

    def _assess(self) -> dict:
        checks = []

        # 1. Completion rate
        rate = self.n_successful / max(1, self.n_requested)
        if rate >= BOOT_COMPLETION_PASS:
            status = 'pass'
            interp = 'Excellent completion rate.'
        elif rate >= BOOT_COMPLETION_WARN:
            status = 'pass'
            interp = 'Good completion rate.'
        elif rate >= BOOT_COMPLETION_FAIL:
            status = 'warning'
            interp = 'Borderline completion. Results usable but precision may be affected.'
        else:
            status = 'fail'
            interp = 'Too many failures. Results unreliable.'

        checks.append({
            'name': 'Completion rate',
            'status': status,
            'value': f'{rate*100:.1f}% ({self.n_successful}/{self.n_requested})',
            'interpretation': interp
        })

        if not self.samples_df:
            return {'overall': 'FAILED', 'checks': checks}

        # 2. Bias assessment
        biases = {}
        max_bias = 0
        flagged_params = []
        for col in self.param_cols:
            orig_val = self.original.get(col, 0)
            sample_vals = [s[col] for s in self.samples_df if col in s]
            if not sample_vals:
                continue
            sample_vals.sort()
            median_val = sample_vals[len(sample_vals)//2]

            if abs(orig_val) > 1e-6:
                bias = abs(median_val - orig_val) / abs(orig_val)
            else:
                bias = abs(median_val - orig_val)
            biases[col] = bias
            if bias > max_bias:
                max_bias = bias
            if bias >= BOOT_BIAS_WARN:
                flagged_params.append(col)

        if max_bias < BOOT_BIAS_PASS:
            status = 'pass'
            value = 'All parameters < 10% deviation'
            interp = 'No evidence of bias.'
        elif max_bias < BOOT_BIAS_WARN:
            status = 'pass'
            value = f'{len(flagged_params)} parameter(s) with 10-20% deviation'
            interp = 'Minor deviation, likely sampling noise.'
        elif max_bias < BOOT_BIAS_FAIL:
            status = 'warning'
            value = f'{len(flagged_params)} parameter(s) > 20% deviation: {", ".join(flagged_params[:3])}'
            interp = 'Moderate bias detected. May indicate model instability.'
        else:
            status = 'fail'
            value = f'{len(flagged_params)} parameter(s) > 50% deviation'
            interp = 'Severe bias. Original estimates likely unreliable.'

        checks.append({
            'name': 'Bias assessment',
            'status': status,
            'value': value,
            'interpretation': interp,
            'details': biases
        })

        # 3. Correlation check
        if HAS_NP and len(self.samples_df) >= 10:
            # Build matrix
            n_params = len(self.param_cols)
            data_matrix = []
            for s in self.samples_df:
                row = [s.get(col, float('nan')) for col in self.param_cols]
                data_matrix.append(row)
            data_matrix = np.array(data_matrix)

            # Compute correlation
            try:
                corr_matrix = np.corrcoef(data_matrix, rowvar=False)
                np.fill_diagonal(corr_matrix, 0)
                max_corr = np.nanmax(np.abs(corr_matrix))

                if max_corr < BOOT_CORR_WARN:
                    status = 'pass'
                    interp = 'Parameters adequately distinguished.'
                elif max_corr < BOOT_CORR_FAIL:
                    status = 'warning'
                    interp = 'High correlation may indicate overparameterization.'
                else:
                    status = 'fail'
                    interp = 'Near-perfect correlation. Parameters not independently identifiable.'

                checks.append({
                    'name': 'Parameter correlations',
                    'status': status,
                    'value': f'Max |r| = {max_corr:.2f}',
                    'interpretation': interp
                })
            except Exception:
                pass  # skip correlation check if numpy fails

        # 4. Confidence interval validity
        ci_issues = []
        for col in self.param_cols:
            orig_val = self.original.get(col, 0)
            sample_vals = sorted([s[col] for s in self.samples_df if col in s])
            if len(sample_vals) < 20:
                continue
            lo = sample_vals[int(len(sample_vals) * 0.025)]
            hi = sample_vals[int(len(sample_vals) * 0.975)]
            if not (lo <= orig_val <= hi):
                ci_issues.append(col)

        if not ci_issues:
            status = 'pass'
            value = 'All CIs include point estimate'
            interp = 'Expected behavior.'
        elif len(ci_issues) <= 2:
            status = 'warning'
            value = f'{len(ci_issues)} CI(s) exclude estimate: {", ".join(ci_issues)}'
            interp = 'Unusual but not necessarily wrong. Suggests skewed distribution.'
        else:
            status = 'warning'
            value = f'{len(ci_issues)} CIs exclude point estimate'
            interp = 'Multiple CIs exclude estimate. Check for bias or instability.'

        checks.append({
            'name': 'CI validity',
            'status': status,
            'value': value,
            'interpretation': interp
        })

        # Overall assessment
        n_fail = sum(1 for c in checks if c['status'] == 'fail')
        n_warn = sum(1 for c in checks if c['status'] == 'warning')

        if n_fail > 0:
            overall = 'FAILED'
        elif n_warn > 2:
            overall = 'WARNING'
        elif n_warn > 0:
            overall = 'ACCEPTABLE'
        else:
            overall = 'PASSED'

        return {'overall': overall, 'checks': checks, 'biases': biases}

    def get_parameter_table(self) -> list:
        """Return list of dicts with parameter estimates and CIs."""
        if not self.samples_df:
            return []

        table = []
        for col in self.param_cols:
            orig_val = self.original.get(col, float('nan'))
            sample_vals = sorted([s[col] for s in self.samples_df if col in s])
            if not sample_vals:
                continue

            median = sample_vals[len(sample_vals)//2]
            lo = sample_vals[int(len(sample_vals) * 0.025)]
            hi = sample_vals[int(len(sample_vals) * 0.975)]

            # RSE approximation
            if abs(median) > 1e-10:
                rse = (hi - lo) / (2 * 1.96 * abs(median)) * 100
            else:
                rse = float('nan')

            table.append({
                'parameter': col,
                'estimate': orig_val,
                'median': median,
                'ci_lo': lo,
                'ci_hi': hi,
                'rse': rse
            })
        return table


class SIRParser:
    """Parse PsN SIR output folder and compute diagnostics."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.dofv = []
        self.df = 0
        self.param_cols = []
        self.samples = []
        self.original = {}
        self.n_resamples = 0

    def parse(self) -> dict:
        raw_file = self.folder / 'raw_results_sir.csv'
        if not raw_file.exists():
            raise FileNotFoundError('raw_results_sir.csv not found in SIR folder')

        # Read CSV
        import csv
        with open(raw_file, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            raise ValueError('raw_results_sir.csv is empty')

        # Identify parameter columns
        all_cols = list(rows[0].keys())
        self.param_cols = [c for c in all_cols
                          if c.startswith(('THETA', 'OMEGA', 'SIGMA'))
                          and not c.endswith(('SE', 'RSE', '_SE'))]

        self.df = len(self.param_cols)

        # Extract dOFV values
        dofv_col = None
        for cand in ('deltaofv', 'dOFV', 'DOFV', 'delta_ofv'):
            if cand in all_cols:
                dofv_col = cand
                break

        self.dofv = []
        for row in rows:
            try:
                if dofv_col:
                    val = float(row.get(dofv_col, 'nan'))
                else:
                    # Compute from OFV if available
                    continue
                if not math.isnan(val) and val >= 0:
                    self.dofv.append(val)
            except (ValueError, TypeError):
                continue

        # Get original estimates (from sir_results.csv header or first row)
        sir_results = self.folder / 'sir_results.csv'
        if sir_results.exists():
            with open(sir_results, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                final_rows = list(reader)
            self.samples = []
            for row in final_rows:
                param_vals = {}
                for col in self.param_cols:
                    try:
                        param_vals[col] = float(row.get(col, 'nan'))
                    except (ValueError, TypeError):
                        param_vals[col] = float('nan')
                self.samples.append(param_vals)
            self.n_resamples = len(self.samples)
        else:
            # Use final iteration from raw_results
            max_iter = 0
            for row in rows:
                try:
                    it = int(row.get('iteration', 0))
                    if it > max_iter:
                        max_iter = it
                except (ValueError, TypeError):
                    pass

            self.samples = []
            for row in rows:
                try:
                    if int(row.get('iteration', 0)) == max_iter:
                        param_vals = {}
                        for col in self.param_cols:
                            param_vals[col] = float(row.get(col, 'nan'))
                        self.samples.append(param_vals)
                except (ValueError, TypeError):
                    continue
            self.n_resamples = len(self.samples)

        # Get original from model with lowest OFV or iteration 0
        for row in rows:
            try:
                if int(row.get('iteration', 1)) == 0:
                    for col in self.param_cols:
                        self.original[col] = float(row.get(col, 'nan'))
                    break
            except (ValueError, TypeError):
                continue

        # If no original found, use median of final iteration
        if not self.original and self.samples:
            for col in self.param_cols:
                vals = sorted([s[col] for s in self.samples if not math.isnan(s.get(col, float('nan')))])
                if vals:
                    self.original[col] = vals[len(vals)//2]

        diagnostics = self._assess()

        return {
            'method': 'sir',
            'folder': str(self.folder),
            'n_resamples': self.n_resamples,
            'df': self.df,
            'param_cols': self.param_cols,
            'original': self.original,
            'samples': self.samples,
            'dofv': self.dofv,
            'diagnostics': diagnostics
        }

    def _assess(self) -> dict:
        checks = []

        # 1. dOFV K-S test
        if HAS_SCIPY and len(self.dofv) >= 50:
            try:
                stat, pval = scipy_kstest(self.dofv, 'chi2', args=(self.df,))
                if pval > SIR_KS_PASS:
                    status = 'pass'
                    interp = f'dOFV distribution consistent with χ²({self.df}).'
                elif pval > SIR_KS_WARN:
                    status = 'pass'
                    interp = 'Marginally consistent with theoretical distribution.'
                else:
                    status = 'fail'
                    interp = 'Significant deviation from χ². SIR proposal may be inappropriate.'

                checks.append({
                    'name': 'dOFV K-S test',
                    'status': status,
                    'value': f'p = {pval:.3f} (χ² df={self.df})',
                    'interpretation': interp
                })
            except Exception:
                pass

        # 2. dOFV median check
        if self.dofv:
            observed_median = sorted(self.dofv)[len(self.dofv)//2]
            # Theoretical median of chi-square ≈ df * (1 - 2/(9*df))^3
            if self.df > 0:
                theoretical_median = self.df * (1 - 2/(9*self.df))**3
            else:
                theoretical_median = self.df

            if theoretical_median > 0:
                deviation = abs(observed_median - theoretical_median) / theoretical_median
            else:
                deviation = 0

            if deviation < SIR_MEDIAN_PASS:
                status = 'pass'
                interp = 'Median close to expected value.'
            elif deviation < SIR_MEDIAN_WARN:
                status = 'warning'
                interp = 'Some shift from expected. May indicate proposal mismatch.'
            else:
                status = 'fail'
                interp = 'Substantial shift. Proposal distribution problematic.'

            checks.append({
                'name': 'dOFV median',
                'status': status,
                'value': f'{observed_median:.1f} vs expected {theoretical_median:.1f} ({deviation*100:+.0f}%)',
                'interpretation': interp
            })

        # 3. Effective sample size (approximation)
        if self.samples:
            # Simple approximation: count unique resampled vectors
            # A more accurate ESS would require importance weights
            n_unique = len(set(tuple(sorted(s.items())) for s in self.samples))
            ess_ratio = n_unique / max(1, self.n_resamples)

            if ess_ratio > SIR_ESS_PASS:
                status = 'pass'
                interp = 'Excellent resampling efficiency.'
            elif ess_ratio > SIR_ESS_WARN:
                status = 'pass'
                interp = 'Good efficiency.'
            elif ess_ratio > SIR_ESS_FAIL:
                status = 'warning'
                interp = 'Moderate efficiency. Consider increasing samples.'
            else:
                status = 'fail'
                interp = 'Poor efficiency. Results may be dominated by few samples.'

            # Also check absolute ESS
            if n_unique < SIR_ESS_ABS_FAIL:
                status = 'fail'
                interp = f'ESS below minimum threshold ({SIR_ESS_ABS_FAIL}).'
            elif n_unique < SIR_ESS_ABS_WARN and status == 'pass':
                status = 'warning'
                interp = 'ESS somewhat low. Results usable but consider more samples.'

            checks.append({
                'name': 'Effective sample size',
                'status': status,
                'value': f'~{n_unique} unique / {self.n_resamples} ({ess_ratio*100:.0f}%)',
                'interpretation': interp
            })

        # 4. Parameter shift check
        if self.samples and self.original:
            shifts = {}
            max_shift = 0
            for col in self.param_cols:
                orig_val = self.original.get(col, 0)
                sample_vals = [s[col] for s in self.samples if col in s and not math.isnan(s[col])]
                if not sample_vals:
                    continue
                sample_vals.sort()
                median_val = sample_vals[len(sample_vals)//2]
                if abs(orig_val) > 1e-6:
                    shift = abs(median_val - orig_val) / abs(orig_val)
                else:
                    shift = abs(median_val - orig_val)
                shifts[col] = shift
                if shift > max_shift:
                    max_shift = shift

            if max_shift < 0.10:
                status = 'pass'
                value = 'All parameters < 10% shift'
                interp = 'Well-centered distributions.'
            elif max_shift < 0.25:
                status = 'warning'
                value = f'Max shift {max_shift*100:.0f}%'
                interp = 'Moderate shift. Original estimate may be at edge of uncertainty region.'
            else:
                status = 'warning'
                value = f'Max shift {max_shift*100:.0f}%'
                interp = 'Substantial shift from point estimate.'

            checks.append({
                'name': 'Parameter shift',
                'status': status,
                'value': value,
                'interpretation': interp
            })

        # 5. Boundary pile-up (check if many samples at lower bound 0 for omegas)
        boundary_issues = []
        for col in self.param_cols:
            if not col.startswith('OMEGA'):
                continue
            sample_vals = [s[col] for s in self.samples if col in s and not math.isnan(s[col])]
            if not sample_vals:
                continue
            n_at_zero = sum(1 for v in sample_vals if abs(v) < 1e-8)
            frac_at_zero = n_at_zero / len(sample_vals)
            if frac_at_zero > 0.15:
                boundary_issues.append(f'{col} ({frac_at_zero*100:.0f}%)')
            elif frac_at_zero > 0.05:
                boundary_issues.append(f'{col} ({frac_at_zero*100:.0f}%)')

        if not boundary_issues:
            status = 'pass'
            value = 'No pile-up detected'
            interp = 'No boundary issues.'
        elif any('(' in b and int(b.split('(')[1].rstrip('%)')) > 15 for b in boundary_issues):
            status = 'fail'
            value = f'Pile-up: {", ".join(boundary_issues[:3])}'
            interp = 'Substantial pile-up at bounds. CI may be artificially narrow.'
        else:
            status = 'warning'
            value = f'Minor: {", ".join(boundary_issues[:3])}'
            interp = 'Some truncation at bounds.'

        checks.append({
            'name': 'Boundary check',
            'status': status,
            'value': value,
            'interpretation': interp
        })

        # Overall assessment
        n_fail = sum(1 for c in checks if c['status'] == 'fail')
        n_warn = sum(1 for c in checks if c['status'] == 'warning')

        if n_fail > 0:
            overall = 'FAILED'
        elif n_warn > 2:
            overall = 'WARNING'
        elif n_warn > 0:
            overall = 'ACCEPTABLE'
        else:
            overall = 'PASSED'

        return {'overall': overall, 'checks': checks}

    def get_parameter_table(self) -> list:
        """Return list of dicts with parameter estimates and CIs."""
        if not self.samples:
            return []

        table = []
        for col in self.param_cols:
            orig_val = self.original.get(col, float('nan'))
            sample_vals = sorted([s[col] for s in self.samples
                                  if col in s and not math.isnan(s[col])])
            if not sample_vals:
                continue

            median = sample_vals[len(sample_vals)//2]
            lo = sample_vals[int(len(sample_vals) * 0.025)]
            hi = sample_vals[int(len(sample_vals) * 0.975)]

            if abs(median) > 1e-10:
                rse = (hi - lo) / (2 * 1.96 * abs(median)) * 100
            else:
                rse = float('nan')

            table.append({
                'parameter': col,
                'estimate': orig_val,
                'median': median,
                'ci_lo': lo,
                'ci_hi': hi,
                'rse': rse
            })
        return table


class PsNWorker(QThread):
    """Worker thread for running PsN bootstrap or sir."""
    line_out = pyqtSignal(str)
    finished = pyqtSignal(bool, str)  # success, folder_or_error

    def __init__(self, cmd: list, output_dir: str, env: dict):
        super().__init__()
        self._cmd = cmd
        self._output_dir = output_dir
        self._env = env
        self._process = None
        self._cancelled = False

    def run(self):
        try:
            self.line_out.emit(f'> {" ".join(self._cmd)}\n')
            self._process = subprocess.Popen(
                self._cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=self._env,
                cwd=str(Path(self._output_dir).parent) if self._output_dir else None
            )

            for line in iter(self._process.stdout.readline, ''):
                if self._cancelled:
                    break
                self.line_out.emit(line.rstrip())

            self._process.wait()

            if self._cancelled:
                self.finished.emit(False, 'Cancelled by user')
            elif self._process.returncode == 0:
                self.finished.emit(True, self._output_dir)
            else:
                self.finished.emit(False, f'Process exited with code {self._process.returncode}')

        except Exception as e:
            self.finished.emit(False, str(e))

    def terminate(self):
        self._cancelled = True
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass


class ParameterUncertaintyTab(QWidget):
    """Tab for running and analyzing Bootstrap and SIR results."""
    status_msg = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = None
        self._worker = None
        self._results = None
        self._psn_available = {}
        self._build_ui()
        QTimer.singleShot(500, self._check_psn)

    def _build_ui(self):
        main_h = QHBoxLayout(self)
        main_h.setContentsMargins(6, 6, 6, 6)
        main_h.setSpacing(8)

        # ── Left panel: method & mode selection ────────────────────────────────
        left_panel = QWidget()
        left_panel.setFixedWidth(180)
        left_v = QVBoxLayout(left_panel)
        left_v.setContentsMargins(8, 8, 8, 8)
        left_v.setSpacing(16)

        # Model info
        self.model_lbl = QLabel('No model selected')
        self.model_lbl.setWordWrap(True)
        self.model_lbl.setStyleSheet(f'color: {T("fg2")}; font-size: 12px;')
        left_v.addWidget(self.model_lbl)

        # Method selection
        method_lbl = QLabel('METHOD')
        method_lbl.setStyleSheet(f'color: {T("fg2")}; font-size: 10px; font-weight: 600; letter-spacing: 0.5px;')
        left_v.addWidget(method_lbl)
        
        self._method_group = QButtonGroup(self)
        self.bootstrap_rb = QRadioButton('Bootstrap')
        self.bootstrap_rb.setChecked(True)
        self.sir_rb = QRadioButton('SIR')
        self._method_group.addButton(self.bootstrap_rb, 0)
        self._method_group.addButton(self.sir_rb, 1)
        self._method_group.buttonClicked.connect(self._on_method_change)
        left_v.addWidget(self.bootstrap_rb)
        left_v.addWidget(self.sir_rb)

        # Spacer
        left_v.addSpacing(8)

        # Mode selection
        mode_lbl = QLabel('MODE')
        mode_lbl.setStyleSheet(f'color: {T("fg2")}; font-size: 10px; font-weight: 600; letter-spacing: 0.5px;')
        left_v.addWidget(mode_lbl)
        
        self._mode_group = QButtonGroup(self)
        self.run_new_rb = QRadioButton('Run new')
        self.run_new_rb.setChecked(True)
        self.load_existing_rb = QRadioButton('Load existing')
        self._mode_group.addButton(self.run_new_rb, 0)
        self._mode_group.addButton(self.load_existing_rb, 1)
        self._mode_group.buttonClicked.connect(self._on_mode_change)
        left_v.addWidget(self.run_new_rb)
        left_v.addWidget(self.load_existing_rb)

        # Detected results (for load mode)
        left_v.addSpacing(8)
        self.detected_lbl = QLabel('FOUND RESULTS')
        self.detected_lbl.setStyleSheet(f'color: {T("fg2")}; font-size: 10px; font-weight: 600; letter-spacing: 0.5px;')
        self.detected_lbl.hide()
        left_v.addWidget(self.detected_lbl)
        
        self.results_combo = QComboBox()
        self.results_combo.addItem('(none found)')
        self.results_combo.hide()
        left_v.addWidget(self.results_combo)
        
        browse_btn = QPushButton('Browse other…')
        browse_btn.setFixedHeight(28)
        browse_btn.clicked.connect(self._browse_folder)
        browse_btn.hide()
        self._browse_btn = browse_btn
        left_v.addWidget(browse_btn)

        # PSN status
        left_v.addSpacing(12)
        self.psn_lbl = QLabel('Checking PsN…')
        self.psn_lbl.setWordWrap(True)
        self.psn_lbl.setStyleSheet(f'color: {T("fg2")}; font-size: 11px;')
        left_v.addWidget(self.psn_lbl)

        left_v.addStretch()
        main_h.addWidget(left_panel)

        # Separator
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f'background: {T("border")};')
        main_h.addWidget(sep)

        # ── Right panel: config + results ──────────────────────────────────────
        right_v = QVBoxLayout()
        right_v.setContentsMargins(0, 0, 0, 0)
        right_v.setSpacing(8)

        # Config stack (switches between bootstrap/sir and run/load)
        self._config_stack = QStackedWidget()

        # Page 0: Bootstrap run config
        self._bootstrap_config = self._build_bootstrap_config()
        self._config_stack.addWidget(self._bootstrap_config)

        # Page 1: SIR run config
        self._sir_config = self._build_sir_config()
        self._config_stack.addWidget(self._sir_config)

        # Page 2: Load existing (minimal)
        self._load_config = self._build_load_config()
        self._config_stack.addWidget(self._load_config)

        right_v.addWidget(self._config_stack)

        # Run/Load buttons
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton('Run Bootstrap')
        self.run_btn.setFixedHeight(32)
        self.run_btn.clicked.connect(self._run)
        self.stop_btn = QPushButton('Stop')
        self.stop_btn.setFixedHeight(32)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        self.load_btn = QPushButton('Load Results')
        self.load_btn.setFixedHeight(32)
        self.load_btn.clicked.connect(self._load_results)
        self.load_btn.hide()
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.load_btn)
        btn_row.addStretch()
        right_v.addLayout(btn_row)

        # Results tabs
        results_tabs_row = QHBoxLayout()
        self._results_btns = []
        for i, label in enumerate(['Console', 'Assessment', 'Parameters', 'Plots']):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.clicked.connect(lambda _, idx=i: self._switch_results_tab(idx))
            results_tabs_row.addWidget(btn)
            self._results_btns.append(btn)
        results_tabs_row.addStretch()
        right_v.addLayout(results_tabs_row)

        # Results stack
        self._results_stack = QStackedWidget()

        # Console
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont('Menlo' if IS_MAC else 'Consolas', 10))
        self.console.setStyleSheet(f'background: {T("bg2")}; border: 1px solid {T("border")}; border-radius: 4px;')
        self._results_stack.addWidget(self.console)

        # Assessment panel
        self.assessment_panel = QWidget()
        ap_v = QVBoxLayout(self.assessment_panel)
        ap_v.setContentsMargins(8, 8, 8, 8)
        self.assessment_lbl = QLabel('No results loaded')
        self.assessment_lbl.setWordWrap(True)
        self.assessment_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.assessment_lbl.setTextFormat(Qt.TextFormat.RichText)
        ap_v.addWidget(self.assessment_lbl)
        ap_v.addStretch()
        self._results_stack.addWidget(self.assessment_panel)

        # Parameters table
        self.param_table = QTableWidget()
        self.param_table.setColumnCount(6)
        self.param_table.setHorizontalHeaderLabels(['Parameter', 'Estimate', 'Median', '2.5%', '97.5%', 'RSE (%)'])
        self.param_table.horizontalHeader().setStretchLastSection(True)
        self.param_table.setAlternatingRowColors(True)
        self.param_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._results_stack.addWidget(self.param_table)

        # Plots panel
        self.plots_panel = QWidget()
        plots_v = QVBoxLayout(self.plots_panel)
        plots_v.setContentsMargins(0, 0, 0, 0)
        if HAS_MPL:
            self._figure = Figure(figsize=(8, 6), dpi=100)
            self._canvas = FigureCanvasQTAgg(self._figure)
            plots_v.addWidget(self._canvas)
        else:
            plots_v.addWidget(QLabel('Matplotlib not available'))
        self._results_stack.addWidget(self.plots_panel)

        right_v.addWidget(self._results_stack, 1)

        main_h.addLayout(right_v, 1)

        self._on_mode_change()

    def _build_bootstrap_config(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.boot_samples_spin = QDoubleSpinBox()
        self.boot_samples_spin.setRange(100, 10000)
        self.boot_samples_spin.setValue(1000)
        self.boot_samples_spin.setDecimals(0)
        form.addRow('Samples:', self.boot_samples_spin)

        self.boot_threads_spin = QDoubleSpinBox()
        self.boot_threads_spin.setRange(1, 64)
        self.boot_threads_spin.setValue(4)
        self.boot_threads_spin.setDecimals(0)
        form.addRow('Threads:', self.boot_threads_spin)

        self.boot_stratify_edit = QLineEdit()
        self.boot_stratify_edit.setPlaceholderText('Column name (optional)')
        form.addRow('Stratify by:', self.boot_stratify_edit)

        self.boot_skip_cov_cb = QCheckBox('Skip covariance step (faster)')
        self.boot_skip_cov_cb.setChecked(True)
        form.addRow('', self.boot_skip_cov_cb)

        # Output directory
        dir_row = QHBoxLayout()
        self.boot_dir_edit = QLineEdit()
        self.boot_dir_edit.setPlaceholderText('Output directory')
        dir_row.addWidget(self.boot_dir_edit)
        dir_browse = QPushButton('…')
        dir_browse.setFixedWidth(30)
        dir_browse.clicked.connect(lambda: self._browse_output_dir(self.boot_dir_edit))
        dir_row.addWidget(dir_browse)
        form.addRow('Output dir:', dir_row)

        # Cluster options - collapsible
        self.boot_cluster_cb = QCheckBox('Submit to cluster')
        self.boot_cluster_cb.setChecked(False)
        form.addRow('', self.boot_cluster_cb)
        
        # Cluster options container (hidden by default)
        self._boot_cluster_container = QWidget()
        cluster_layout = QFormLayout(self._boot_cluster_container)
        cluster_layout.setContentsMargins(20, 0, 0, 0)
        cluster_layout.setSpacing(6)
        
        self.boot_cluster_type = QComboBox()
        self.boot_cluster_type.addItems(['slurm', 'sge', 'torque', 'lsf'])
        cluster_layout.addRow('Scheduler:', self.boot_cluster_type)
        
        self.boot_cluster_opts = QLineEdit()
        self.boot_cluster_opts.setPlaceholderText('e.g., -p short --mem=4G')
        cluster_layout.addRow('Options:', self.boot_cluster_opts)
        
        self._boot_cluster_container.hide()
        form.addRow('', self._boot_cluster_container)
        
        # Connect checkbox to show/hide cluster options
        self.boot_cluster_cb.toggled.connect(self._boot_cluster_container.setVisible)

        return w

    def _build_sir_config(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.sir_samples_spin = QDoubleSpinBox()
        self.sir_samples_spin.setRange(100, 50000)
        self.sir_samples_spin.setValue(1000)
        self.sir_samples_spin.setDecimals(0)
        form.addRow('Samples:', self.sir_samples_spin)

        self.sir_resamples_spin = QDoubleSpinBox()
        self.sir_resamples_spin.setRange(100, 50000)
        self.sir_resamples_spin.setValue(1000)
        self.sir_resamples_spin.setDecimals(0)
        form.addRow('Resamples:', self.sir_resamples_spin)

        self.sir_iterations_spin = QDoubleSpinBox()
        self.sir_iterations_spin.setRange(1, 20)
        self.sir_iterations_spin.setValue(5)
        self.sir_iterations_spin.setDecimals(0)
        form.addRow('Iterations:', self.sir_iterations_spin)

        self.sir_threads_spin = QDoubleSpinBox()
        self.sir_threads_spin.setRange(1, 64)
        self.sir_threads_spin.setValue(4)
        self.sir_threads_spin.setDecimals(0)
        form.addRow('Threads:', self.sir_threads_spin)

        # Output directory
        dir_row = QHBoxLayout()
        self.sir_dir_edit = QLineEdit()
        self.sir_dir_edit.setPlaceholderText('Output directory')
        dir_row.addWidget(self.sir_dir_edit)
        dir_browse = QPushButton('…')
        dir_browse.setFixedWidth(30)
        dir_browse.clicked.connect(lambda: self._browse_output_dir(self.sir_dir_edit))
        dir_row.addWidget(dir_browse)
        form.addRow('Output dir:', dir_row)

        # Cluster options - collapsible
        self.sir_cluster_cb = QCheckBox('Submit to cluster')
        self.sir_cluster_cb.setChecked(False)
        form.addRow('', self.sir_cluster_cb)
        
        # Cluster options container (hidden by default)
        self._sir_cluster_container = QWidget()
        cluster_layout = QFormLayout(self._sir_cluster_container)
        cluster_layout.setContentsMargins(20, 0, 0, 0)
        cluster_layout.setSpacing(6)
        
        self.sir_cluster_type = QComboBox()
        self.sir_cluster_type.addItems(['slurm', 'sge', 'torque', 'lsf'])
        cluster_layout.addRow('Scheduler:', self.sir_cluster_type)
        
        self.sir_cluster_opts = QLineEdit()
        self.sir_cluster_opts.setPlaceholderText('e.g., -p short --mem=4G')
        cluster_layout.addRow('Options:', self.sir_cluster_opts)
        
        self._sir_cluster_container.hide()
        form.addRow('', self._sir_cluster_container)
        
        # Connect checkbox to show/hide cluster options
        self.sir_cluster_cb.toggled.connect(self._sir_cluster_container.setVisible)

        return w

    def _build_load_config(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel('Select a results folder from the dropdown on the left,\nor browse for a folder.')
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f'color: {T("fg2")};')
        v.addWidget(lbl)
        v.addStretch()
        return w

    def _check_psn(self):
        self._psn_available = _check_psn_tools()
        parts = []
        for tool in ('bootstrap', 'sir'):
            if self._psn_available.get(tool):
                parts.append(f'✓ {tool}')
            else:
                parts.append(f'✗ {tool}')
        self.psn_lbl.setText('PsN tools:\n' + ', '.join(parts))

        if not self._psn_available.get('bootstrap') and not self._psn_available.get('sir'):
            self.run_btn.setEnabled(False)
            self.psn_lbl.setStyleSheet(f'color: {T("red")}; font-size: 10px;')

    def _on_method_change(self, *args):
        if self.run_new_rb.isChecked():
            if self.bootstrap_rb.isChecked():
                self._config_stack.setCurrentIndex(0)
                self.run_btn.setText('Run Bootstrap')
            else:
                self._config_stack.setCurrentIndex(1)
                self.run_btn.setText('Run SIR')
        self._detect_existing_results()

    def _on_mode_change(self, *args):
        if self.run_new_rb.isChecked():
            self.detected_lbl.hide()
            self.results_combo.hide()
            self._browse_btn.hide()
            self.run_btn.show()
            self.stop_btn.show()
            self.load_btn.hide()
            self._on_method_change()
        else:
            self.detected_lbl.show()
            self.results_combo.show()
            self._browse_btn.show()
            self.run_btn.hide()
            self.stop_btn.hide()
            self.load_btn.show()
            self._config_stack.setCurrentIndex(2)
            self._detect_existing_results()

    def _detect_existing_results(self):
        """Scan model directory for existing bootstrap/SIR folders."""
        self.results_combo.clear()
        if not self._model or not self._model.get('lst_path'):
            self.results_combo.addItem('(no model selected)')
            return

        model_dir = Path(self._model['lst_path']).parent
        method = 'bootstrap' if self.bootstrap_rb.isChecked() else 'sir'

        # Find matching folders
        patterns = [f'{method}_*', f'{method.upper()}_*']
        found = []
        for pat in patterns:
            found.extend(model_dir.glob(pat))

        # Also look for folders containing the method name and model stem
        stem = self._model.get('stem', '')
        if stem:
            found.extend(model_dir.glob(f'*{method}*{stem}*'))
            found.extend(model_dir.glob(f'*{stem}*{method}*'))

        # Deduplicate and sort by modification time
        found = list(set(found))
        found = [f for f in found if f.is_dir()]
        found.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        if found:
            for folder in found[:10]:  # limit to 10 most recent
                # Get modification date
                try:
                    mtime = datetime.fromtimestamp(folder.stat().st_mtime)
                    date_str = mtime.strftime('%Y-%m-%d %H:%M')
                except Exception:
                    date_str = ''
                self.results_combo.addItem(f'{folder.name} ({date_str})', str(folder))
        else:
            self.results_combo.addItem('(none found)')

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Select results folder',
            str(Path(self._model['lst_path']).parent) if self._model and self._model.get('lst_path') else str(HOME))
        if folder:
            # Add to combo and select it
            self.results_combo.insertItem(0, Path(folder).name, folder)
            self.results_combo.setCurrentIndex(0)

    def _browse_output_dir(self, edit: QLineEdit):
        folder = QFileDialog.getExistingDirectory(self, 'Select output directory',
            edit.text() or str(HOME))
        if folder:
            edit.setText(folder)

    def load_model(self, model: dict):
        self._model = model
        if model:
            stem = model.get('stem', 'model')
            self.model_lbl.setText(f'Model: {stem}')

            # Set default output directories
            if model.get('lst_path'):
                model_dir = Path(model['lst_path']).parent
                self.boot_dir_edit.setText(str(model_dir / f'bootstrap_{stem}'))
                self.sir_dir_edit.setText(str(model_dir / f'sir_{stem}'))

            self._detect_existing_results()
        else:
            self.model_lbl.setText('No model selected')

    def _build_bootstrap_cmd(self) -> list:
        if not self._model or not self._model.get('path'):
            return []

        cmd = ['bootstrap', self._model['path']]
        cmd.append(f'-samples={int(self.boot_samples_spin.value())}')
        cmd.append(f'-threads={int(self.boot_threads_spin.value())}')

        strat = self.boot_stratify_edit.text().strip()
        if strat:
            cmd.append(f'-stratify_on={strat}')

        if self.boot_skip_cov_cb.isChecked():
            cmd.append('-skip_covariance_step')

        if self.boot_cluster_cb.isChecked():
            cluster_type = self.boot_cluster_type.currentText()
            cmd.append(f'-run_on_{cluster_type}')
            opts = self.boot_cluster_opts.text().strip()
            if opts:
                cmd.append(f'-{cluster_type}_options={opts}')

        out_dir = self.boot_dir_edit.text().strip()
        if out_dir:
            cmd.append(f'-directory={out_dir}')

        return cmd

    def _build_sir_cmd(self) -> list:
        if not self._model or not self._model.get('path'):
            return []

        cmd = ['sir', self._model['path']]
        cmd.append(f'-samples={int(self.sir_samples_spin.value())}')
        cmd.append(f'-resamples={int(self.sir_resamples_spin.value())}')
        cmd.append(f'-iterations={int(self.sir_iterations_spin.value())}')
        cmd.append(f'-threads={int(self.sir_threads_spin.value())}')

        if self.sir_cluster_cb.isChecked():
            cluster_type = self.sir_cluster_type.currentText()
            cmd.append(f'-run_on_{cluster_type}')
            opts = self.sir_cluster_opts.text().strip()
            if opts:
                cmd.append(f'-{cluster_type}_options={opts}')

        out_dir = self.sir_dir_edit.text().strip()
        if out_dir:
            cmd.append(f'-directory={out_dir}')

        return cmd

    def _run(self):
        if not self._model:
            QMessageBox.warning(self, 'No model', 'Select a model first.')
            return

        method = 'bootstrap' if self.bootstrap_rb.isChecked() else 'sir'

        if not self._psn_available.get(method):
            QMessageBox.warning(self, 'PsN not available',
                f'The PsN {method} tool is not found on PATH.')
            return

        if method == 'bootstrap':
            cmd = self._build_bootstrap_cmd()
            out_dir = self.boot_dir_edit.text().strip()
        else:
            cmd = self._build_sir_cmd()
            out_dir = self.sir_dir_edit.text().strip()

        if not cmd:
            QMessageBox.warning(self, 'Error', 'Could not build command.')
            return

        self.console.clear()
        self.console.appendPlainText(f'Starting {method}…\n')
        self._switch_results_tab(0)

        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self._worker = PsNWorker(cmd, out_dir, get_login_env())
        self._worker.line_out.connect(self._on_line)
        self._worker.finished.connect(self._on_run_done)
        self._worker.start()

    def _stop(self):
        if self._worker:
            self._worker.terminate()
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.console.appendPlainText('\n[Cancelled]')

    def _on_line(self, line: str):
        self.console.appendPlainText(line)
        # Auto-scroll
        sb = self.console.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_run_done(self, success: bool, folder_or_err: str):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if success:
            self.console.appendPlainText(f'\n[Completed] Output: {folder_or_err}')
            self.status_msg.emit('Run completed successfully')
            # Auto-load results
            self._parse_and_display(Path(folder_or_err))
        else:
            self.console.appendPlainText(f'\n[Failed] {folder_or_err}')
            self.status_msg.emit(f'Run failed: {folder_or_err}')

    def _load_results(self):
        """Load existing results from selected folder."""
        idx = self.results_combo.currentIndex()
        folder = self.results_combo.itemData(idx)
        if not folder:
            QMessageBox.warning(self, 'No folder', 'Select a results folder first.')
            return

        self._parse_and_display(Path(folder))

    def _parse_and_display(self, folder: Path):
        """Parse results folder and display diagnostics."""
        self.console.appendPlainText(f'\nParsing results from: {folder}\n')

        # Detect method from folder contents
        if (folder / 'raw_results_sir.csv').exists():
            method = 'sir'
        elif list(folder.glob('raw_results_*.csv')):
            method = 'bootstrap'
        else:
            QMessageBox.warning(self, 'Not found',
                'Could not find raw_results_*.csv or raw_results_sir.csv in this folder.')
            return

        try:
            if method == 'bootstrap':
                parser = BootstrapParser(folder)
                self._results = parser.parse()
            else:
                parser = SIRParser(folder)
                self._results = parser.parse()

            self.console.appendPlainText(f'Parsed {method} results successfully.\n')
            self._display_assessment()
            self._display_parameters()
            self._generate_plots()
            self._switch_results_tab(1)  # Switch to assessment
            self.status_msg.emit(f'Loaded {method} results from {folder.name}')

        except Exception as e:
            self.console.appendPlainText(f'Error parsing results: {e}\n')
            QMessageBox.critical(self, 'Parse error', str(e))

    def _display_assessment(self):
        """Display diagnostic assessment panel."""
        if not self._results:
            return

        method = self._results['method'].upper()
        diag = self._results['diagnostics']
        overall = diag['overall']

        # Color-code overall status
        if overall == 'PASSED':
            color = T('green')
            icon = '●'
        elif overall == 'ACCEPTABLE':
            color = T('accent')
            icon = '●'
        elif overall == 'WARNING':
            color = T('orange')
            icon = '●'
        else:
            color = T('red')
            icon = '●'

        html = f'''
        <div style="font-family: system-ui; color: {T('fg')};">
            <h3 style="margin: 0 0 12px 0;">{method} Assessment</h3>
            <p style="font-size: 16px; margin: 0 0 16px 0;">
                Overall: <span style="color: {color}; font-weight: bold;">{icon} {overall}</span>
            </p>
            <table style="border-collapse: collapse; width: 100%;">
        '''

        for check in diag['checks']:
            status = check['status']
            if status == 'pass':
                s_icon = '✓'
                s_color = T('green')
            elif status == 'warning':
                s_icon = '⚠'
                s_color = T('orange')
            else:
                s_icon = '✗'
                s_color = T('red')

            html += f'''
                <tr style="border-bottom: 1px solid {T('border')};">
                    <td style="padding: 8px 4px; color: {s_color}; width: 24px;">{s_icon}</td>
                    <td style="padding: 8px 4px; font-weight: 500;">{check['name']}</td>
                    <td style="padding: 8px 4px; color: {T('fg2')};">{check['value']}</td>
                </tr>
                <tr>
                    <td></td>
                    <td colspan="2" style="padding: 4px 4px 12px 4px; color: {T('fg2')}; font-size: 12px;">
                        {check.get('interpretation', '')}
                    </td>
                </tr>
            '''

        html += '</table></div>'
        self.assessment_lbl.setText(html)

    def _display_parameters(self):
        """Display parameter uncertainty table."""
        if not self._results:
            return

        method = self._results['method']
        if method == 'bootstrap':
            parser = BootstrapParser(Path(self._results['folder']))
            parser.param_cols = self._results['param_cols']
            parser.original = self._results['original']
            parser.samples_df = self._results['samples']
            table_data = parser.get_parameter_table()
        else:
            parser = SIRParser(Path(self._results['folder']))
            parser.param_cols = self._results['param_cols']
            parser.original = self._results['original']
            parser.samples = self._results['samples']
            table_data = parser.get_parameter_table()

        self.param_table.setRowCount(len(table_data))
        for i, row in enumerate(table_data):
            self.param_table.setItem(i, 0, QTableWidgetItem(row['parameter']))
            self.param_table.setItem(i, 1, QTableWidgetItem(f"{row['estimate']:.4g}"))
            self.param_table.setItem(i, 2, QTableWidgetItem(f"{row['median']:.4g}"))
            self.param_table.setItem(i, 3, QTableWidgetItem(f"{row['ci_lo']:.4g}"))
            self.param_table.setItem(i, 4, QTableWidgetItem(f"{row['ci_hi']:.4g}"))
            rse_str = f"{row['rse']:.1f}" if not math.isnan(row['rse']) else '—'
            self.param_table.setItem(i, 5, QTableWidgetItem(rse_str))

        self.param_table.resizeColumnsToContents()

    def _generate_plots(self):
        """Generate diagnostic plots."""
        if not HAS_MPL or not self._results:
            return

        self._figure.clear()
        method = self._results['method']

        if method == 'bootstrap':
            self._plot_bootstrap()
        else:
            self._plot_sir()

        self._canvas.draw()

    def _plot_bootstrap(self):
        """Generate bootstrap diagnostic plots."""
        samples = self._results['samples']
        param_cols = self._results['param_cols'][:6]  # max 6 params
        original = self._results['original']

        if not samples or not param_cols:
            return

        n_params = len(param_cols)
        n_cols = min(3, n_params)
        n_rows = (n_params + n_cols - 1) // n_cols

        for i, col in enumerate(param_cols):
            ax = self._figure.add_subplot(n_rows, n_cols, i + 1)
            vals = [s[col] for s in samples if col in s]
            if not vals:
                continue

            ax.hist(vals, bins=30, alpha=0.7, color='#4c8aff', edgecolor='none')
            orig = original.get(col, None)
            if orig is not None:
                ax.axvline(orig, color='#e85555', linestyle='--', linewidth=1.5, label='Estimate')
            median = sorted(vals)[len(vals)//2]
            ax.axvline(median, color='#3ec97a', linestyle='-', linewidth=1.5, label='Median')
            ax.set_title(col, fontsize=9)
            ax.tick_params(labelsize=8)
            if i == 0:
                ax.legend(fontsize=7)

        self._figure.tight_layout()

    def _plot_sir(self):
        """Generate SIR diagnostic plots."""
        dofv = self._results.get('dofv', [])
        df = self._results.get('df', 8)

        if not dofv:
            return

        # Plot 1: dOFV distribution
        ax1 = self._figure.add_subplot(1, 2, 1)
        ax1.hist(dofv, bins=50, density=True, alpha=0.7, color='#4c8aff', edgecolor='none')

        # Chi-square overlay
        if HAS_SCIPY and HAS_NP:
            x = np.linspace(0, max(dofv), 200)
            ax1.plot(x, scipy_chi2.pdf(x, df), color='#e85555', linewidth=2,
                    label=f'χ²(df={df})')
            ax1.legend(fontsize=8)

        ax1.set_xlabel('dOFV', fontsize=9)
        ax1.set_ylabel('Density', fontsize=9)
        ax1.set_title('dOFV Distribution', fontsize=10)
        ax1.tick_params(labelsize=8)

        # Plot 2: Parameter distributions (first 3)
        samples = self._results.get('samples', [])
        param_cols = self._results.get('param_cols', [])[:3]

        if samples and param_cols:
            ax2 = self._figure.add_subplot(1, 2, 2)
            for j, col in enumerate(param_cols):
                vals = [s[col] for s in samples if col in s and not math.isnan(s[col])]
                if vals:
                    ax2.hist(vals, bins=30, alpha=0.5, label=col)
            ax2.legend(fontsize=8)
            ax2.set_title('Parameter Distributions', fontsize=10)
            ax2.tick_params(labelsize=8)

        self._figure.tight_layout()

    def _switch_results_tab(self, index: int):
        self._results_stack.setCurrentIndex(index)
        for i, btn in enumerate(self._results_btns):
            btn.setChecked(i == index)


# ══════════════════════════════════════════════════════════════════════════════
# NMTRAN Error Panel (shown in Models tab after failed/warning runs)
# ══════════════════════════════════════════════════════════════════════════════

def render_lst_html(model: dict, raw_text: str, embed: bool = False) -> str:
    """Render a NONMEM .lst file as a structured, readable HTML document."""
    import re as _re

    stem = model.get('stem', 'model')
    t = THEMES[_active_theme]
    is_dark = _active_theme == 'dark'

    # ── Colour palette ────────────────────────────────────────────────────────
    bg       = '#1a1a22' if is_dark else '#f8f8fc'
    bg2      = '#22222e' if is_dark else '#ffffff'
    bg3      = '#2a2a38' if is_dark else '#f0f0f8'
    border   = '#3a3a50' if is_dark else '#dde0f0'
    fg       = '#dde0ee' if is_dark else '#1a1a2e'
    fg2      = '#7a7d9a' if is_dark else '#5a5a70'
    accent   = '#4c8aff'
    green    = '#3ec97a' if is_dark else '#16a34a'
    red      = '#e85555' if is_dark else '#dc2626'
    orange   = '#e89540' if is_dark else '#d97706'
    amber_bg = '#2a1f00' if is_dark else '#fffbeb'
    amber_bd = '#8a6000' if is_dark else '#f59e0b'
    mono     = '"Menlo","Consolas","Courier New",monospace'

    # ── CSS ───────────────────────────────────────────────────────────────────
    css = f"""
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{font-family:-apple-system,system-ui,sans-serif;font-size:13px;
          color:{fg};background:{bg};padding:20px 24px 40px;line-height:1.5;}}
    h1{{font-size:20px;font-weight:800;letter-spacing:-.5px;margin-bottom:2px;}}
    h2{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
        color:{accent};margin:28px 0 10px;padding-left:12px;
        border-left:3px solid {accent};}}
    .card{{background:{bg2};border:1px solid {border};border-radius:10px;
           padding:16px 20px;margin-bottom:16px;}}
    .summary-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-top:12px;}}
    .summary-item{{background:{bg3};border:1px solid {border};border-radius:8px;padding:10px 14px;}}
    .summary-label{{font-size:10px;color:{fg2};text-transform:uppercase;letter-spacing:.5px;}}
    .summary-value{{font-size:16px;font-weight:800;margin-top:3px;}}
    .ok{{color:{green};}} .bad{{color:{red};}} .warn{{color:{orange};}}
    .warn-block{{background:{amber_bg};border:1px solid {amber_bd};border-radius:8px;
                 padding:14px 16px;margin-bottom:12px;}}
    .warn-block h3{{font-size:12px;font-weight:700;color:{orange};margin-bottom:6px;}}
    .warn-block pre{{font-size:11px;font-family:{mono};white-space:pre-wrap;
                     color:{fg};background:transparent;border:none;padding:0;}}
    table{{border-collapse:collapse;width:100%;font-size:12px;}}
    thead th{{background:{bg3};font-weight:700;text-align:left;padding:6px 10px;
              border-bottom:2px solid {border};color:{fg2};text-transform:uppercase;
              font-size:10.5px;letter-spacing:.4px;white-space:nowrap;}}
    td{{padding:5px 10px;border-bottom:1px solid {border};white-space:nowrap;}}
    tr:last-child td{{border-bottom:none;}}
    tr:nth-child(even) td{{background:{bg3};}}
    .num{{text-align:right;font-family:{mono};}}
    .fix{{color:{fg2};font-style:italic;font-size:11px;}}
    .block-sep td{{border-top:2px solid {accent};color:{accent};font-weight:700;
                   font-size:10px;text-transform:uppercase;padding-top:8px;}}
    .good{{color:{green};font-weight:700;}}
    .red{{color:{red};font-weight:700;}}
    .or{{color:{orange};font-weight:700;}}
    .scroll-x{{overflow-x:auto;}}
    details summary{{cursor:pointer;font-size:12px;font-weight:600;
                     color:{fg2};padding:6px 0;list-style:none;}}
    details summary::-webkit-details-marker{{display:none;}}
    details summary::before{{content:'▶ ';font-size:10px;}}
    details[open] summary::before{{content:'▼ ';}}
    pre.raw{{font-family:{mono};font-size:11px;background:{bg3};
             border:1px solid {border};border-radius:6px;padding:12px;
             white-space:pre;overflow-x:auto;color:{fg};line-height:1.4;}}
    .tag{{display:inline-block;font-size:10px;font-weight:700;padding:2px 8px;
          border-radius:10px;margin-left:8px;vertical-align:middle;}}
    .tag-ok{{background:{green}22;color:{green};}}
    .tag-bad{{background:{red}22;color:{red};}}
    .iter-table td,.iter-table th{{padding:4px 10px;}}
    .nav{{position:fixed;right:20px;top:80px;width:140px;font-size:11px;
          background:{bg2};border:1px solid {border};border-radius:8px;
          padding:10px 12px;}}
    .nav a{{display:block;color:{fg2};text-decoration:none;padding:3px 0;}}
    .nav a:hover{{color:{accent};}}
    @media(max-width:900px){{.nav{{display:none;}}}}
    @media print{{.nav{{display:none;}}body{{padding:16px;}}}}
    """

    # ── Helper: parse raw sections ─────────────────────────────────────────
    def between(text, start_pat, end_pat):
        m = _re.search(start_pat, text, _re.IGNORECASE)
        if not m: return ''
        start = m.end()
        m2 = _re.search(end_pat, text[start:], _re.IGNORECASE)
        return text[start:start+m2.start()].strip() if m2 else text[start:start+2000].strip()

    def find_all(text, pat, flags=0):
        return _re.findall(pat, text, flags)

    # ── 1. NM-TRAN warnings ────────────────────────────────────────────────
    nmtran_block = between(raw_text, r'NM-TRAN MESSAGES', r'Note:|License Registered')
    warning_texts = _re.findall(r'\(WARNING\s+\d+\).*?(?=\(WARNING\s+\d+\)|\Z)',
                                nmtran_block, _re.DOTALL)
    warnings_html = ''
    for w in warning_texts:
        w = w.strip()
        if w:
            warnings_html += f'<div class="warn-block"><pre>{w}</pre></div>'

    # ── 2. Summary ─────────────────────────────────────────────────────────
    ofv    = model.get('ofv')
    status = model.get('minimization_message','').strip()
    successful = 'SUCCESSFUL' in status or 'COMPLETED' in status
    status_cls  = 'ok' if successful else 'bad'
    status_tag  = f'<span class="tag {"tag-ok" if successful else "tag-bad"}">' \
                  f'{"✓" if successful else "✗"} {status[:30]}</span>'

    # sig digits
    sigdig_m = _re.search(r'NO\. OF SIG\. DIGITS IN FINAL EST\.\:\s*([\d\.]+)', raw_text)
    sigdig = sigdig_m.group(1) if sigdig_m else '—'

    # n function evals
    nevals_m = _re.search(r'NO\. OF FUNCTION EVALUATIONS USED\:\s*(\d+)', raw_text)
    nevals = nevals_m.group(1) if nevals_m else '—'

    # timing
    timing = {}
    for kind in ('estimation','covariance','postprocess'):
        m = _re.search(fr'Elapsed {kind}\s+time in seconds:\s*([\d\.]+)', raw_text, _re.IGNORECASE)
        if m: timing[kind] = float(m.group(1))
    total_time = sum(timing.values()) if timing else None

    cov  = model.get('covariance_step')
    cn   = model.get('condition_number')
    nind = model.get('n_individuals')
    nobs = model.get('n_observations')
    meth = model.get('estimation_method','')
    aic  = model.get('aic')

    summary_items = [
        ('OFV',             f'{ofv:.4f}' if ofv is not None else '—', ''),
        ('AIC',             f'{aic:.2f}' if aic is not None else '—', ''),
        ('Method',          meth or '—', ''),
        ('Covariance',      ('✓ Successful' if cov else '✗ Failed') if cov is not None else '—',
                            'ok' if cov else 'bad' if cov is False else ''),
        ('Sig. digits',     sigdig, ''),
        ('Func. evals',     nevals, ''),
        ('Individuals',     str(nind) if nind else '—', ''),
        ('Observations',    str(nobs) if nobs else '—', ''),
        ('CN',              f'{cn:.1f}' if cn else '—',
                            'or' if cn and cn > 1000 else ''),
        ('Runtime',         f'{total_time:.1f} s' if total_time else '—', ''),
    ]
    summary_cards = ''.join(
        f'<div class="summary-item">'
        f'<div class="summary-label">{lbl}</div>'
        f'<div class="summary-value {cls}">{val}</div></div>'
        for lbl,val,cls in summary_items)

    # ── 3. Control stream (everything before NM-TRAN MESSAGES) ────────────
    ctrl_end = raw_text.find('NM-TRAN MESSAGES')
    ctrl_stream = raw_text[:ctrl_end].strip() if ctrl_end > 0 else ''
    # Syntax-highlight $RECORDS in the control stream for HTML
    def hl_ctrl(s):
        s = s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
        s = _re.sub(r'(\$[A-Z]+)', r'<span style="color:#4c8aff;font-weight:700;">\1</span>', s)
        s = _re.sub(r'(;[^\n]*)', r'<span style="color:#6a9955;font-style:italic;">\1</span>', s)
        return s

    # ── 4. Iteration trace ─────────────────────────────────────────────────
    iter_blocks = _re.findall(
        r'ITERATION NO\.\:\s+(\d+)\s+OBJECTIVE VALUE\:\s+([\d\.\-\+E]+)',
        raw_text)
    iter_rows = ''
    prev_ofv = None
    for it, ov in iter_blocks:
        ov_f = float(ov)
        delta = f'{ov_f-prev_ofv:+.3f}' if prev_ofv is not None else '—'
        dcls  = 'ok' if prev_ofv and ov_f < prev_ofv else ''
        iter_rows += (f'<tr><td class="num">{it}</td>'
                      f'<td class="num">{ov_f:.4f}</td>'
                      f'<td class="num {dcls}">{delta}</td></tr>')
        prev_ofv = ov_f
    iter_html = (f'<table class="iter-table"><thead><tr>'
                 f'<th>Iteration</th><th>OFV</th><th>ΔOFV</th></tr></thead>'
                 f'<tbody>{iter_rows}</tbody></table>') if iter_rows else '<p>Not found</p>'

    # ── 5. ETABAR ──────────────────────────────────────────────────────────
    etabar_v = model.get('etabar',[])
    etabar_se = model.get('etabar_se',[])
    etabar_pv = model.get('etabar_pval',[])
    # Fallback: parse from raw
    if not etabar_v:
        eb_m = _re.search(r'ETABAR:\s+([\d\.\-\+E\s]+)\n', raw_text)
        if eb_m:
            etabar_v = [float(x) for x in eb_m.group(1).split()]
        pv_m = _re.search(r'P VAL\.:\s+([\d\.\-\+E\s]+)\n', raw_text)
        if pv_m:
            etabar_pv = [float(x) for x in pv_m.group(1).split()]
    etabar_rows = ''
    for i, eb in enumerate(etabar_v):
        pv = etabar_pv[i] if i < len(etabar_pv) else None
        se_ = etabar_se[i] if i < len(etabar_se) else None
        pv_cls = 'red' if pv is not None and pv < 0.05 else ''
        etabar_rows += (f'<tr><td>ETA({i+1})</td>'
                        f'<td class="num">{eb:.4f}</td>'
                        f'<td class="num">{fmt_num(se_) if se_ else "—"}</td>'
                        f'<td class="num {pv_cls}">{f"{pv:.4f}" if pv else "—"}</td></tr>')
    etabar_html = (f'<table><thead><tr><th>ETA</th><th>ETABAR</th>'
                   f'<th>SE</th><th>P-value</th></tr></thead>'
                   f'<tbody>{etabar_rows}</tbody></table>') if etabar_rows else \
                  '<p style="color:#888;">Not available</p>'

    # ── 6. Shrinkage ───────────────────────────────────────────────────────
    eta_shr = model.get('eta_shrinkage',[])
    eps_shr = model.get('eps_shrinkage',[])
    shr_rows = ''
    for i, v in enumerate(eta_shr):
        cls = 'red' if v > 30 else 'or' if v > 20 else 'ok'
        shr_rows += f'<tr><td>ETA({i+1})</td><td class="num {cls}">{v:.1f}%</td></tr>'
    for i, v in enumerate(eps_shr):
        cls = 'red' if v > 30 else 'or' if v > 20 else 'ok'
        shr_rows += f'<tr><td>EPS({i+1})</td><td class="num {cls}">{v:.1f}%</td></tr>'
    shr_html = (f'<table><thead><tr><th>Parameter</th>'
                f'<th>Shrinkage SD%</th></tr></thead>'
                f'<tbody>{shr_rows}</tbody></table>') if shr_rows else \
               '<p style="color:#888;">Not available</p>'

    # ── Helper: parse NONMEM matrix ──────────────────────────────────────────
    def parse_nonmem_matrix(block):
        """
        Parse a NONMEM matrix block (triangular or full).
        Handles both spaced labels 'TH 1', 'TH 2' and compact 'OM11', 'SG11'.
        Returns (labels, n×n matrix) where matrix[i][j] = float or None.
        """
        lines = block.splitlines()
        label_re = _re.compile(r'(?:TH|OM|SG|ETA|EPS)\s*\d+', _re.IGNORECASE)

        # Header lines contain ONLY parameter tokens and whitespace
        labels = []
        for line in lines:
            stripped = line.strip()
            if not stripped: continue
            # Remove all tokens — if anything non-whitespace remains it's not a header
            cleaned = label_re.sub('', stripped)
            if cleaned.strip(): continue
            for lbl in label_re.findall(stripped):
                compact = lbl.replace(' ', '')
                if compact not in labels:
                    labels.append(compact)

        if not labels: return [], []
        n = len(labels)
        mat = [[None]*n for _ in range(n)]

        row_lbl_re = _re.compile(
            r'^\s+((?:TH|OM|SG|ETA|EPS)\s*\d+)\s*$', _re.IGNORECASE)
        val_re = _re.compile(r'^\+(.*)')

        i = 0
        while i < len(lines):
            lm = row_lbl_re.match(lines[i])
            if lm:
                raw_lbl = lm.group(1).replace(' ', '')
                if raw_lbl in labels:
                    ri = labels.index(raw_lbl)
                    j = i + 1
                    while j < len(lines) and not lines[j].strip(): j += 1
                    if j < len(lines):
                        vm = val_re.match(lines[j])
                        if vm:
                            parts = vm.group(1).split()
                            for ci, p in enumerate(parts):
                                if ci >= n: break
                                if _re.match(r'^\.*$', p):
                                    mat[ri][ci] = None
                                else:
                                    try: mat[ri][ci] = float(p)
                                    except ValueError: mat[ri][ci] = None
                    i = j
            i += 1
        return labels, mat

    def render_matrix_html(labels, mat, is_correlation=False):
        """Render a list-of-lists matrix as a bordered HTML table."""
        if not labels: return ''
        hdr = ''.join(
            f'<th style="padding:5px 10px;white-space:nowrap;background:{bg3};">{l}</th>'
            for l in labels)
        crows = ''
        for i in range(len(labels)):
            cells = ''
            for j in range(len(labels)):
                v = mat[i][j] if i < len(mat) and j < len(mat[i]) else None
                if v is None:
                    cells += f'<td class="num" style="color:{fg2};">·</td>'
                else:
                    cls = ''
                    if is_correlation and i != j:
                        a = abs(v)
                        cls = 'red' if a > 0.95 else ('or' if a > 0.7 else '')
                    cells += f'<td class="num {cls}">{v:.4g}</td>'
            crows += (f'<tr><th style="text-align:left;font-weight:700;'
                      f'padding:5px 10px;white-space:nowrap;background:{bg3};">'
                      f'{labels[i]}</th>{cells}</tr>')
        return (f'<div class="scroll-x"><table style="border-collapse:collapse;">'
                f'<thead><tr><th style="background:{bg3};padding:5px 10px;"></th>{hdr}</tr></thead>'
                f'<tbody>{crows}</tbody></table></div>')

    # ── Find the FINAL PARAMETER ESTIMATE section block ───────────────────────
    # This comes after the rows of stars with "FINAL PARAMETER ESTIMATE"
    final_m = _re.search(
        r'FINAL PARAMETER ESTIMATE.*?\n[\*\s]+\n(.*?)(?=\n[\*\s]{60,}\n|\Z)',
        raw_text, _re.DOTALL | _re.IGNORECASE)
    final_block = final_m.group(1) if final_m else ''

    se_m = _re.search(
        r'STANDARD ERROR OF ESTIMATE.*?\n[\*\s]+\n(.*?)(?=\n[\*\s]{60,}\n|\Z)',
        raw_text, _re.DOTALL | _re.IGNORECASE)
    se_block = se_m.group(1) if se_m else ''

    cor_raw_m = _re.search(
        r'CORRELATION MATRIX OF ESTIMATE.*?\n[\*\s]+\n(.*?)(?=\n[\*\s]{60,}\n|\Z)',
        raw_text, _re.DOTALL | _re.IGNORECASE)
    cor_raw_block = cor_raw_m.group(1) if cor_raw_m else ''

    cov_raw_m = _re.search(
        r'COVARIANCE MATRIX OF ESTIMATE.*?\n[\*\s]+\n(.*?)(?=\n[\*\s]{60,}\n|\Z)',
        raw_text, _re.DOTALL | _re.IGNORECASE)
    cov_raw_block = cov_raw_m.group(1) if cov_raw_m else ''

    # ── Parse theta/omega/sigma from raw if not in model dict ─────────────────
    def parse_theta_from_block(block):
        """Extract THETA values from final parameter block."""
        th_m = _re.search(r'THETA.*?VECTOR.*?\n\s+(.*?)\n\s+(.*?)\n', block, _re.DOTALL)
        if not th_m: return [], []
        labels = th_m.group(1).split()
        vals_str = th_m.group(2).split()
        vals = []
        for v in vals_str:
            try: vals.append(float(v))
            except ValueError: vals.append(None)
        return labels, vals

    def parse_omega_sigma_from_block(blk, name):
        """Extract OMEGA or SIGMA lower triangular from block."""
        m = _re.search(name + r'.*?MATRIX.*?\n(.*?)(?=\n\s*\n\s*(?:SIGMA|OMEGA|1\n|\Z))',
                       blk, _re.DOTALL | _re.IGNORECASE)
        if not m: return [], []
        section = m.group(1)
        labels_m = _re.search(r'^\s+((?:ETA\d+\s+|EPS\d+\s+)+)', section, _re.MULTILINE)
        if not labels_m: return [], []
        labels = labels_m.group(0).split()
        vals = []
        for row_m in _re.finditer(r'\+?\s*((?:[\d\.\-\+E]+|\.{9})\s*)+', section):
            row_vals = []
            for v in row_m.group(0).split():
                try: row_vals.append(float(v))
                except ValueError: row_vals.append(None)
            if row_vals: vals.append(row_vals)
        return labels, vals

    # ── 7. Parameters ──────────────────────────────────────────────────────────
    param_rows = ''
    blocks = [
        ('THETA','thetas','theta_ses','theta_names','theta_units','theta_fixed'),
        ('OMEGA','omegas','omega_ses','omega_names','omega_units','omega_fixed'),
        ('SIGMA','sigmas','sigma_ses','sigma_names','sigma_units','sigma_fixed'),
    ]
    import math as _math

    for block, ek, sk, nk, uk, fk in blocks:
        ests = model.get(ek,[]); ses = model.get(sk,[])
        names = model.get(nk,[]); units = model.get(uk,[])
        fixed = model.get(fk,[])
        if not ests: continue
        param_rows += f'<tr class="block-sep"><td colspan="8">{block}</td></tr>'
        for i, est in enumerate(ests):
            se   = ses[i]   if i < len(ses)   else None
            nm   = names[i] if i < len(names) else ''
            un   = units[i] if i < len(units) else ''
            fx   = fixed[i] if i < len(fixed) else False
            rse_v = abs(se/est)*100 if se and est and abs(est)>1e-12 else None
            rse_s = f'{rse_v:.1f}%' if rse_v is not None else ('...' if se is None and not fx else '—')
            rse_cls = ('red' if rse_v and rse_v>=50 else 'or' if rse_v and rse_v>=25 else 'ok') if rse_v else ''
            ci_lo = f'{est - 1.96*se:.4g}' if se else '—'
            ci_hi = f'{est + 1.96*se:.4g}' if se else '—'
            sd_s = f'{_math.sqrt(max(est,0)):.4g}' if block in ('OMEGA','SIGMA') and est is not None and est >= 0 else ''
            lbl = f'{block}({i+1})'
            fix_tag = ' <span class="fix">FIX</span>' if fx else ''
            param_rows += (
                f'<tr><td>{lbl}{fix_tag}</td><td>{nm}</td>'
                f'<td class="num">{fmt_num(est)}</td>'
                f'<td class="num">{sd_s}</td>'
                f'<td class="num">{fmt_num(se) if se is not None else ("..." if not fx else "—")}</td>'
                f'<td class="num {rse_cls}">{rse_s}</td>'
                f'<td class="num">[{ci_lo}, {ci_hi}]</td>'
                f'<td>{un}</td></tr>')

    param_html = (f'<div class="scroll-x"><table>'
                  f'<thead><tr><th>Parameter</th><th>Name</th><th>Estimate</th>'
                  f'<th>SD</th><th>SE</th><th>RSE%</th><th>95% CI</th><th>Units</th>'
                  f'</tr></thead><tbody>{param_rows}</tbody></table></div>'
                  if param_rows else
                  '<p style="color:#888;">Parameters not available — .lst may not have run successfully</p>')

    # ── 8. Covariance matrix ───────────────────────────────────────────────────
    cov_html = ''
    if cov_raw_block:
        lbls, mat = parse_nonmem_matrix(cov_raw_block)
        if lbls:
            cov_html = render_matrix_html(lbls, mat, is_correlation=False)
    if not cov_html:
        cov_html = '<p style="color:#888;">Not available (requires successful covariance step)</p>'

    # ── 9. Correlation matrix ──────────────────────────────────────────────────
    cor_html = ''
    # Try model dict first, then raw text
    cor_mat  = model.get('correlation_matrix',[])
    cor_lbls = model.get('cor_labels',[])
    if cor_mat and cor_lbls:
        cor_html = render_matrix_html(cor_lbls, cor_mat, is_correlation=True)
    elif cor_raw_block:
        lbls, mat = parse_nonmem_matrix(cor_raw_block)
        if lbls:
            cor_html = render_matrix_html(lbls, mat, is_correlation=True)
    if not cor_html:
        cor_html = '<p style="color:#888;">Not available (requires successful covariance step with PRINT=E)</p>'

    # ── 9. Eigenvalues ─────────────────────────────────────────────────────
    eig_m = _re.search(r'EIGENVALUES OF COR MATRIX.*?\n([\s\d\.E\+\-]+)\n', raw_text, _re.DOTALL)
    eig_html = ''
    if eig_m:
        vals = [float(x) for x in eig_m.group(1).split() if x.replace('.','').replace('-','').replace('+','').replace('E','').isdigit() or _re.match(r'[\d\.E\+\-]+', x)]
        if vals:
            mn, mx = min(vals), max(vals)
            cn_calc = mx/mn if mn > 0 else float('inf')
            cn_cls = 'red' if cn_calc > 1000 else 'or' if cn_calc > 100 else 'ok'
            eig_vals = '  '.join(f'{v:.3E}' for v in vals)
            eig_html = (f'<p style="font-family:{mono};font-size:12px;margin-bottom:8px;">{eig_vals}</p>'
                        f'<p>Min: <b>{mn:.3E}</b>  ·  Max: <b>{mx:.3E}</b>  ·  '
                        f'Condition number: <b class="{cn_cls}">{cn_calc:.1f}</b>'
                        f'{"  ⚠ CN > 1000: near-collinearity" if cn_calc > 1000 else ""}</p>')
    if not eig_html:
        if cn:
            cn_cls = 'red' if cn > 1000 else 'or' if cn > 100 else 'ok'
            eig_html = f'<p>Condition number: <b class="{cn_cls}">{cn:.1f}</b></p>'
        else:
            eig_html = '<p style="color:#888;">Not available</p>'

    # ── 10. Nav ────────────────────────────────────────────────────────────
    nav = f'''<div class="nav">
      <div style="font-size:10px;font-weight:700;color:{fg2};text-transform:uppercase;
                  letter-spacing:.5px;margin-bottom:8px;">Jump to</div>
      <a href="#summary">📊 Summary</a>
      {"<a href='#warnings'>⚠ Warnings</a>" if warnings_html else ""}
      <a href="#convergence">↻ Convergence</a>
      <a href="#parameters">θ Parameters</a>
      <a href="#etabar">η ETABAR</a>
      <a href="#correlation">ρ Correlation</a>
      <a href="#covariance">Σ Covariance</a>
      <a href="#eigenvalues">λ Eigenvalues</a>
      {"" if embed else "<a href='#raw'>⌨ Raw</a>"}
    </div>'''

    # ── Assemble ───────────────────────────────────────────────────────────
    from datetime import datetime as _dt
    now = _dt.now().strftime('%Y-%m-%d %H:%M')

    html = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8">
<title>{stem}.lst — NMGUI</title>
<style>{css}</style>
</head><body>
{nav}
<h1 id="summary">{stem}.lst {status_tag}</h1>
<p style="color:{fg2};font-size:12px;margin-bottom:16px;">
  {model.get('problem','')}  ·  Rendered by NMGUI v{APP_VERSION}  ·  {now}
</p>
<div class="card"><div class="summary-grid">{summary_cards}</div></div>

{"<h2 id='warnings'>⚠ NM-TRAN Warnings</h2>" + warnings_html if warnings_html else ""}

<h2 id="convergence">Convergence</h2>
<div class="card">{iter_html}</div>

<h2 id="parameters">Parameter Estimates</h2>
<div class="card">{param_html}</div>

<h2 id="etabar">ETABAR &amp; Shrinkage</h2>
<div class="card" style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
  <div><h3 style="font-size:11px;font-weight:700;color:{fg2};margin-bottom:8px;
       text-transform:uppercase;letter-spacing:.5px;">ETABAR</h3>{etabar_html}</div>
  <div><h3 style="font-size:11px;font-weight:700;color:{fg2};margin-bottom:8px;
       text-transform:uppercase;letter-spacing:.5px;">Shrinkage</h3>{shr_html}</div>
</div>

<h2 id="correlation">Correlation Matrix</h2>
<div class="card">{cor_html}</div>

<h2 id="covariance">Covariance Matrix</h2>
<div class="card">{cov_html}</div>

<h2 id="eigenvalues">Eigenvalues &amp; Condition Number</h2>
<div class="card">{eig_html}</div>

{"" if embed else f'''
<details style="margin-top:24px;">
<summary id="raw">Control stream</summary>
<pre class="raw" style="margin-top:8px;">{hl_ctrl(ctrl_stream)}</pre>
</details>

<details style="margin-top:12px;">
<summary>Raw .lst output</summary>
<pre class="raw" style="margin-top:8px;">{raw_text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")}</pre>
</details>
'''}

</body></html>"""
    return html


class LstOutputWidget(QWidget):
    """Rendered .lst viewer — embedded QTextBrowser + Open in browser button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = None; self._raw_text = ''
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        # Toolbar
        tb = QWidget(); tb.setFixedHeight(36)
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(8,4,8,4); tbl.setSpacing(8)
        self._status_lbl = QLabel('No model selected')
        self._status_lbl.setStyleSheet(f'color:{C_FG2};font-size:12px;')
        tbl.addWidget(self._status_lbl, 1)
        self._browser_btn = QPushButton('Open in browser')
        self._browser_btn.setFixedHeight(26)
        self._browser_btn.setEnabled(False)
        self._browser_btn.clicked.connect(self._open_browser)
        tbl.addWidget(self._browser_btn)
        v.addWidget(tb)

        sep = QWidget(); sep.setFixedHeight(1)
        sep.setStyleSheet(f'background:{C_BORDER};')
        v.addWidget(sep)

        # QTextBrowser renders basic HTML tables and CSS
        from PyQt6.QtWidgets import QTextBrowser
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setPlaceholderText('Select a model with a .lst file to render output.')
        v.addWidget(self._browser, 1)

    def load_model(self, model):
        self._model = model
        lst_path = model.get('lst_path','')
        if not lst_path or not Path(lst_path).is_file():
            self._status_lbl.setText(f'{model.get("stem","")} — no .lst file')
            self._browser_btn.setEnabled(False)
            self._browser.setPlainText('No .lst file found for this model.')
            return
        try:
            self._raw_text = Path(lst_path).read_text('utf-8', errors='replace')
        except Exception as e:
            self._browser.setPlainText(f'Could not read .lst file:\n{e}'); return
        self._status_lbl.setText(f'{model.get("stem","")} — {Path(lst_path).name}')
        self._browser_btn.setEnabled(True)
        html = render_lst_html(model, self._raw_text, embed=True)
        self._browser.setHtml(html)

    def _open_browser(self):
        if not self._model: return
        import tempfile, webbrowser
        html = render_lst_html(self._model, self._raw_text, embed=False)
        tmp = tempfile.NamedTemporaryFile(suffix='.html', delete=False,
                                          mode='w', encoding='utf-8')
        tmp.write(html); tmp.flush(); tmp_name = tmp.name; tmp.close()
        webbrowser.open(f'file://{tmp_name}')
        QTimer.singleShot(30000, lambda: Path(tmp_name).unlink(missing_ok=True))


class LstViewerDialog(QDialog):
    """Non-modal .lst file viewer with search."""
    def __init__(self, stem, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'{stem}.lst')
        self.resize(820, 640)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        v = QVBoxLayout(self); v.setContentsMargins(8,8,8,8); v.setSpacing(6)

        # Search bar
        search_row = QHBoxLayout()
        self._search = QLineEdit(); self._search.setPlaceholderText('Search… (Enter = next, Shift+Enter = prev)')
        self._search.returnPressed.connect(self._find_next)
        self._match_lbl = QLabel('')
        self._match_lbl.setStyleSheet(f'color:{C_FG2};font-size:11px;')
        prev_btn = QPushButton('^'); prev_btn.setFixedWidth(32); prev_btn.clicked.connect(self._find_prev)
        next_btn = QPushButton('v'); next_btn.setFixedWidth(32); next_btn.clicked.connect(self._find_next)
        search_row.addWidget(self._search, 1); search_row.addWidget(prev_btn)
        search_row.addWidget(next_btn); search_row.addWidget(self._match_lbl)
        v.addLayout(search_row)

        # Text viewer
        self._editor = QPlainTextEdit()
        self._editor.setReadOnly(True)
        self._editor.setFont(QFont('Menlo' if IS_MAC else 'Consolas', 11))
        self._editor.setPlainText(text)
        v.addWidget(self._editor, 1)

        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.close)
        btn_row = QHBoxLayout(); btn_row.addStretch(); btn_row.addWidget(close_btn)
        v.addLayout(btn_row)

        self._search.textChanged.connect(self._highlight_all)
        self._positions = []; self._pos_idx = 0

    def _highlight_all(self):
        from PyQt6.QtGui import QTextCharFormat, QTextCursor
        # Clear existing
        cursor = self._editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        fmt_clear = QTextCharFormat(); fmt_clear.setBackground(QColor('transparent'))
        cursor.mergeCharFormat(fmt_clear)
        self._positions = []; self._pos_idx = 0
        term = self._search.text()
        if not term: self._match_lbl.setText(''); return
        doc = self._editor.document()
        fmt = QTextCharFormat(); fmt.setBackground(QColor('#ffdd44' if _active_theme=='light' else '#554400'))
        cursor = doc.find(term)
        while not cursor.isNull():
            self._positions.append(cursor.position())
            cursor.mergeCharFormat(fmt)
            cursor = doc.find(term, cursor)
        n = len(self._positions)
        self._match_lbl.setText(f'{n} match{"es" if n!=1 else ""}' if n else 'Not found')
        if n: self._goto(0)

    def _goto(self, idx):
        if not self._positions: return
        self._pos_idx = idx % len(self._positions)
        c = self._editor.textCursor()
        c.setPosition(self._positions[self._pos_idx])
        self._editor.setTextCursor(c)
        self._editor.ensureCursorVisible()
        self._match_lbl.setText(f'{self._pos_idx+1} / {len(self._positions)}')

    def _find_next(self): self._goto(self._pos_idx + 1)
    def _find_prev(self): self._goto(self._pos_idx - 1)


class ModelComparisonDialog(QDialog):
    """Side-by-side parameter comparison for two models."""

    def __init__(self, model_a, model_b, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Compare: {model_a["stem"]}  vs  {model_b["stem"]}')
        self.resize(900, 620)
        v = QVBoxLayout(self); v.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        for m, align in [(model_a, Qt.AlignmentFlag.AlignLeft),
                         (model_b, Qt.AlignmentFlag.AlignRight)]:
            lbl = QLabel(f'<b>{m["stem"]}</b><br>'
                         f'<span style="color:{C_FG2};font-size:11px;">'
                         f'OFV: {fmt_ofv(m.get("ofv"))}  ·  '
                         f'{m.get("estimation_method","")}  ·  '
                         f'{"✓ COV" if m.get("covariance_step") else ""}</span>')
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setAlignment(align)
            hdr.addWidget(lbl, 1)
        dofv = None
        if model_a.get('ofv') is not None and model_b.get('ofv') is not None:
            dofv = model_b['ofv'] - model_a['ofv']
        mid_lbl = QLabel(f'<b>ΔOFV: {dofv:+.3f}</b>' if dofv is not None else 'ΔOFV: —')
        mid_lbl.setTextFormat(Qt.TextFormat.RichText)
        mid_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col = C_GREEN if dofv is not None and dofv < -3.84 else \
              C_ORANGE if dofv is not None and dofv < 0 else C_RED if dofv is not None else C_FG2
        mid_lbl.setStyleSheet(f'color:{col};font-size:14px;')
        hdr.insertWidget(1, mid_lbl)
        v.addLayout(hdr)

        # Comparison table
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        cols = ['Parameter', 'Name',
                f'{model_a["stem"]} Est.', f'{model_a["stem"]} RSE%',
                f'{model_b["stem"]} Est.', f'{model_b["stem"]} RSE%',
                'Δ Est.', 'Δ%']
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        chh = self.table.horizontalHeader()
        chh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        chh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c in range(2, len(cols)):
            chh.resizeSection(c, 90)
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

        rows = self._build_rows(model_a, model_b)
        self.table.setRowCount(len(rows))
        R = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        L = Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter
        grey = QBrush(QColor(C_FG2))

        for ri, row_data in enumerate(rows):
            lbl, nm, est_a, rse_a, est_b, rse_b, delta, delta_pct, is_block, is_fixed = row_data
            if is_block:
                for ci in range(len(cols)):
                    item = QTableWidgetItem(lbl if ci == 0 else '')
                    item.setBackground(QBrush(QColor(C_BG3)))
                    item.setForeground(QBrush(QColor(C_BLUE)))
                    f = item.font(); f.setBold(True); f.setPointSize(10); item.setFont(f)
                    self.table.setItem(ri, ci, item)
                continue
            vals = [lbl, nm, est_a, rse_a, est_b, rse_b, delta, delta_pct]
            aligns = [L, L, R, R, R, R, R, R]
            for ci, (txt, align) in enumerate(zip(vals, aligns)):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(align)
                if is_fixed: item.setForeground(grey)
                # Colour delta: green = improved RSE, red = worse
                if ci == 6 and txt and txt not in ('—', ''):
                    try:
                        d = float(txt)
                        item.setForeground(QBrush(QColor(C_GREEN if d < 0 else C_RED)))
                    except ValueError: pass
                if ci == 7 and txt and txt not in ('—', ''):
                    try:
                        dp = float(txt.rstrip('%'))
                        item.setForeground(QBrush(QColor(C_GREEN if abs(dp) < 20 else C_ORANGE if abs(dp) < 50 else C_RED)))
                    except ValueError: pass
                self.table.setItem(ri, ci, item)

        v.addWidget(self.table, 1)

        # Shrinkage comparison
        shr_a = model_a.get('eta_shrinkage',[])
        shr_b = model_b.get('eta_shrinkage',[])
        if shr_a or shr_b:
            def fmt_shr(s): return '  '.join(f'ETA{i+1}: {v:.1f}%' for i,v in enumerate(s)) if s else '—'
            shr_lbl = QLabel(f'Shrinkage  {model_a["stem"]}: {fmt_shr(shr_a)}    '
                             f'{model_b["stem"]}: {fmt_shr(shr_b)}')
            shr_lbl.setStyleSheet(f'color:{C_FG2};font-size:11px;')
            v.addWidget(shr_lbl)

        # Buttons
        btn_row = QHBoxLayout()
        export_btn = QPushButton('Export CSV')
        export_btn.clicked.connect(lambda: self._export_csv(model_a, model_b, rows))
        close_btn = QPushButton('Close'); close_btn.setObjectName('primary')
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(export_btn); btn_row.addStretch(); btn_row.addWidget(close_btn)
        v.addLayout(btn_row)

    def _build_rows(self, ma, mb):
        """Build comparison rows. Returns list of tuples."""
        rows = []
        blocks = [
            ('THETA', 'thetas','theta_ses','theta_names','theta_units','theta_fixed'),
            ('OMEGA', 'omegas','omega_ses','omega_names','omega_units','omega_fixed'),
            ('SIGMA', 'sigmas','sigma_ses','sigma_names','sigma_units','sigma_fixed'),
        ]
        for block, ek, sk, nk, uk, fk in blocks:
            ests_a = ma.get(ek,[]); ses_a = ma.get(sk,[]); names_a = ma.get(nk,[])
            units_a = ma.get(uk,[]); fixed_a = ma.get(fk,[])
            ests_b = mb.get(ek,[]); ses_b = mb.get(sk,[]); names_b = mb.get(nk,[])
            n = max(len(ests_a), len(ests_b))
            if n == 0: continue
            # Block header row
            rows.append((block,'','','','','','','', True, False))
            for i in range(n):
                ea  = ests_a[i] if i < len(ests_a) else None
                se_a= ses_a[i]  if i < len(ses_a)  else None
                eb  = ests_b[i] if i < len(ests_b) else None
                se_b= ses_b[i]  if i < len(ses_b)  else None
                nm  = (names_a[i] if i < len(names_a) else '') or \
                      (names_b[i] if i < len(names_b) else '')
                fx  = (fixed_a[i] if i < len(fixed_a) else False) or \
                      (mb.get(fk,[])[i] if i < len(mb.get(fk,[])) else False)
                lbl = f'{block}({i+1})'

                def _est(e): return fmt_num(e) if e is not None else '—'
                def _rse(e,s):
                    if e is None: return '—'
                    return fmt_rse(e,s) if s is not None else '...'
                def _delta(a,b):
                    if a is None or b is None: return '—'
                    return f'{b-a:+.4g}'
                def _dpct(a,b):
                    if a is None or b is None or abs(a) < 1e-12: return '—'
                    return f'{(b-a)/abs(a)*100:+.1f}%'

                rows.append((lbl, nm,
                             _est(ea), _rse(ea, se_a),
                             _est(eb), _rse(eb, se_b),
                             _delta(ea, eb), _dpct(ea, eb),
                             False, fx))
        return rows

    def _export_csv(self, ma, mb, rows):
        import csv as _csv
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Export comparison',
            str(HOME / f'compare_{ma["stem"]}_vs_{mb["stem"]}.csv'),
            'CSV files (*.csv)')
        if not dst: return
        with open(dst, 'w', newline='', encoding='utf-8') as f:
            w = _csv.writer(f)
            w.writerow(['Parameter','Name',
                        f'{ma["stem"]}_estimate', f'{ma["stem"]}_RSE',
                        f'{mb["stem"]}_estimate', f'{mb["stem"]}_RSE',
                        'delta_estimate', 'delta_pct'])
            for row in rows:
                if not row[8]:  # skip block headers
                    w.writerow(row[:8])


class NMTRANPanel(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'NMTRAN messages — {model.get("stem","")}')
        self.resize(700, 400)
        v = QVBoxLayout(self)
        self.text = QPlainTextEdit(); self.text.setReadOnly(True)
        self.text.setFont(QFont('Menlo' if IS_MAC else 'Consolas',12))
        v.addWidget(self.text)
        close = QPushButton('Close'); close.clicked.connect(self.accept)
        v.addWidget(close)
        self._load(model)

    def _load(self, model):
        if not HAS_PARSER: self.text.setPlainText('parser.py not available'); return
        base_dir = str(Path(model['path']).parent)
        stem     = model['stem']
        errors   = parse_nmtran_errors(base_dir, stem)
        if not errors:
            # Fall back to first 3000 chars of .lst
            if model.get('lst_path'):
                try:
                    txt = Path(model['lst_path']).read_text('utf-8', errors='replace')[:3000]
                    self.text.setPlainText(txt)
                except Exception:
                    self.text.setPlainText('No NMTRAN messages found.')
            else:
                self.text.setPlainText('No NMTRAN messages found.')
            return
        lines = []
        for e in errors:
            tag = '[ERROR]' if e.get('type')=='error' else '[INFO] '
            lines.append(f'{tag} {e.get("message","")}')
        self.text.setPlainText('\n'.join(lines))


# ══════════════════════════════════════════════════════════════════════════════
# Settings Tab
# ══════════════════════════════════════════════════════════════════════════════

class RunHistoryTab(QWidget):
    """Displays all recorded NONMEM runs from runs.json."""

    COLS = ['Model', 'Tool', 'Status', 'Started', 'Duration', 'Directory']

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self); v.setContentsMargins(16,12,16,12); v.setSpacing(8)

        # Toolbar
        tb = QHBoxLayout()
        tb.addWidget(QLabel('Run History'))
        tb.addStretch()
        self._filter = QLineEdit(); self._filter.setPlaceholderText('Filter by model name or tool…')
        self._filter.setFixedWidth(280); self._filter.textChanged.connect(self._apply_filter)
        refresh_btn = QPushButton('↻ Refresh'); refresh_btn.setFixedHeight(26)
        refresh_btn.clicked.connect(self.load)
        clear_btn = QPushButton('Clear history'); clear_btn.setFixedHeight(26)
        clear_btn.clicked.connect(self._clear)
        tb.addWidget(self._filter); tb.addWidget(refresh_btn); tb.addWidget(clear_btn)
        v.addLayout(tb)

        # Table
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.resizeSection(1, 90)
        hh.resizeSection(2, 90)
        hh.resizeSection(3, 145)
        hh.resizeSection(4, 75)
        hh.resizeSection(5, 200)
        self.table.setMinimumHeight(200)
        v.addWidget(self.table, 1)

        # Command preview
        sep = QWidget(); sep.setFixedHeight(1)
        sep.setStyleSheet(f'background:{C_BORDER};'); v.addWidget(sep)
        cmd_lbl = QLabel('Command')
        cmd_lbl.setStyleSheet(f'color:{C_FG2};font-size:11px;font-weight:700;text-transform:uppercase;')
        v.addWidget(cmd_lbl)
        self._cmd_view = QPlainTextEdit()
        self._cmd_view.setReadOnly(True)
        self._cmd_view.setFixedHeight(52)
        self._cmd_view.setFont(QFont('Menlo' if sys.platform=='darwin' else 'Consolas', 11))
        self._cmd_view.setPlaceholderText('Select a row to see the full command')
        v.addWidget(self._cmd_view)

        self.table.currentCellChanged.connect(lambda row,_,__,___: self._on_row(row))
        self._runs = []; self._filtered_runs = []
        self.load()

    def load(self):
        self._runs = load_runs()
        self._apply_filter(self._filter.text())

    def _apply_filter(self, text=''):
        term = text.strip().lower()
        self.table.setRowCount(0)
        self._filtered_runs = []  # track what's visible for _on_row
        R = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        L = Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter
        for run in self._runs:
            name = run.get('run_name',''); tool = run.get('tool','')
            if term and term not in name.lower() and term not in tool.lower():
                continue
            self._filtered_runs.append(run)
        for run in self._filtered_runs:
            name = run.get('run_name',''); tool = run.get('tool','')
            status = run.get('status','running')
            finished = run.get('finished')
            # Normalise legacy statuses from before the status-fix
            if status == 'finished' or (status == 'running' and finished):
                status_display = 'ok'; status_col = QColor(C_GREEN)
            elif status == 'ok':
                status_display = 'ok'; status_col = QColor(C_GREEN)
            elif 'fail' in str(status):
                status_display = status; status_col = QColor(C_RED)
            elif status == 'running' and not finished:
                status_display = 'unknown'; status_col = QColor(C_FG2)
            else:
                status_display = status; status_col = QColor(C_FG2)
            started = run.get('started','')
            # Format started timestamp
            try:
                from datetime import datetime as _dt
                dt = _dt.fromisoformat(started)
                started_fmt = dt.strftime('%Y-%m-%d  %H:%M:%S')
            except Exception:
                started_fmt = started[:19] if started else '—'
            # Duration
            duration = '—'
            try:
                if finished and started:
                    from datetime import datetime as _dt
                    s = _dt.fromisoformat(started); f = _dt.fromisoformat(finished)
                    secs = int((f - s).total_seconds())
                    duration = f'{secs//60}m {secs%60}s' if secs >= 60 else f'{secs}s'
                elif status == 'running' and not finished:
                    duration = '…'
            except Exception:
                pass
            directory = str(Path(run.get('working_dir', run.get('model',''))).name)
            row = self.table.rowCount(); self.table.insertRow(row)
            cells = [(name,L),(tool,L),(status_display,L),(started_fmt,L),(duration,R),(directory,L)]
            for ci, (txt, align) in enumerate(cells):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(align)
                if ci == 2:
                    item.setForeground(QBrush(status_col))
                self.table.setItem(row, ci, item)
        self.table.setRowCount(self.table.rowCount())

    def _on_row(self, row):
        if 0 <= row < len(getattr(self, '_filtered_runs', [])):
            self._cmd_view.setPlainText(self._filtered_runs[row].get('command',''))

    def _clear(self):
        if QMessageBox.question(self, 'Clear history',
            'Delete all run history? This cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            save_runs([])
            self.load()


class SettingsTab(QWidget):
    theme_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self); v.setContentsMargins(20,20,20,20); v.setSpacing(16)
        s = load_settings()

        # ── Appearance ────────────────────────────────────────────────────────
        appear_grp = QGroupBox('Appearance')
        ag = QHBoxLayout(appear_grp); ag.setContentsMargins(12,16,12,12)
        ag.addWidget(QLabel('Theme:'))
        self.theme_combo = QComboBox(); self.theme_combo.addItems(['Dark','Light'])
        saved_theme = s.get('theme', 'dark').capitalize()
        self.theme_combo.setCurrentText(saved_theme); self.theme_combo.setFixedWidth(120)
        self.theme_combo.currentTextChanged.connect(
            lambda t: self.theme_changed.emit(t.lower()))
        ag.addWidget(self.theme_combo); ag.addStretch()
        v.addWidget(appear_grp)

        # ── Paths ─────────────────────────────────────────────────────────────
        paths_grp = QGroupBox('Paths')
        pg = QGridLayout(paths_grp); pg.setContentsMargins(12,16,12,12); pg.setSpacing(8)
        pg.setColumnStretch(1,1)
        self.wd_edit  = QLineEdit(s.get('working_directory',''))
        self.psn_edit = QLineEdit(s.get('psn_path','')); self.psn_edit.setPlaceholderText('Leave blank — auto-detect from PATH')
        self.nm_edit  = QLineEdit(s.get('nonmem_path','')); self.nm_edit.setPlaceholderText('Leave blank — auto-detect from PATH')
        self.rs_edit  = QLineEdit(s.get('rstudio_path','')); self.rs_edit.setPlaceholderText('Leave blank — auto-detect (RStudio on PATH or default install)')
        wd_btn = QPushButton('Browse…'); wd_btn.setFixedWidth(90)
        wd_btn.clicked.connect(self._browse_wd)
        rs_btn = QPushButton('Browse…'); rs_btn.setFixedWidth(90)
        rs_btn.clicked.connect(self._browse_rs)
        pg.addWidget(QLabel('Default directory:'), 0, 0); pg.addWidget(self.wd_edit, 0, 1); pg.addWidget(wd_btn, 0, 2)
        pg.addWidget(QLabel('PsN bin path:'),      1, 0); pg.addWidget(self.psn_edit, 1, 1, 1, 2)
        pg.addWidget(QLabel('NONMEM bin path:'),   2, 0); pg.addWidget(self.nm_edit,  2, 1, 1, 2)
        pg.addWidget(QLabel('RStudio path:'),      3, 0); pg.addWidget(self.rs_edit,  3, 1); pg.addWidget(rs_btn, 3, 2)
        v.addWidget(paths_grp)

        # ── Bookmarks ─────────────────────────────────────────────────────────
        bm_grp = QGroupBox('Bookmarks')
        bv = QVBoxLayout(bm_grp); bv.setContentsMargins(12,16,12,12); bv.setSpacing(8)
        self.bm_list = QListWidget(); self.bm_list.setMaximumHeight(180)
        for b in load_bookmarks():
            self.bm_list.addItem(f"{b.get('name','')}  —  {b.get('path','')}")
        rem_btn = QPushButton('Remove selected bookmark')
        rem_btn.setObjectName('danger'); rem_btn.setFixedWidth(200)
        rem_btn.clicked.connect(self._remove_bm)
        bv.addWidget(self.bm_list)
        rem_row = QHBoxLayout(); rem_row.addWidget(rem_btn); rem_row.addStretch()
        bv.addLayout(rem_row)
        v.addWidget(bm_grp)

        # ── Save ─────────────────────────────────────────────────────────────
        save_row = QHBoxLayout()
        save_btn = QPushButton('Save settings'); save_btn.setObjectName('primary')
        save_btn.setFixedWidth(140); save_btn.clicked.connect(self._save)
        save_row.addWidget(save_btn); save_row.addStretch()
        v.addLayout(save_row)
        v.addStretch()

    def _browse_wd(self):
        d = QFileDialog.getExistingDirectory(self,'Select directory',self.wd_edit.text())
        if d: self.wd_edit.setText(d)

    def _browse_rs(self):
        if IS_WIN:
            f,_ = QFileDialog.getOpenFileName(self,'Select RStudio executable',
                r'C:\Program Files\Posit\RStudio','Executables (*.exe)')
        elif IS_MAC:
            f,_ = QFileDialog.getOpenFileName(self,'Select RStudio.app',
                '/Applications','Applications (*.app);;All files (*)')
        else:
            f,_ = QFileDialog.getOpenFileName(self,'Select RStudio executable',
                '/usr/bin','All files (*)')
        if f: self.rs_edit.setText(f)

    def _save(self):
        s = load_settings()
        s['working_directory'] = self.wd_edit.text().strip()
        s['psn_path']          = self.psn_edit.text().strip()
        s['nonmem_path']       = self.nm_edit.text().strip()
        s['rstudio_path']      = self.rs_edit.text().strip()
        s['theme']             = self.theme_combo.currentText().lower()
        save_settings(s); QMessageBox.information(self,'Saved','Settings saved.')

    def _remove_bm(self):
        row = self.bm_list.currentRow()
        if row < 0: return
        bms = load_bookmarks()
        if row < len(bms): bms.pop(row)
        save_bookmarks(bms); self.bm_list.takeItem(row)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('About NMGUI')
        self.setFixedWidth(480)
        self.setModal(True)
        v = QVBoxLayout(self); v.setSpacing(0); v.setContentsMargins(0,0,0,0)

        # Coloured header band
        header = QWidget()
        header.setStyleSheet(f'background:{C_BLUE};')
        header.setFixedHeight(80)
        hl = QHBoxLayout(header); hl.setContentsMargins(24,0,24,0); hl.setSpacing(16)
        logo_lbl = QLabel(); logo_lbl.setPixmap(_make_logo_pixmap(48)); logo_lbl.setFixedSize(48,48)
        title_col = QVBoxLayout(); title_col.setSpacing(2)
        title_lbl = QLabel('NMGUI')
        title_lbl.setStyleSheet('font-size:24px;font-weight:800;color:#ffffff;background:transparent;')
        sub_lbl   = QLabel(f'v{APP_VERSION}  ·  NONMEM Run Manager')
        sub_lbl.setStyleSheet('font-size:11px;color:rgba(255,255,255,180);background:transparent;')
        title_col.addWidget(title_lbl); title_col.addWidget(sub_lbl)
        hl.addWidget(logo_lbl); hl.addLayout(title_col); hl.addStretch()
        v.addWidget(header)

        # Body
        body = QWidget(); bv = QVBoxLayout(body)
        bv.setContentsMargins(24,20,24,20); bv.setSpacing(14)

        # Purpose
        purpose = QLabel(
            'A standalone desktop application for pharmacometric modelling workflows — '
            'manage NONMEM models, visualise diagnostics, run PsN tools, and compare '
            'model output without leaving one window.')
        purpose.setWordWrap(True)
        purpose.setStyleSheet(f'font-size:12px;color:{C_FG};line-height:1.5;')
        bv.addWidget(purpose)

        from PyQt6.QtWidgets import QFrame
        sep1 = QFrame(); sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet(f'color:{C_BORDER};'); bv.addWidget(sep1)

        # Author
        author = QLabel(
            f'<b>Author</b><br>'
            f'Rob ter Heine — Hospital pharmacist &amp; clinical pharmacologist<br>'
            f'<a href="https://www.radboudumc.nl/en/research/research-groups/'
            f'radboud-applied-pharmacometrics" style="color:#4c8aff;">'
            f'Radboud Applied Pharmacometrics</a>  ·  Radboudumc, Nijmegen')
        author.setOpenExternalLinks(True)
        author.setWordWrap(True)
        author.setStyleSheet(f'font-size:12px;color:{C_FG};')
        bv.addWidget(author)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f'color:{C_BORDER};'); bv.addWidget(sep2)

        # Source & contribute
        source = QLabel(
            f'<b>Source code</b><br>'
            f'<a href="https://github.com/robterheine/NMGUI2" style="color:#4c8aff;">'
            f'github.com/robterheine/NMGUI2</a><br><br>'
            f'<b>Contributions welcome!</b> Open an issue or pull request if you\'d like '
            f'to improve NMGUI — bug reports, feature requests and code contributions '
            f'are all appreciated.')
        source.setOpenExternalLinks(True)
        source.setWordWrap(True)
        source.setStyleSheet(f'font-size:12px;color:{C_FG};')
        bv.addWidget(source)

        sep3 = QFrame(); sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet(f'color:{C_BORDER};'); bv.addWidget(sep3)

        # AI + environment
        pg_ver = pg.__version__ if HAS_PG else 'not installed'
        np_ver = 'installed' if HAS_NP else 'not installed'
        env = QLabel(
            f'<b>Developed with</b>  Claude Sonnet 4.6 by Anthropic<br><br>'
            f'<b>Environment</b><br>'
            f'Python {sys.version.split()[0]}  ·  '
            f'PyQt6 {_pyqt6_version()}  ·  '
            f'pyqtgraph {pg_ver}  ·  numpy {np_ver}')
        env.setWordWrap(True)
        env.setStyleSheet(f'font-size:11px;color:{C_FG2};')
        bv.addWidget(env)

        v.addWidget(body)

        # Footer buttons
        foot = QWidget(); foot.setStyleSheet(f'background:{C_BG3};border-top:1px solid {C_BORDER};')
        fl = QHBoxLayout(foot); fl.setContentsMargins(16,10,16,10)
        gh_btn = QPushButton('Open GitHub')
        gh_btn.clicked.connect(lambda: __import__('webbrowser').open('https://github.com/robterheine/NMGUI2'))
        close = QPushButton('Close'); close.setObjectName('primary')
        close.clicked.connect(self.accept)
        fl.addWidget(gh_btn); fl.addStretch(); fl.addWidget(close)
        v.addWidget(foot)

def _pyqt6_version():
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR
        return PYQT_VERSION_STR
    except Exception:
        return 'unknown'


# ══════════════════════════════════════════════════════════════════════════════
# Main Window
# ══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'NMGUI')
        self._current_theme = 'dark'
        self._selected_model = None
        self._build_menu()
        self._build_ui()
        self._restore_geometry()
        self._check_deps()
        QTimer.singleShot(3000, self._version_check)

    def _restore_geometry(self):
        s = load_settings()
        geom = s.get('window_geometry')
        if geom:
            try:
                from PyQt6.QtCore import QByteArray
                self.restoreGeometry(QByteArray.fromHex(bytes(geom, 'ascii')))
                return
            except Exception:
                pass
        self.resize(1300, 840)
        # Restore splitter
        spl_sizes = s.get('splitter_sizes')
        if spl_sizes and hasattr(self, 'models_tab'):
            try:
                spl = self.models_tab.findChild(QSplitter)
                if spl: spl.setSizes(spl_sizes)
            except Exception:
                pass

    def closeEvent(self, event):
        s = load_settings()
        s['window_geometry'] = bytes(self.saveGeometry().toHex()).decode('ascii')
        # Save model list splitter
        try:
            spl = self.models_tab.findChild(QSplitter)
            if spl: s['splitter_sizes'] = spl.sizes()
        except Exception:
            pass
        save_settings(s)
        super().closeEvent(event)

    # ── Menu bar ──────────────────────────────────────────────────────────────

    def _build_menu(self):
        mb = self.menuBar()
        file_menu = mb.addMenu('File')
        open_act = QAction('Open Directory…', self); open_act.setShortcut(QKeySequence('Ctrl+O'))
        open_act.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        open_act.triggered.connect(self._open_directory)
        rescan_act = QAction('Rescan', self); rescan_act.setShortcut(QKeySequence('Ctrl+R'))
        rescan_act.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        rescan_act.triggered.connect(self._rescan)
        quit_act = QAction('Quit', self); quit_act.setShortcut(QKeySequence('Ctrl+Q'))
        quit_act.triggered.connect(QApplication.instance().quit)
        file_menu.addAction(open_act); file_menu.addAction(rescan_act)
        file_menu.addSeparator(); file_menu.addAction(quit_act)
        help_menu = mb.addMenu('Help')
        about_act = QAction('About NMGUI…', self); about_act.triggered.connect(self._show_about)
        github_act = QAction('GitHub Repository…', self)
        github_act.triggered.connect(
            lambda: __import__('webbrowser').open('https://github.com/robterheine/NMGUI2'))
        help_menu.addAction(about_act); help_menu.addSeparator(); help_menu.addAction(github_act)
        # Keyboard shortcuts for sidebar navigation
        # ApplicationShortcut fires regardless of which child widget has focus
        for i in range(7):
            act = QAction(self)
            act.setShortcut(QKeySequence(f'Ctrl+{i+1}'))
            act.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            act.triggered.connect(lambda _, n=i: self._nav_to(n))
            self.addAction(act)

    def _open_directory(self): self._nav_to(0); self.models_tab._browse()
    def _rescan(self):         self._nav_to(0); self.models_tab._scan()
    def _show_about(self):     AboutDialog(self).exec()

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # ── Header bar ────────────────────────────────────────────────────────
        header = QWidget(); header.setObjectName('appHeader'); header.setFixedHeight(48)
        hl = QHBoxLayout(header); hl.setContentsMargins(16,0,16,0); hl.setSpacing(10)
        logo_lbl = QLabel(); logo_lbl.setPixmap(_make_logo_pixmap(28)); logo_lbl.setFixedSize(28,28)
        name_lbl = QLabel('NMGUI')
        name_lbl.setStyleSheet('font-size:16px;font-weight:700;letter-spacing:-.5px;background:transparent;')
        ver_lbl = QLabel(f'v{APP_VERSION}')
        ver_lbl.setStyleSheet(f'font-size:11px;color:{C_FG2};margin-top:3px;background:transparent;')
        self._ctx_lbl = QLabel('')
        self._ctx_lbl.setStyleSheet(f'font-size:12px;color:{C_FG2};background:transparent;')
        # RStudio button — global, always visible
        self._rs_btn = QPushButton('Open RStudio')
        self._rs_btn.setToolTip('Open RStudio with the current model directory as project')
        self._rs_btn.setFixedHeight(28); self._rs_btn.setEnabled(False)
        self._rs_btn.clicked.connect(self._launch_rstudio_global)
        hl.addWidget(logo_lbl); hl.addWidget(name_lbl); hl.addWidget(ver_lbl)
        hl.addSpacing(16); hl.addWidget(self._ctx_lbl, 1)
        about_btn = QPushButton('? About')
        about_btn.setFixedHeight(28)
        about_btn.setToolTip('About NMGUI')
        about_btn.clicked.connect(self._show_about)
        hl.addWidget(about_btn)
        hl.addWidget(self._rs_btn)
        root.addWidget(header)

        sep = QWidget(); sep.setFixedHeight(1); sep.setStyleSheet(f'background:{C_BORDER};')
        root.addWidget(sep)

        # ── Body: sidebar + stacked pages ─────────────────────────────────────
        body = QHBoxLayout(); body.setContentsMargins(0,0,0,0); body.setSpacing(0)

        # Sidebar
        self._sidebar = QWidget(); self._sidebar.setFixedWidth(82)
        self._sidebar.setObjectName('sidebar')
        sv = QVBoxLayout(self._sidebar); sv.setContentsMargins(0,8,0,8); sv.setSpacing(2)

        self._nav_items = []
        self._nav_icon_lbls = []   # kept for theme-colour refresh
        nav_defs = [
            ('Models',      'models',      'Ctrl+1'),
            ('Tree',        'tree',        'Ctrl+2'),
            ('Evaluation',  'evaluation',  'Ctrl+3'),
            ('VPC',         'vpc',         'Ctrl+4'),
            ('Uncertainty', 'uncertainty', 'Ctrl+5'),
            ('History',     'history',     'Ctrl+6'),
            ('Settings',    'settings',    'Ctrl+7'),
        ]
        for i, (label, icon_name, shortcut) in enumerate(nav_defs):
            btn = QPushButton()
            btn.setObjectName('navBtn')
            btn.setCheckable(True)
            btn.setFixedHeight(68); btn.setFixedWidth(82)
            btn.setToolTip(f'{label}  ({shortcut})')
            bv = QVBoxLayout(btn); bv.setContentsMargins(4, 8, 4, 6); bv.setSpacing(3)

            # QPainter icon — drawn at 28px, coloured to theme fg
            icon_lbl = QLabel(); icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setFixedHeight(28)
            icon_lbl.setPixmap(_make_nav_icon(icon_name, 28, C_FG))
            icon_lbl.setStyleSheet('background:transparent;')

            # Text label
            text_lbl = QLabel(label); text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text_lbl.setStyleSheet('background:transparent;')
            pal = text_lbl.palette()
            pal.setColor(pal.ColorRole.WindowText, QColor(C_FG))
            text_lbl.setPalette(pal)
            f = text_lbl.font(); f.setPointSize(8); text_lbl.setFont(f)

            bv.addWidget(icon_lbl); bv.addWidget(text_lbl)
            btn.clicked.connect(lambda _, n=i: self._nav_to(n))
            sv.addWidget(btn)
            self._nav_items.append(btn)
            # Store (icon_lbl, icon_name, text_lbl) for theme refresh
            self._nav_icon_lbls.append((icon_lbl, icon_name, text_lbl))

        sv.addStretch()
        body.addWidget(self._sidebar)

        # Sidebar separator
        ssep = QWidget(); ssep.setFixedWidth(1); ssep.setStyleSheet(f'background:{C_BORDER};')
        body.addWidget(ssep)

        # Stacked pages
        self._stack = QStackedWidget()
        self.models_tab      = ModelsTab()
        self.tree_tab        = AncestryTreeWidget()
        self.eval_tab        = EvaluationTab()
        self.vpc_tab         = VPCTab()
        self.uncertainty_tab = ParameterUncertaintyTab()
        self.history_tab     = RunHistoryTab()
        self.settings_tab    = SettingsTab()
        self._stack.addWidget(self.models_tab)       # 0
        self._stack.addWidget(self.tree_tab)         # 1
        self._stack.addWidget(self.eval_tab)         # 2
        self._stack.addWidget(self.vpc_tab)          # 3
        self._stack.addWidget(self.uncertainty_tab)  # 4
        self._stack.addWidget(self.history_tab)      # 5
        self._stack.addWidget(self.settings_tab)     # 6
        body.addWidget(self._stack, 1)

        body_w = QWidget(); body_w.setLayout(body)
        root.addWidget(body_w, 1)

        # Signals
        self.models_tab.status_msg.connect(self.statusBar().showMessage)
        self.eval_tab.status_msg.connect(self.statusBar().showMessage)
        self.vpc_tab.status_msg.connect(self.statusBar().showMessage)
        self.uncertainty_tab.status_msg.connect(self.statusBar().showMessage)
        self.models_tab.model_selected.connect(self._on_model_selected)
        self.models_tab.model_selected.connect(self._on_model_selected_for_tree)
        self.tree_tab.model_clicked.connect(self._tree_model_clicked)
        self.settings_tab.theme_changed.connect(self._apply_theme)

        self.setCentralWidget(central)
        self.statusBar().showMessage('Ready')
        self._nav_to(0)  # start on Models

    def _nav_to(self, index):
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_items):
            btn.setChecked(i == index)
        if self._selected_model:
            if index == 2 and self.eval_tab._model is not self._selected_model:
                self.eval_tab.load_model(self._selected_model)
            elif index == 3 and self.vpc_tab._model is not self._selected_model:
                self.vpc_tab.load_model(self._selected_model)
            elif index == 4 and self.uncertainty_tab._model is not self._selected_model:
                self.uncertainty_tab.load_model(self._selected_model)
        if index == 1:
            self._refresh_tree()
        elif index == 5:
            self.history_tab.load()

    def _refresh_tree(self):
        models = self.models_tab._all_models
        stem   = self._selected_model.get('stem') if self._selected_model else None
        self.tree_tab.load(models, current_stem=stem)

    def _tree_model_clicked(self, stem):
        """When a tree node is clicked, select that model and switch to Models tab."""
        for m in self.models_tab._all_models:
            if m['stem'] == stem:
                self._on_model_selected(m)
                for row in range(self.models_tab.table.rowCount()):
                    item = self.models_tab.table.item(row, 1)
                    if item and item.text() == stem:
                        self.models_tab.table.setCurrentCell(row, 1)
                        break
                self._nav_to(0)  # switch to Models so selection is visible
                break

    def _on_model_selected_for_tree(self, model):
        self.tree_tab.set_current(model.get('stem'))

    def _on_model_selected(self, model):
        self._selected_model = model
        stem = model.get('stem',''); directory = Path(model.get('path','')).parent.name
        self._ctx_lbl.setText(f'{directory}  /  {stem}')
        self._rs_btn.setEnabled(True)
        self.eval_tab.load_model(model)
        self.vpc_tab.load_model(model)

    def _launch_rstudio_global(self):
        directory = self.models_tab.current_directory()
        rs_path = load_settings().get('rstudio_path','')
        err = launch_rstudio(directory, rs_path)
        if err: QMessageBox.warning(self,'RStudio',err)
        else: self.statusBar().showMessage(f'RStudio opened — {Path(directory).name}')

    def _apply_theme(self, theme_name):
        global _active_theme
        _active_theme = theme_name
        _set_theme_aliases()
        t = THEMES[theme_name]
        if HAS_PG:
            pg.setConfigOptions(background=t['pg_bg'], foreground=t['pg_fg'])
        QApplication.instance().setStyleSheet(build_stylesheet(theme_name))
        bg = t['pg_bg']; fg = t['pg_fg']
        for w in (self.eval_tab.gof, self.eval_tab.indfit,
                  self.eval_tab.waterfall, self.eval_tab.conv,
                  self.eval_tab.cwres_hist, self.eval_tab.qq_plot,
                  self.eval_tab.eta_cov, self.eval_tab.data_explorer,
                  self.tree_tab):
            if hasattr(w, 'set_theme'):
                w.set_theme(bg, fg)
        # Tree nodes use theme colours — rebuild if models are loaded
        if self.tree_tab._models:
            self.tree_tab._rebuild()
        self._ctx_lbl.setStyleSheet(f'font-size:12px;color:{C_FG2};background:transparent;')
        # Redraw sidebar icons and update text label colours for new theme
        for icon_lbl, icon_name, text_lbl in self._nav_icon_lbls:
            icon_lbl.setPixmap(_make_nav_icon(icon_name, 28, C_FG))
            pal = text_lbl.palette()
            pal.setColor(pal.ColorRole.WindowText, QColor(C_FG))
            text_lbl.setPalette(pal)
        self.statusBar().showMessage(f'Theme: {theme_name.capitalize()}')

    def _check_deps(self):
        missing = []
        if not HAS_NP: missing.append('numpy')
        if not HAS_PG: missing.append('pyqtgraph')
        if missing:
            self.statusBar().showMessage(
                f'Missing dependencies: pip3 install {" ".join(missing)}')

    def _version_check(self):
        def _fetch():
            try:
                import urllib.request, json as _j
                url = 'https://api.github.com/repos/robterheine/NMGUI2/releases/latest'
                with urllib.request.urlopen(url, timeout=5) as r:
                    tag = _j.loads(r.read()).get('tag_name','').lstrip('v')
                if tag and tag > APP_VERSION:
                    self.statusBar().showMessage(
                        f'Update available: v{tag}  —  github.com/robterheine/NMGUI2/releases')
            except Exception:
                pass
        threading.Thread(target=_fetch, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setApplicationName('NMGUI')
    app.setApplicationVersion(APP_VERSION)
    if IS_MAC:   app.setStyle('macos')
    elif IS_WIN: app.setStyle('windowsvista')
    else:        app.setStyle('Fusion')
    # Apply saved theme (default dark)
    saved_theme = load_settings().get('theme', 'dark')
    global _active_theme
    _active_theme = saved_theme
    _set_theme_aliases()
    if HAS_PG:
        t = THEMES[saved_theme]
        pg.setConfigOptions(background=t['pg_bg'], foreground=t['pg_fg'])
    app.setStyleSheet(build_stylesheet(saved_theme))
    if not HAS_PARSER:
        msg = QMessageBox(QMessageBox.Icon.Critical, 'Setup required', '')
        msg.setText('<b>parser.py not found</b>')
        msg.setInformativeText(
            'nmgui2.py must be placed in the same folder as parser.py.<br><br>'
            '<b>Steps to fix:</b><br>'
            '1. Clone or download the NMGUI repository from GitHub<br>'
            '2. Make sure nmgui2.py and parser.py are in the same directory<br>'
            '3. Run: <tt>python3 nmgui2.py</tt> from that directory<br><br>'
            f'<small>Technical detail: {_PARSER_ERR}</small>'
        )
        msg.setTextFormat(Qt.TextFormat.RichText)
        github_btn = msg.addButton('Open GitHub', QMessageBox.ButtonRole.HelpRole)
        msg.addButton('Quit', QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is github_btn:
            import webbrowser
            webbrowser.open('https://github.com/robterheine/NMGUI2')
        sys.exit(1)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
