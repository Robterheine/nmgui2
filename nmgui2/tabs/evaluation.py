from pathlib import Path

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QStackedWidget, QFileDialog, QLineEdit, QCheckBox)
from PyQt6.QtCore import Qt, pyqtSignal, QThread

from ..app.theme import C, T
from ..app.constants import IS_WIN, IS_MAC
from ..widgets.plots.gof import GOFWidget
from ..widgets.plots.indfit import IndFitWidget
from ..widgets.plots.waterfall import WaterfallWidget
from ..widgets.plots.convergence import ConvergenceWidget
from ..widgets.plots.cwres_hist import CWRESHistWidget
from ..widgets.plots.qq import QQPlotWidget
from ..widgets.plots.eta_cov import ETACovWidget
from ..widgets.plots.npde_dist import NPDEDistWidget

import logging
_log = logging.getLogger(__name__)

try:
    from ..parser import read_table_file, parse_phi_file, parse_ext_file
    HAS_PARSER = True
except Exception:
    HAS_PARSER = False

HOME = Path.home()
_MAX_ROWS = 15_000


class _TableLoadWorker(QThread):
    """Load a NONMEM table file in the background so the UI stays responsive."""
    finished = pyqtSignal(list, list)   # header, rows
    error    = pyqtSignal(str)

    def __init__(self, path: str):
        super().__init__()
        self._path = path

    def run(self):
        try:
            h, r = read_table_file(self._path, max_rows=_MAX_ROWS)
            if h is None:
                self.error.emit('Could not parse file')
            else:
                self.finished.emit(h, r)
        except Exception as e:
            self.error.emit(str(e))


class EvaluationTab(QWidget):
    status_msg = pyqtSignal(str)

    # Section indices
    SEC_GOF   = 0
    SEC_INDF  = 1
    SEC_WFALL = 2
    SEC_CONV  = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._header = None; self._rows = None; self._model = None
        self._load_worker: _TableLoadWorker | None = None
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)

        # ── Context + file bar ────────────────────────────────────────────────
        top_bar = QWidget(); top_bar.setObjectName('evalTopBar')
        tbl = QVBoxLayout(top_bar); tbl.setContentsMargins(8, 6, 8, 6); tbl.setSpacing(4)

        ctx_row = QHBoxLayout()
        self._model_lbl = QLabel('No model selected')
        self._model_lbl.setObjectName('mutedBold')
        self._table_lbl = QLabel('')
        self._table_lbl.setObjectName('muted')
        ctx_row.addWidget(self._model_lbl); ctx_row.addSpacing(12)
        ctx_row.addWidget(self._table_lbl); ctx_row.addStretch()
        tbl.addLayout(ctx_row)

        file_row = QHBoxLayout(); file_row.setSpacing(6)
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText('sdtab / output table file…')
        br = QPushButton('Browse…'); br.clicked.connect(self._browse)
        self._load_btn = QPushButton('Load')
        self._load_btn.setObjectName('primary')
        self._load_btn.clicked.connect(self._load)
        ld = self._load_btn
        self.mdv_cb = QCheckBox('Exclude MDV=1'); self.mdv_cb.setChecked(True)
        self.mdv_cb.stateChanged.connect(self._reload)
        file_row.addWidget(self.file_edit, 1)
        file_row.addWidget(br); file_row.addWidget(ld); file_row.addWidget(self.mdv_cb)
        tbl.addLayout(file_row)
        v.addWidget(top_bar)

        # ── Pill navigation strip ─────────────────────────────────────────────
        pill_bar = QWidget(); pill_bar.setObjectName('pillBar'); pill_bar.setFixedHeight(40)
        pl = QHBoxLayout(pill_bar); pl.setContentsMargins(12, 6, 12, 6); pl.setSpacing(4)

        self._pill_btns = []
        pill_labels = ['GOF', 'Individual Fits', 'OFV Waterfall', 'Convergence']
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
        sep.setObjectName('hairlineSep')
        v.addWidget(sep)

        # ── Stacked content ───────────────────────────────────────────────────
        self._stack = QStackedWidget()

        # 0 — GOF panel (GOF 2×2 + CWRES Hist + QQ Plot via inner pill)
        gof_panel = QWidget(); gv = QVBoxLayout(gof_panel); gv.setContentsMargins(0, 0, 0, 0); gv.setSpacing(0)
        # Inner sub-strip for GOF
        inner_bar = QWidget(); inner_bar.setFixedHeight(34)
        il = QHBoxLayout(inner_bar); il.setContentsMargins(8, 4, 8, 4); il.setSpacing(3)
        self._gof_btns = []
        for i, lbl in enumerate(['GOF 2x2', 'CWRES Hist', 'QQ Plot', 'ETA vs Cov', 'NPDE Dist']):
            btn = QPushButton(lbl); btn.setObjectName('innerPillBtn')
            btn.setCheckable(True); btn.setFixedHeight(24)
            btn.clicked.connect(lambda _, n=i: self._switch_gof(n))
            il.addWidget(btn); self._gof_btns.append(btn)
        il.addStretch()
        gv.addWidget(inner_bar)
        self._gof_stack = QStackedWidget()
        self.gof        = GOFWidget()
        self.cwres_hist = CWRESHistWidget()
        self.qq_plot    = QQPlotWidget()
        self.eta_cov    = ETACovWidget()
        self.npde_dist  = NPDEDistWidget()
        self._gof_stack.addWidget(self.gof)
        self._gof_stack.addWidget(self.cwres_hist)
        self._gof_stack.addWidget(self.qq_plot)
        self._gof_stack.addWidget(self.eta_cov)
        self._gof_stack.addWidget(self.npde_dist)
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

        v.addWidget(self._stack, 1)

        # Initialise selection; NPDE button hidden until a file with NPDE is loaded
        self._gof_btns[4].setVisible(False)
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
        f, _ = QFileDialog.getOpenFileName(self, 'Select table file', d, 'All files (*)')
        if f: self.file_edit.setText(f)

    def _load(self):
        path = self.file_edit.text().strip()
        if not path or not Path(path).is_file():
            self.status_msg.emit('File not found'); return
        if not HAS_PARSER:
            self.status_msg.emit('parser.py not available'); return
        # Cancel any in-progress load
        if self._load_worker and self._load_worker.isRunning():
            self._load_worker.finished.disconnect()
            self._load_worker.error.disconnect()
            self._load_worker.quit()
        fname = Path(path).name
        self._load_btn.setEnabled(False)
        self._load_btn.setText('Loading…')
        self.status_msg.emit(f'Parsing {fname}…')
        self._load_worker = _TableLoadWorker(path)
        self._load_worker.finished.connect(self._on_load_done)
        self._load_worker.error.connect(self._on_load_error)
        self._load_worker.start()

    def _on_load_done(self, h, r):
        self._load_btn.setEnabled(True)
        self._load_btn.setText('Load')
        self._header = h; self._rows = r; self._reload()
        fname = Path(self.file_edit.text()).name
        truncated = len(r) >= _MAX_ROWS
        if truncated:
            self._table_lbl.setText(
                f'·  {fname}  (first {len(r):,} rows, {len(h)} cols) [TRUNCATED]')
            self.status_msg.emit(
                f'Showing first {len(r):,} of file — {fname} (file has more rows)')
        else:
            self._table_lbl.setText(f'·  {fname}  ({len(r):,} rows, {len(h)} cols)')
            self.status_msg.emit(f'Loaded {len(r):,} rows, {len(h)} columns — {fname}')

    def _on_load_error(self, msg):
        self._load_btn.setEnabled(True)
        self._load_btn.setText('Load')
        self.status_msg.emit(f'Load error: {msg}')

    def _reload(self):
        if self._header is None: return
        mdv = self.mdv_cb.isChecked()
        self.gof.load(self._header, self._rows, mdv)
        self.indfit.load(self._header, self._rows)
        self.cwres_hist.load(self._header, self._rows, mdv)
        self.qq_plot.load(self._header, self._rows, mdv)
        self.eta_cov.load(self._header, self._rows, mdv)
        self.npde_dist.load(self._header, self._rows, mdv)
        # Show NPDE Dist button only when NPDE column is present
        has_npde = 'NPDE' in [h.upper() for h in self._header]
        self._gof_btns[4].setVisible(has_npde)
        if not has_npde and self._gof_stack.currentIndex() == 4:
            self._switch_gof(0)

    def load_model(self, model):
        self._model = model
        self._model_lbl.setText(f'Model: {model.get("stem", "")}')
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

    def _try_phi(self, model):
        if not HAS_PARSER: return
        stem = model['stem']
        for base in [Path(model['lst_path']).parent, Path(model['path']).parent]:
            for fn in [f'{stem}.phi', f'{stem}/{stem}.phi']:
                p = base / fn
                if p.is_file():
                    try:
                        r = parse_phi_file(str(p))
                        if r.get('obj') is not None: self.waterfall.load(r)
                    except Exception as e: _log.debug(f'Failed to parse phi file {p}: {e}')
                    return

    def _try_ext(self, model):
        if not HAS_PARSER: return
        stem = model['stem']
        for base in [Path(model['lst_path']).parent, Path(model['path']).parent]:
            for fn in [f'{stem}.ext', f'{stem}/{stem}.ext']:
                p = base / fn
                if p.is_file():
                    try:
                        r = parse_ext_file(str(p))
                        if r: self.conv.load(r)
                    except Exception as e: _log.debug(f'Failed to parse ext file {p}: {e}')
                    return
