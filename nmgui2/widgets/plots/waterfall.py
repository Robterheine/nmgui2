import os, subprocess, sys
import numpy as np
from pathlib import Path

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                              QFileDialog, QMessageBox, QLabel, QButtonGroup)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

try:
    import pyqtgraph as pg
    HAS_PG = True
except ImportError:
    HAS_PG = False

try:
    from scipy.stats import chi2 as _chi2
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

from ...app.theme import C, T
from ...widgets._icons import _placeholder

_CHI2_ALPHA   = 0.001   # p < 0.001 per-subject outlier threshold
_SPARSE_NOBS  = 5       # n_obs below which chi-squared approximation is unreliable


# ── Background worker ─────────────────────────────────────────────────────────

class _NormLoadWorker(QThread):
    """Count informative observations per subject ID from a NONMEM dataset file.

    Excludes EVID≠0 (dose/reset records) and MDV=1 (missing DV) rows.
    BLQ rows handled by M3/M4 are kept (they contribute to the likelihood).
    """
    finished = pyqtSignal(dict)   # {float(subject_id): int(obs_count)}
    failed   = pyqtSignal(str)

    def __init__(self, dataset_path: str):
        super().__init__()
        self._path = dataset_path

    def run(self):
        try:
            from ...parser import read_table_file
            cols, rows = read_table_file(self._path, max_rows=200_000)
            if cols is None or rows is None:
                self.failed.emit('Could not read dataset file')
                return

            cu = [c.upper() for c in cols]
            id_idx   = next((i for i, c in enumerate(cu) if c == 'ID'),   None)
            evid_idx = next((i for i, c in enumerate(cu) if c == 'EVID'), None)
            mdv_idx  = next((i for i, c in enumerate(cu) if c == 'MDV'),  None)

            if id_idx is None:
                self.failed.emit(f'No ID column found in dataset (columns: {", ".join(cols[:10])})')
                return

            counts: dict[float, int] = {}
            for row in rows:
                try:
                    raw_id = row[id_idx]
                    if raw_id is None:
                        continue
                    sid = float(raw_id)
                    if evid_idx is not None:
                        try:
                            if float(row[evid_idx]) != 0:
                                continue
                        except (TypeError, ValueError):
                            pass
                    if mdv_idx is not None:
                        try:
                            if float(row[mdv_idx]) == 1:
                                continue
                        except (TypeError, ValueError):
                            pass
                    counts[sid] = counts.get(sid, 0) + 1
                except Exception:
                    continue

            if not counts:
                self.failed.emit('No observations found after filtering EVID/MDV rows')
                return
            self.finished.emit(counts)
        except Exception as e:
            self.failed.emit(str(e))


# ── Widget ────────────────────────────────────────────────────────────────────

class WaterfallWidget(QWidget):
    """Waterfall plot of individual OFV contributions.

    Supports two display modes:
      Absolute   — raw iOFV per subject; outlier threshold χ²(n_obs_i, α=0.001)
                   drawn as a step function over each bar.
      Normalised — iOFV / n_obs per subject; threshold χ²(n_obs_i, α=0.001) / n_obs_i
                   drawn as a smooth decreasing curve.

    Normalisation corrects for unequal sampling richness: subjects with more
    observations produce larger-magnitude iOFV values even when the model fits
    them well. The normalised view makes subjects directly comparable.

    Call set_dataset_path() when a new model is loaded so the worker can count
    observations per subject from the raw dataset file.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        if not HAS_PG:
            v.addWidget(_placeholder('Install pyqtgraph and numpy'))
            return

        # Internal state
        self._ids_sorted: list      = []
        self._obj_sorted: np.ndarray = np.array([])
        self._n_obs:       dict      = {}          # {float(id): int(n_obs)}
        self._thr_arr:     np.ndarray | None = None
        self._norm_available: bool | None = None   # None=untried
        self._dataset_path:   str  | None = None
        self._norm_worker: _NormLoadWorker | None = None

        # ── Toolbar ───────────────────────────────────────────────────────────
        tb  = QWidget(); tb.setFixedHeight(34)
        tbl = QHBoxLayout(tb)
        tbl.setContentsMargins(8, 4, 8, 4)
        tbl.setSpacing(0)

        self._abs_btn  = QPushButton('Absolute')
        self._norm_btn = QPushButton('Normalised')
        self._abs_btn.setObjectName('segLeft')
        self._norm_btn.setObjectName('segRight')
        for btn in (self._abs_btn, self._norm_btn):
            btn.setFixedHeight(26)
            btn.setCheckable(True)

        self._abs_btn.setToolTip(
            '<b>Absolute iOFV</b><br>'
            'Raw individual OFV contribution per subject.<br>'
            'Subjects with more observations will have larger-magnitude iOFV<br>'
            'even when the model fits them well.<br><br>'
            'Threshold: χ²(df=n_obs, α=0.001) — step function over each bar.')
        self._norm_btn.setToolTip(
            '<b>Normalised iOFV / n_obs</b><br>'
            'iOFV divided by the number of informative observations per subject.<br>'
            'Corrects for sampling richness so sparse and rich subjects are comparable.<br><br>'
            'Threshold: χ²(df=n_obs, α=0.001) / n_obs — decreasing curve because<br>'
            'sparse subjects have more variable per-observation OFV under correct fit.<br><br>'
            'Requires the dataset file to count observations. Excludes EVID≠0 and MDV=1 rows.')

        self._mode_grp = QButtonGroup(self)
        self._mode_grp.setExclusive(True)
        self._mode_grp.addButton(self._abs_btn,  0)
        self._mode_grp.addButton(self._norm_btn, 1)
        self._abs_btn.setChecked(True)
        self._mode_grp.idToggled.connect(self._on_mode_toggled)

        tbl.addWidget(self._abs_btn)
        tbl.addWidget(self._norm_btn)
        tbl.addSpacing(10)

        self._status_lbl = QLabel()
        self._status_lbl.setFixedHeight(26)
        self._status_lbl.setStyleSheet(f'color: {C.fg2}; font-size: 11px;')
        self._status_lbl.hide()
        tbl.addWidget(self._status_lbl)

        tbl.addStretch()

        self._exp_btn = QPushButton('Save PNG…')
        self._exp_btn.setFixedHeight(26)
        self._exp_btn.setEnabled(False)
        self._exp_btn.clicked.connect(self._export)
        tbl.addWidget(self._exp_btn)
        v.addWidget(tb)

        # ── Info bar: explains why the option exists ───────────────────────────
        info_bar = QWidget()
        info_bar.setFixedHeight(22)
        info_bar.setStyleSheet(f'background: {T("bg2")};')
        il = QHBoxLayout(info_bar)
        il.setContentsMargins(10, 0, 10, 0)
        il.setSpacing(0)
        info_lbl = QLabel(
            'iOFV scales with the number of observations per subject  ·  '
            '<b>Absolute</b>: raw iOFV with subject-specific χ² threshold  ·  '
            '<b>Normalised</b>: iOFV / n_obs corrects for unequal sampling richness')
        info_lbl.setStyleSheet(
            f'color: {C.fg2}; font-size: 10px; font-style: italic; background: transparent;')
        il.addWidget(info_lbl)
        v.addWidget(info_bar)

        sep = QWidget(); sep.setFixedHeight(1); sep.setObjectName('hairlineSep')
        v.addWidget(sep)

        # ── Plot ──────────────────────────────────────────────────────────────
        self.pw = pg.PlotWidget()
        self.pw.setLabel('left',   'iOFV')
        self.pw.setLabel('bottom', 'Subject rank (low → high)')
        self.pw.showGrid(x=True, y=True, alpha=0.2)
        self.pw.getAxis('bottom').enableAutoSIPrefix(False)
        self.pw.getAxis('left').enableAutoSIPrefix(False)

        self._hover_lbl = pg.TextItem(
            '', anchor=(0.5, 1.3),
            color='#ffffff',
            fill=pg.mkBrush(30, 30, 40, 220),
            border=pg.mkPen('#4c8aff', width=1))
        self._hover_lbl.setZValue(10)
        self.pw.addItem(self._hover_lbl)
        self._hover_lbl.hide()
        self.pw.scene().sigMouseMoved.connect(self._on_mouse)
        v.addWidget(self.pw, 1)

        # ── Color legend bar ──────────────────────────────────────────────────
        leg_bar = QWidget()
        leg_bar.setFixedHeight(22)
        leg_bar.setStyleSheet(f'background: {T("bg2")};')
        ll = QHBoxLayout(leg_bar)
        ll.setContentsMargins(10, 2, 10, 2)
        ll.setSpacing(14)

        def _dot(color: str) -> QLabel:
            d = QLabel('●')
            d.setStyleSheet(f'color: {color}; font-size: 11px; background: transparent;')
            d.setFixedWidth(12)
            return d

        def _ltxt(text: str) -> QLabel:
            lb = QLabel(text)
            lb.setStyleSheet(f'color: {C.fg2}; font-size: 10px; background: transparent;')
            return lb

        for dot_color, label in [
            ('#5664b4', 'Normal (low end)'),
            ('#c86447', 'Normal (high end)'),
            ('#dc3c3c', 'Outlier — above χ²(α=0.001) threshold'),
            ('#dca028', 'Sparse subject (n_obs < 5, threshold approximate)'),
            ('#646464', 'No n_obs data (dataset not loaded)'),
        ]:
            ll.addWidget(_dot(dot_color))
            ll.addWidget(_ltxt(label))

        ll.addStretch()
        v.addWidget(leg_bar)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_dataset_path(self, path: str | None):
        """Called by the Evaluation tab when a new model is loaded."""
        self._dataset_path   = path
        self._n_obs          = {}
        self._norm_available = None
        self._thr_arr        = None
        self._norm_btn.setEnabled(True)
        self._status_lbl.hide()
        if self._norm_btn.isChecked():
            self._abs_btn.setChecked(True)
        # Redraw absolute view with updated state
        if len(self._obj_sorted) > 0:
            self._redraw()

    def set_theme(self, bg, fg):
        if not HAS_PG:
            return
        self.pw.setBackground(bg)
        fg_color = pg.mkColor(fg)
        for ax_name in ('left', 'bottom'):
            ax = self.pw.getAxis(ax_name)
            ax.setPen(fg_color)
            ax.setTextPen(fg_color)

    def load(self, phi):
        if not HAS_PG:
            return
        obj = np.array(phi.get('obj', []), dtype=float)
        ids = phi.get('ids', [])
        if len(obj) == 0:
            return
        order = np.argsort(obj)
        self._obj_sorted = obj[order]
        self._ids_sorted = [ids[i] for i in order] if ids else list(range(len(order)))
        self._exp_btn.setEnabled(True)
        self._redraw()

    # ── Mode toggle ───────────────────────────────────────────────────────────

    def _on_mode_toggled(self, btn_id: int, checked: bool):
        if not checked:
            return
        if btn_id == 0:   # Absolute
            self._status_lbl.hide()
            self._redraw()
        else:             # Normalised
            if self._norm_available is True:
                self._redraw()
            elif self._norm_available is False:
                self._show_status('Dataset not found — normalisation unavailable', C.orange)
                self._norm_btn.setEnabled(False)
                self._abs_btn.setChecked(True)
            else:
                self._start_norm_load()

    def _start_norm_load(self):
        if not self._dataset_path or not Path(self._dataset_path).is_file():
            self._norm_available = False
            self._show_status('Dataset not found — normalisation unavailable', C.orange)
            self._norm_btn.setEnabled(False)
            self._abs_btn.setChecked(True)
            return
        self._norm_btn.setEnabled(False)
        self._show_status('Reading dataset…', C.fg2)
        self._norm_worker = _NormLoadWorker(self._dataset_path)
        self._norm_worker.finished.connect(self._on_norm_loaded)
        self._norm_worker.failed.connect(self._on_norm_failed)
        self._norm_worker.start()

    def _on_norm_loaded(self, counts: dict):
        self._n_obs          = counts
        self._norm_available = True
        self._norm_btn.setEnabled(True)
        self._status_lbl.hide()
        self._redraw()

    def _on_norm_failed(self, msg: str):
        self._norm_available = False
        self._norm_btn.setEnabled(False)
        self._show_status(f'Normalisation unavailable: {msg}', C.orange)
        self._abs_btn.setChecked(True)

    def _show_status(self, text: str, color: str):
        self._status_lbl.setStyleSheet(f'color: {color}; font-size: 11px; background: transparent;')
        self._status_lbl.setText(text)
        self._status_lbl.show()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _redraw(self):
        if not HAS_PG or len(self._obj_sorted) == 0:
            return
        self.pw.clear()
        self.pw.addItem(self._hover_lbl)
        self._hover_lbl.hide()

        normalised = self._norm_btn.isChecked() and self._norm_available is True
        n          = len(self._obj_sorted)
        xs         = np.arange(n, dtype=float)

        # n_obs array aligned to the sorted subject order
        n_obs_arr = np.array([
            self._n_obs.get(float(sid), 0) if sid is not None else 0
            for sid in self._ids_sorted
        ], dtype=float)

        # Values to plot
        if normalised:
            safe_n = np.where(n_obs_arr > 0, n_obs_arr, np.nan)
            values = self._obj_sorted / safe_n
            self.pw.setTitle('Individual OFV Contributions  ·  per observation  (iOFV / n_obs)')
            self.pw.setLabel('left', 'iOFV / n_obs')
        else:
            values = self._obj_sorted.copy()
            self.pw.setTitle('Individual OFV Contributions  (absolute iOFV)')
            self.pw.setLabel('left', 'iOFV')

        # Per-subject chi-squared thresholds
        if HAS_SCIPY and np.any(n_obs_arr > 0):
            df_arr  = np.where(n_obs_arr > 0, n_obs_arr, 1.0)
            abs_thr = _chi2.ppf(1 - _CHI2_ALPHA, df=df_arr)         # absolute
            if normalised:
                self._thr_arr = np.where(n_obs_arr > 0, abs_thr / df_arr, np.nan)
            else:
                self._thr_arr = np.where(n_obs_arr > 0, abs_thr, np.nan)
        else:
            self._thr_arr = None

        # Bar colors
        mn  = float(np.nanmin(values))
        mx  = float(np.nanmax(values))
        rng = max(mx - mn, 1e-12)

        brushes = []
        for i, v in enumerate(values):
            n_i = n_obs_arr[i]
            if np.isnan(v) or n_i == 0:
                brushes.append(pg.mkBrush(100, 100, 100, 150))   # grey: no data
                continue
            is_outlier = (self._thr_arr is not None
                          and not np.isnan(self._thr_arr[i])
                          and v > self._thr_arr[i])
            is_sparse  = 0 < n_i < _SPARSE_NOBS
            if is_outlier:
                brushes.append(pg.mkBrush(220, 60, 60, 210))     # red
            elif is_sparse:
                brushes.append(pg.mkBrush(220, 160, 40, 200))    # amber
            else:
                t = (v - mn) / rng
                brushes.append(pg.mkBrush(
                    int(244 * t + 86  * (1 - t)),
                    100,
                    int(71  * t + 156 * (1 - t)),
                    200))

        self.pw.addItem(pg.BarGraphItem(
            x=xs, height=np.nan_to_num(values),
            width=0.8, brushes=brushes))

        # Threshold overlay
        if self._thr_arr is not None:
            valid = ~np.isnan(self._thr_arr)
            if normalised:
                # Smooth decreasing curve through the per-subject thresholds
                if np.any(valid):
                    self.pw.addItem(pg.PlotDataItem(
                        xs[valid], self._thr_arr[valid],
                        pen=pg.mkPen(C.red, width=1.5, style=Qt.PenStyle.DashLine)))
                    # Label at the rightmost valid point
                    last = int(np.where(valid)[0][-1])
                    lbl = pg.TextItem(
                        f'χ²(α={_CHI2_ALPHA}) / n_obs',
                        anchor=(1.0, 1.4), color=C.red)
                    lbl.setPos(xs[last], float(self._thr_arr[last]))
                    self.pw.addItem(lbl)
            else:
                # Step function: one horizontal tick per bar — drawn as single path
                seg_x, seg_y = [], []
                for i in range(n):
                    if not valid[i]:
                        continue
                    seg_x += [xs[i] - 0.4, xs[i] + 0.4, float('nan')]
                    seg_y += [self._thr_arr[i], self._thr_arr[i], float('nan')]
                if seg_x:
                    self.pw.addItem(pg.PlotDataItem(
                        np.array(seg_x), np.array(seg_y),
                        pen=pg.mkPen(C.red, width=1.5),
                        connect='finite'))
                    last_valid = [i for i in range(n) if valid[i]][-1]
                    lbl = pg.TextItem(
                        f'χ²(α={_CHI2_ALPHA})',
                        anchor=(1.0, 1.4), color=C.red)
                    lbl.setPos(xs[last_valid], float(self._thr_arr[last_valid]))
                    self.pw.addItem(lbl)
        else:
            # scipy absent — fallback with clear warning label
            fallback = float(np.nanmean(values) + 2 * np.nanstd(values))
            self.pw.addItem(pg.InfiniteLine(
                pos=fallback, angle=0,
                pen=pg.mkPen(C.red, width=1.5, style=Qt.PenStyle.DashLine),
                label=f'mean+2SD = {fallback:.2f}  [install scipy for χ² threshold]',
                labelOpts={'color': C.red, 'position': 0.95}))

    # ── Mouse hover ───────────────────────────────────────────────────────────

    def _on_mouse(self, pos):
        if len(self._ids_sorted) == 0:
            return
        try:
            mp = self.pw.plotItem.vb.mapSceneToView(pos)
            xi = int(round(mp.x()))
            if 0 <= xi < len(self._ids_sorted):
                sid  = self._ids_sorted[xi]
                ov   = float(self._obj_sorted[xi])
                nobs = int(self._n_obs.get(float(sid) if sid is not None else sid, 0))
                normalised = self._norm_btn.isChecked() and self._norm_available is True

                lines = [f'ID {sid:.0f}   iOFV {ov:.3f}']
                if nobs > 0:
                    lines.append(f'n_obs {nobs}')
                    if normalised:
                        lines.append(f'iOFV/n {ov/nobs:.4f}')
                if self._thr_arr is not None and 0 <= xi < len(self._thr_arr):
                    thr = self._thr_arr[xi]
                    if not np.isnan(thr):
                        label = 'χ²-thr/n' if normalised else 'χ²-thr'
                        lines.append(f'{label} {thr:.3f}')
                if 0 < nobs < _SPARSE_NOBS:
                    lines.append('⚠ sparse — threshold approximate')

                self._hover_lbl.setText('\n'.join(lines))
                self._hover_lbl.setPos(xi, ov)
                self._hover_lbl.show()
            else:
                self._hover_lbl.hide()
        except Exception:
            self._hover_lbl.hide()

    # ── Export ────────────────────────────────────────────────────────────────

    def _export(self):
        if not HAS_PG:
            return
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Save Waterfall Plot', str(Path.home() / 'waterfall.png'),
            'PNG images (*.png)')
        if not dst:
            return
        try:
            from pyqtgraph.exporters import ImageExporter
            exp   = ImageExporter(self.pw.scene())
            w     = self.pw.width()
            h     = self.pw.height()
            scale = max(1, 3000 // max(w, 1))
            exp.parameters()['width']  = w * scale
            exp.parameters()['height'] = h * scale
            exp.export(dst)
            if QMessageBox.question(
                    self, 'Saved', f'Saved to:\n{dst}\n\nOpen?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes:
                if sys.platform == 'win32':    os.startfile(dst)
                elif sys.platform == 'darwin': subprocess.Popen(['open', dst])
                else:                          subprocess.Popen(['xdg-open', dst])
        except Exception as e:
            QMessageBox.warning(self, 'Export failed', str(e))
