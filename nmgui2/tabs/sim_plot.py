"""Monte Carlo simulation prediction interval plot tab."""
import re
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QScrollArea,
    QPushButton, QLabel, QLineEdit, QComboBox, QCheckBox,
    QDoubleSpinBox, QFileDialog, QMessageBox, QSizePolicy,
    QSpinBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from ..app.theme import C, T
from ..widgets.collapsible import CollapsibleCard
from ..widgets.plots.sim_canvas import SimCanvas, _SimWorker

import logging
_log = logging.getLogger(__name__)

try:
    import numpy as np
    HAS_NP = True
except ImportError:
    HAS_NP = False

try:
    import pandas as pd
    HAS_PD = True
except ImportError:
    HAS_PD = False

try:
    from ..parser import read_table_file
    HAS_PARSER = True
except Exception:
    HAS_PARSER = False

HOME = Path.home()

_REP_PATTERN = re.compile(
    r'^(REP|IREP|SIM|REPLICATE|SIMNO|SIM_NO|REP_NO|SIM_NUM|NSIM|ISIM)$',
    re.IGNORECASE,
)
_OPS = ['==', '!=', '>', '<', '>=', '<=']

# Default PI band specs: (lo_pct, hi_pct, color, alpha)
_DEFAULT_BANDS = [
    (5,  95,  '#569cd6', 0.25),
    (25, 75,  '#569cd6', 0.40),
]


def _make_color_btn(color: str) -> QPushButton:
    btn = QPushButton()
    btn.setFixedSize(28, 22)
    btn.setToolTip('Click to change colour')
    _set_btn_color(btn, color)
    return btn


def _set_btn_color(btn: QPushButton, color: str):
    btn._color = color
    btn.setStyleSheet(
        f'QPushButton{{background:{color};border:1px solid #555;border-radius:3px;}}'
        f'QPushButton:hover{{border:1px solid #aaa;}}'
    )


class _BandRow(QWidget):
    """One row in the PI bands list."""
    removed = pyqtSignal(object)   # emits self

    def __init__(self, lo=5.0, hi=95.0, color='#569cd6', alpha=0.25, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(4)

        self._vis = QCheckBox(); self._vis.setChecked(True)
        self._vis.setToolTip('Show/hide this band')
        h.addWidget(self._vis)

        h.addWidget(QLabel('Lo%:'))
        self._lo = QDoubleSpinBox()
        self._lo.setRange(0.0, 49.9); self._lo.setDecimals(1); self._lo.setSingleStep(2.5)
        self._lo.setValue(lo); self._lo.setFixedWidth(60)
        h.addWidget(self._lo)

        h.addWidget(QLabel('Hi%:'))
        self._hi = QDoubleSpinBox()
        self._hi.setRange(50.1, 100.0); self._hi.setDecimals(1); self._hi.setSingleStep(2.5)
        self._hi.setValue(hi); self._hi.setFixedWidth(60)
        h.addWidget(self._hi)

        self._color_btn = _make_color_btn(color)
        self._color_btn.clicked.connect(self._pick_color)
        h.addWidget(self._color_btn)

        h.addWidget(QLabel('α:'))
        self._alpha = QDoubleSpinBox()
        self._alpha.setRange(0.05, 1.0); self._alpha.setDecimals(2); self._alpha.setSingleStep(0.05)
        self._alpha.setValue(alpha); self._alpha.setFixedWidth(55)
        h.addWidget(self._alpha)

        rm = QPushButton('×'); rm.setFixedSize(22, 22)
        rm.setToolTip('Remove this band')
        rm.clicked.connect(lambda: self.removed.emit(self))
        h.addWidget(rm)

    def _pick_color(self):
        c = QColor(self._color_btn._color)
        nc = _color_dialog(self, c)
        if nc.isValid():
            _set_btn_color(self._color_btn, nc.name())

    def spec(self) -> dict:
        return {
            'lo_pct':  self._lo.value(),
            'hi_pct':  self._hi.value(),
            'color':   self._color_btn._color,
            'alpha':   self._alpha.value(),
            'visible': self._vis.isChecked(),
        }


def _color_dialog(parent, initial: QColor) -> QColor:
    from PyQt6.QtWidgets import QColorDialog
    return QColorDialog.getColor(initial, parent, 'Choose colour')


class _FilterRow(QWidget):
    """One row in the multi-filter list."""
    removed = pyqtSignal(object)

    def __init__(self, columns=None, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(4)

        self._col = QComboBox(); self._col.setMinimumWidth(90)
        if columns:
            self._col.addItems([''] + columns)
        h.addWidget(self._col)

        self._op = QComboBox()
        self._op.addItems(_OPS); self._op.setFixedWidth(50)
        h.addWidget(self._op)

        self._val = QLineEdit(); self._val.setPlaceholderText('value')
        self._val.setMinimumWidth(70)
        h.addWidget(self._val, 1)

        rm = QPushButton('×'); rm.setFixedSize(22, 22)
        rm.clicked.connect(lambda: self.removed.emit(self))
        h.addWidget(rm)

    def set_columns(self, cols):
        cur = self._col.currentText()
        self._col.blockSignals(True)
        self._col.clear()
        self._col.addItems([''] + cols)
        idx = self._col.findText(cur)
        if idx >= 0: self._col.setCurrentIndex(idx)
        self._col.blockSignals(False)

    def filter_tuple(self):
        return (self._col.currentText(), self._op.currentText(), self._val.text().strip())


class SimulationPlotTab(QWidget):
    status_msg = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model    = None
        self._df       = None       # loaded data as DataFrame
        self._obs_df   = None       # optional observed data
        self._worker   = None
        self._band_rows: list[_BandRow]   = []
        self._filter_rows: list[_FilterRow] = []
        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left controls panel ────────────────────────────────────────────
        left = QWidget(); left.setMinimumWidth(280); left.setMaximumWidth(440)
        lv = QVBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_content = QWidget()
        scl = QVBoxLayout(scroll_content)
        scl.setContentsMargins(6, 6, 6, 6)
        scl.setSpacing(6)
        scroll.setWidget(scroll_content)
        lv.addWidget(scroll, 1)

        # ── Section 1: Data ────────────────────────────────────────────────
        card_data = CollapsibleCard('Data', expanded=True)
        file_row = QHBoxLayout()
        self._file_edit = QLineEdit()
        self._file_edit.setPlaceholderText('NONMEM table or CSV…')
        br = QPushButton('Browse…'); br.setFixedHeight(26)
        br.clicked.connect(self._browse_sim)
        ld = QPushButton('Load'); ld.setObjectName('primary'); ld.setFixedHeight(26)
        ld.clicked.connect(self._load_sim)
        file_row.addWidget(self._file_edit, 1)
        file_row.addWidget(br); file_row.addWidget(ld)
        card_data.add_layout(file_row)
        self._data_lbl = QLabel('No file loaded')
        self._data_lbl.setObjectName('muted')
        self._data_lbl.setWordWrap(True)
        card_data.add_widget(self._data_lbl)
        scl.addWidget(card_data)

        # ── Section 2: Variables ───────────────────────────────────────────
        card_vars = CollapsibleCard('Variables', expanded=True)
        self._rep_cb  = self._labeled_combo(card_vars, 'Replicate col:',
            'Column identifying each simulation replicate (e.g. REP, IREP, SIM)')
        self._x_cb    = self._labeled_combo(card_vars, 'X-axis:',
            'Independent variable (e.g. TIME)')
        self._y_cb    = self._labeled_combo(card_vars, 'Y-axis:',
            'Dependent variable to plot (e.g. IPRED, DV)')
        scl.addWidget(card_vars)

        # ── Section 3: PI Bands ────────────────────────────────────────────
        card_bands = CollapsibleCard('Prediction Interval Bands', expanded=True)
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel('Preset:'))
        self._preset_cb = QComboBox()
        self._preset_cb.addItems(['5/95 + 25/75', '2.5/97.5 + 10/90', '10/90 only', '5/95 only', 'Custom'])
        self._preset_cb.currentIndexChanged.connect(self._apply_preset)
        preset_row.addWidget(self._preset_cb, 1)
        card_bands.add_layout(preset_row)

        self._bands_container = QWidget()
        self._bands_layout = QVBoxLayout(self._bands_container)
        self._bands_layout.setContentsMargins(0, 0, 0, 0)
        self._bands_layout.setSpacing(2)
        card_bands.add_widget(self._bands_container)

        band_btns = QHBoxLayout()
        add_band = QPushButton('+ Add band'); add_band.setFixedHeight(24)
        add_band.clicked.connect(lambda: self._add_band_row())
        band_btns.addWidget(add_band); band_btns.addStretch()
        card_bands.add_layout(band_btns)
        scl.addWidget(card_bands)

        # ── Section 4: Appearance ──────────────────────────────────────────
        card_app = CollapsibleCard('Appearance', expanded=False)

        med_row = QHBoxLayout()
        med_row.addWidget(QLabel('Median colour:'))
        self._med_color_btn = _make_color_btn('#ffffff')
        self._med_color_btn.clicked.connect(self._pick_median_color)
        med_row.addWidget(self._med_color_btn)
        med_row.addWidget(QLabel('Width:'))
        self._med_lw = QDoubleSpinBox()
        self._med_lw.setRange(0.5, 6.0); self._med_lw.setSingleStep(0.5)
        self._med_lw.setValue(2.0); self._med_lw.setFixedWidth(55)
        med_row.addWidget(self._med_lw)
        med_row.addStretch()
        card_app.add_layout(med_row)

        log_row = QHBoxLayout()
        log_row.addWidget(QLabel('Y-axis:'))
        self._log_cb = QCheckBox('Logarithmic')
        log_row.addWidget(self._log_cb)
        log_row.addStretch()
        card_app.add_layout(log_row)

        self._mdv_cb = QCheckBox('Exclude MDV=1 rows'); self._mdv_cb.setChecked(True)
        card_app.add_widget(self._mdv_cb)
        scl.addWidget(card_app)

        # ── Section 5: Filters ─────────────────────────────────────────────
        card_filt = CollapsibleCard('Filters', expanded=False)
        self._filters_container = QWidget()
        self._filters_layout = QVBoxLayout(self._filters_container)
        self._filters_layout.setContentsMargins(0, 0, 0, 0)
        self._filters_layout.setSpacing(2)
        card_filt.add_widget(self._filters_container)
        add_filt = QPushButton('+ Add filter'); add_filt.setFixedHeight(24)
        add_filt.clicked.connect(self._add_filter_row)
        card_filt.add_widget(add_filt)
        scl.addWidget(card_filt)

        # ── Section 6: Observed overlay ────────────────────────────────────
        card_obs = CollapsibleCard('Observed Data Overlay', expanded=False)
        obs_note = QLabel('Optional: overlay observed data from a separate file.')
        obs_note.setObjectName('muted'); obs_note.setWordWrap(True)
        card_obs.add_widget(obs_note)
        obs_file_row = QHBoxLayout()
        self._obs_edit = QLineEdit(); self._obs_edit.setPlaceholderText('Observed file…')
        obs_br = QPushButton('Browse…'); obs_br.setFixedHeight(26)
        obs_br.clicked.connect(self._browse_obs)
        obs_ld = QPushButton('Load'); obs_ld.setObjectName('primary'); obs_ld.setFixedHeight(26)
        obs_ld.clicked.connect(self._load_obs)
        obs_file_row.addWidget(self._obs_edit, 1)
        obs_file_row.addWidget(obs_br); obs_file_row.addWidget(obs_ld)
        card_obs.add_layout(obs_file_row)
        obs_x_row = QHBoxLayout()
        obs_x_row.addWidget(QLabel('X-col:'))
        self._obs_x_cb = QComboBox(); self._obs_x_cb.setMinimumWidth(80)
        obs_x_row.addWidget(self._obs_x_cb)
        obs_x_row.addWidget(QLabel('Y-col:'))
        self._obs_y_cb = QComboBox(); self._obs_y_cb.setMinimumWidth(80)
        obs_x_row.addWidget(self._obs_y_cb)
        obs_x_row.addStretch()
        card_obs.add_layout(obs_x_row)
        self._obs_lbl = QLabel(''); self._obs_lbl.setObjectName('muted')
        card_obs.add_widget(self._obs_lbl)
        scl.addWidget(card_obs)

        scl.addStretch()

        # Plot button below scroll area
        plot_row = QWidget(); plot_row.setFixedHeight(44)
        pr = QHBoxLayout(plot_row); pr.setContentsMargins(6, 6, 6, 6)
        self._plot_btn = QPushButton('Plot'); self._plot_btn.setObjectName('primary')
        self._plot_btn.setFixedHeight(30); self._plot_btn.setEnabled(False)
        self._plot_btn.clicked.connect(self._run_plot)
        pr.addWidget(self._plot_btn)
        lv.addWidget(plot_row)

        # ── Right canvas ───────────────────────────────────────────────────
        self.canvas = SimCanvas()

        self._splitter.addWidget(left)
        self._splitter.addWidget(self.canvas)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([320, 800])

        root.addWidget(self._splitter)

        # Populate default band rows (after containers exist)
        for lo, hi, col, alpha in _DEFAULT_BANDS:
            self._add_band_row(lo, hi, col, alpha)

    def _labeled_combo(self, card: CollapsibleCard, label: str, tooltip: str) -> QComboBox:
        row = QHBoxLayout()
        lbl = QLabel(label); lbl.setToolTip(tooltip)
        cb = QComboBox(); cb.setMinimumWidth(100)
        cb.setToolTip(tooltip)
        row.addWidget(lbl); row.addWidget(cb, 1)
        card.add_layout(row)
        return cb

    # ── Band rows ──────────────────────────────────────────────────────────────

    def _add_band_row(self, lo=5.0, hi=95.0, color='#569cd6', alpha=0.25):
        if len(self._band_rows) >= 4:
            self.status_msg.emit('Maximum 4 PI bands.')
            return
        row = _BandRow(lo, hi, color, alpha)
        row.removed.connect(self._remove_band_row)
        self._band_rows.append(row)
        self._bands_layout.addWidget(row)

    def _remove_band_row(self, row):
        self._band_rows.remove(row)
        self._bands_layout.removeWidget(row)
        row.deleteLater()

    def _apply_preset(self, idx):
        presets = [
            [(5, 95, '#569cd6', 0.25), (25, 75, '#569cd6', 0.40)],
            [(2.5, 97.5, '#4ec994', 0.20), (10, 90, '#4ec994', 0.35)],
            [(10, 90, '#ce9178', 0.30)],
            [(5, 95, '#569cd6', 0.25)],
        ]
        if idx >= len(presets): return   # Custom — do nothing
        for row in list(self._band_rows):
            self._remove_band_row(row)
        for lo, hi, col, alpha in presets[idx]:
            self._add_band_row(lo, hi, col, alpha)

    # ── Filter rows ────────────────────────────────────────────────────────────

    def _add_filter_row(self):
        if len(self._filter_rows) >= 6:
            self.status_msg.emit('Maximum 6 filters.')
            return
        cols = self._current_columns()
        row = _FilterRow(columns=cols)
        row.removed.connect(self._remove_filter_row)
        self._filter_rows.append(row)
        self._filters_layout.addWidget(row)

    def _remove_filter_row(self, row):
        self._filter_rows.remove(row)
        self._filters_layout.removeWidget(row)
        row.deleteLater()

    def _current_columns(self) -> list:
        if self._df is None: return []
        return list(self._df.columns)

    # ── Colour pickers ─────────────────────────────────────────────────────────

    def _pick_median_color(self):
        c = QColor(self._med_color_btn._color)
        nc = _color_dialog(self, c)
        if nc.isValid():
            _set_btn_color(self._med_color_btn, nc.name())

    # ── File loading ───────────────────────────────────────────────────────────

    def _default_dir(self) -> str:
        if self._model:
            return str(Path(self._model.get('path', str(HOME))).parent)
        return str(HOME)

    def _browse_sim(self):
        f, _ = QFileDialog.getOpenFileName(
            self, 'Select simulation table', self._default_dir(), 'All files (*)')
        if f: self._file_edit.setText(f)

    def _browse_obs(self):
        f, _ = QFileDialog.getOpenFileName(
            self, 'Select observed data file', self._default_dir(), 'All files (*)')
        if f: self._obs_edit.setText(f)

    def _load_sim(self):
        path = self._file_edit.text().strip()
        if not path or not Path(path).is_file():
            self.status_msg.emit('File not found.'); return
        if not HAS_PARSER or not HAS_PD:
            self.status_msg.emit('pandas / parser not available.'); return
        try:
            # max_rows=None — simulation files can be very large
            h, r = read_table_file(path, max_rows=None)
            if h is None:
                self.status_msg.emit('Could not parse file.'); return
            self._df = pd.DataFrame(r, columns=[c.upper() for c in h])
            self._populate_columns()
            n, nc = len(self._df), len(self._df.columns)
            self._data_lbl.setText(f'{Path(path).name}  ({n:,} rows, {nc} cols)')
            self.status_msg.emit(f'Loaded {n:,} rows, {nc} columns — {Path(path).name}')
            self._plot_btn.setEnabled(True)
        except Exception as e:
            self.status_msg.emit(f'Load error: {e}')

    def _load_obs(self):
        path = self._obs_edit.text().strip()
        if not path or not Path(path).is_file():
            self.status_msg.emit('Observed file not found.'); return
        if not HAS_PARSER or not HAS_PD:
            self.status_msg.emit('pandas / parser not available.'); return
        try:
            h, r = read_table_file(path, max_rows=None)
            if h is None:
                self.status_msg.emit('Could not parse observed file.'); return
            self._obs_df = pd.DataFrame(r, columns=[c.upper() for c in h])
            cols = list(self._obs_df.columns)
            for cb in (self._obs_x_cb, self._obs_y_cb):
                cb.blockSignals(True); cb.clear(); cb.addItems(cols); cb.blockSignals(False)
            # Try to default obs x/y to match sim x/y
            for cb, sim_cb in ((self._obs_x_cb, self._obs_x_cb),
                                (self._obs_y_cb, self._obs_y_cb)):
                pass  # already matches since we add same column names
            # Best-effort auto-match
            self._try_set(self._obs_x_cb, self._x_cb.currentText())
            self._try_set(self._obs_y_cb, self._y_cb.currentText())
            self._obs_lbl.setText(f'{len(self._obs_df):,} observed rows loaded.')
            self.status_msg.emit(f'Observed data: {len(self._obs_df):,} rows')
        except Exception as e:
            self.status_msg.emit(f'Observed load error: {e}')

    def _try_set(self, cb: QComboBox, text: str):
        idx = cb.findText(text)
        if idx >= 0: cb.setCurrentIndex(idx)

    def _populate_columns(self):
        if self._df is None: return
        cols = list(self._df.columns)

        # Auto-detect replicate column
        rep_guess = ''
        for c in cols:
            if _REP_PATTERN.match(c):
                rep_guess = c; break
        # If no explicit rep col, try ID-cycling detection
        if not rep_guess and 'ID' in cols:
            try:
                ids = self._df['ID'].to_numpy(dtype=float)
                resets = np.where(np.diff(ids) < 0)[0]
                if len(resets) > 0:
                    rep = np.zeros(len(self._df), dtype=int)
                    rep_num = 0
                    prev = 0
                    for rst in resets:
                        rep[prev:rst + 1] = rep_num
                        rep_num += 1
                        prev = rst + 1
                    rep[prev:] = rep_num
                    self._df['_REP_AUTO'] = rep
                    cols = list(self._df.columns)
                    rep_guess = '_REP_AUTO'
            except Exception:
                pass

        for cb in (self._rep_cb, self._x_cb, self._y_cb):
            cur = cb.currentText()
            cb.blockSignals(True); cb.clear(); cb.addItems(cols); cb.blockSignals(False)
            self._try_set(cb, cur)

        # Smart defaults if nothing restored
        if not self._rep_cb.currentText() and rep_guess:
            self._try_set(self._rep_cb, rep_guess)
        if not self._x_cb.currentText():
            self._try_set(self._x_cb, 'TIME')
        if not self._y_cb.currentText():
            for cand in ('IPRED', 'DV', 'PRED'):
                if cand in cols:
                    self._try_set(self._y_cb, cand); break

        # Update filter row column lists
        for fr in self._filter_rows:
            fr.set_columns(cols)

    # ── Plot ───────────────────────────────────────────────────────────────────

    def _run_plot(self):
        if self._df is None: return
        if self._worker and self._worker.isRunning():
            self.status_msg.emit('Computation in progress…'); return

        rep_col = self._rep_cb.currentText()
        x_col   = self._x_cb.currentText()
        y_col   = self._y_cb.currentText()

        if not rep_col or not x_col or not y_col:
            self.status_msg.emit('Select replicate, X, and Y columns.'); return

        specs = [r.spec() for r in self._band_rows if r.spec()['visible']]
        if not specs:
            self.status_msg.emit('No visible PI bands configured.'); return

        band_pcts = [(s['lo_pct'], s['hi_pct']) for s in specs]
        filters   = [fr.filter_tuple() for fr in self._filter_rows]

        self._plot_btn.setEnabled(False)
        self._plot_btn.setText('Computing…')
        self.status_msg.emit('Computing quantiles…')

        self._worker = _SimWorker(
            df         = self._df,
            x_col      = x_col,
            y_col      = y_col,
            rep_col    = rep_col,
            band_pcts  = band_pcts,
            filters    = filters,
            mdv_filter = self._mdv_cb.isChecked(),
        )
        # Attach median colour + linewidth to each spec for the canvas
        med_color = self._med_color_btn._color
        med_lw    = self._med_lw.value()
        for s in specs:
            s['median_color'] = med_color
            s['median_lw']    = med_lw

        self._worker.finished.connect(lambda res: self._on_worker_done(res, specs, x_col, y_col))
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_worker_done(self, result, specs, x_col, y_col):
        self._plot_btn.setEnabled(True)
        self._plot_btn.setText('Plot')

        obs_xy = None
        if self._obs_df is not None:
            ox_col = self._obs_x_cb.currentText()
            oy_col = self._obs_y_cb.currentText()
            if ox_col in self._obs_df.columns and oy_col in self._obs_df.columns:
                try:
                    ox = self._obs_df[ox_col].to_numpy(dtype=float)
                    oy = self._obs_df[oy_col].to_numpy(dtype=float)
                    ok = np.isfinite(ox) & np.isfinite(oy)
                    obs_xy = (ox[ok], oy[ok])
                except Exception:
                    pass

        self.canvas.plot_result(
            result    = result,
            band_specs= specs,
            x_label   = x_col,
            y_label   = y_col,
            log_y     = self._log_cb.isChecked(),
            obs_xy    = obs_xy,
        )
        n_reps = len(result['times'])
        self.status_msg.emit(
            f'Plot ready — {n_reps} unique {x_col} values, '
            f'{len([s for s in specs if s["visible"]])} band(s)')

    def _on_worker_error(self, msg):
        self._plot_btn.setEnabled(True)
        self._plot_btn.setText('Plot')
        self.status_msg.emit(f'Plot error: {msg}')
        QMessageBox.warning(self, 'Simulation Plot', f'Could not compute plot:\n\n{msg}')

    # ── Model context ──────────────────────────────────────────────────────────

    def load_model(self, model):
        self._model = model
        # Don't auto-load — simulation files are not in the model folder by convention.
        # Just set browse directory context so the dialog opens in the right place.

    def set_theme(self, bg, fg):
        if hasattr(self, 'canvas'):
            self.canvas.set_theme(bg, fg)
