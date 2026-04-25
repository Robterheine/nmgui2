import os, subprocess, sys
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                              QLabel, QFileDialog, QComboBox)
from PyQt6.QtCore import Qt, QTimer
try: import pyqtgraph as pg; HAS_PG = True
except ImportError: HAS_PG = False
try: import numpy as np; HAS_NP = True
except ImportError: HAS_NP = False
from ...app.theme import C, T, THEMES, _active_theme
from ...app.format import loess
from ...widgets._icons import _placeholder

# 8-colour palette accessible to common colour-vision deficiencies
_PAL = ['#4c8aff', '#f4a028', '#3ec97a', '#e85555',
        '#c586c0', '#9cdcfe', '#dcdcaa', '#ff7f50']
_MIN_LOESS_N = 20   # minimum group size before drawing a LOESS line
_MAX_CAT     = 8    # unique-value threshold before auto-binning to quartiles


class GOFWidget(QWidget):
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
        self._leg_plot = None; self._leg_items = []; self._gof_legend = None
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        if not HAS_PG or not HAS_NP:
            v.addWidget(_placeholder('Install pyqtgraph and numpy:\npip3 install pyqtgraph numpy')); return
        self._replot_timer = QTimer(self)
        self._replot_timer.setSingleShot(True)
        self._replot_timer.setInterval(50)
        self._replot_timer.timeout.connect(self._replot)

        # ── Toolbar row 1: X-axis selectors + Export ──────────────────────────
        tb1 = QWidget(); tb1.setFixedHeight(36)
        tl1 = QHBoxLayout(tb1); tl1.setContentsMargins(8, 4, 8, 4); tl1.setSpacing(8)
        self._x_cbs = {}
        panel_labels = ['Top-left X:', 'Top-right X:', 'Bottom-left X:', 'Bottom-right X:']
        defaults     = ['PRED', 'IPRED', 'PRED', 'TIME']
        keys = [(0,0), (0,1), (1,0), (1,1)]
        for i, (key, lbl, dflt) in enumerate(zip(keys, panel_labels, defaults)):
            tl1.addWidget(QLabel(lbl))
            cb = QComboBox(); cb.setMinimumWidth(80); cb.addItem(dflt)
            cb.currentTextChanged.connect(self._schedule_replot)
            self._x_cbs[key] = cb
            tl1.addWidget(cb)
            if i < 3: tl1.addSpacing(4)
        tl1.addStretch()
        exp_btn = QPushButton('Export PNG…'); exp_btn.setFixedHeight(26)
        exp_btn.setToolTip('Save publication-ready 300 DPI PNG')
        exp_btn.clicked.connect(self._export)
        tl1.addWidget(exp_btn)
        v.addWidget(tb1)

        # ── Toolbar row 2: Color by + Filter ──────────────────────────────────
        tb2 = QWidget(); tb2.setFixedHeight(32)
        tl2 = QHBoxLayout(tb2); tl2.setContentsMargins(8, 3, 8, 3); tl2.setSpacing(8)
        tl2.addWidget(QLabel('Color by:'))
        self._color_cb = QComboBox(); self._color_cb.setMinimumWidth(110)
        self._color_cb.addItem('')
        self._color_cb.setToolTip(
            'Colour scatter points by a column value.\n'
            'Columns prefixed with ~ will be auto-binned into quartiles.')
        self._color_cb.currentTextChanged.connect(self._schedule_replot)
        tl2.addWidget(self._color_cb)
        tl2.addStretch()
        tl2.addWidget(QLabel('Filter:'))
        self._filt_col = QComboBox(); self._filt_col.setMinimumWidth(80); self._filt_col.addItem('')
        self._filt_val = QComboBox(); self._filt_val.setMinimumWidth(80); self._filt_val.setEditable(True)
        self._filt_col.currentTextChanged.connect(self._update_filter_vals)
        self._filt_val.currentTextChanged.connect(self._schedule_replot)
        tl2.addWidget(self._filt_col); tl2.addWidget(self._filt_val)
        v.addWidget(tb2)

        sep = QWidget(); sep.setFixedHeight(1); sep.setObjectName('hairlineSep')
        v.addWidget(sep)

        # ── Plot grid ─────────────────────────────────────────────────────────
        self.gw = pg.GraphicsLayoutWidget()
        v.addWidget(self.gw, 1)
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
        y_labels = {(0,0): 'DV', (0,1): 'DV', (1,0): 'CWRES', (1,1): 'CWRES'}
        reflines = {(0,0): True,  (0,1): True,  (1,0): False,   (1,1): False}
        for r in range(2):
            for c in range(2):
                key = (r, c)
                xl = self._x_cbs[key].currentText()
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
                pass
        return mask

    def _get_groups(self, col_name, mask):
        """Return list of (label, bool_mask) tuples.

        A single entry with label=None means no colour-by is active (uniform colour).
        Columns with ≤ _MAX_CAT unique values are treated as categorical.
        Columns with more unique values are binned into four equal-frequency quartiles.
        """
        if not col_name or col_name not in self._H:
            return [(None, mask)]
        ci = self._H.index(col_name)
        vals = self._arr[:, ci]
        valid = mask & np.isfinite(vals)
        unique = np.unique(vals[valid])
        if len(unique) == 0:
            return [(None, mask)]
        if len(unique) <= _MAX_CAT:
            groups = []
            for v in unique:
                gm = valid & (vals == v)
                try:    label = f'{v:.4g}'
                except: label = str(v)
                groups.append((label, gm))
            return groups
        # Continuous: bin into quartiles
        p25, p50, p75 = np.nanpercentile(vals[valid], [25, 50, 75])
        bins = [
            (f'Q1 (≤{p25:.3g})',           valid & (vals <= p25)),
            (f'Q2 ({p25:.3g}–{p50:.3g})',  valid & (vals > p25) & (vals <= p50)),
            (f'Q3 ({p50:.3g}–{p75:.3g})',  valid & (vals > p50) & (vals <= p75)),
            (f'Q4 (>{p75:.3g})',            valid & (vals > p75)),
        ]
        return [(lbl, gm) for lbl, gm in bins if gm.sum() > 0]

    def _schedule_replot(self, *_):
        self._replot_timer.start()

    def _replot(self):
        if self._arr is None: return
        try:
            mask = self._get_mask()
            raw = self._color_cb.currentText()
            col_name = raw[2:] if raw.startswith('~ ') else raw
            groups = self._get_groups(col_name, mask)
            using_color = len(groups) > 1

            reflines = {(0,0): True, (0,1): True, (1,0): False, (1,1): False}
            group_legend = []   # [(label, color_hex)] built from first panel

            for key, (p, _, old_xl, yl) in self._panels.items():
                xl = self._x_cbs[key].currentText()
                p.clear()
                if xl not in self._H or yl not in self._H: continue
                xd = self._arr[:, self._H.index(xl)]
                yd = self._arr[:, self._H.index(yl)]

                # Full-data extent for the reference line (drawn behind scatter)
                all_ok = mask & np.isfinite(xd) & np.isfinite(yd)
                if not all_ok.any(): continue
                p.setLabel('bottom', xl)
                x_all, y_all = xd[all_ok], yd[all_ok]
                if reflines[key]:
                    mn = min(x_all.min(), y_all.min()); mx = max(x_all.max(), y_all.max())
                    p.plot([mn, mx], [mn, mx], pen=pg.mkPen(C.red, width=1.5))
                else:
                    p.plot([x_all.min(), x_all.max()], [0, 0],
                           pen=pg.mkPen('#aaaaaa', width=1.5, style=Qt.PenStyle.DashLine))

                # Per-group scatter + LOESS
                for gi, (label, gmask) in enumerate(groups):
                    ok = gmask & np.isfinite(xd) & np.isfinite(yd)
                    x, y = xd[ok], yd[ok]
                    if len(x) == 0: continue

                    if using_color:
                        color = _PAL[gi % len(_PAL)]
                        qc = pg.mkColor(color)
                        brush = pg.mkBrush(qc.red(), qc.green(), qc.blue(), 150)
                        line_pen = pg.mkPen(color, width=2)
                    else:
                        brush = pg.mkBrush(60, 120, 220, 140)
                        line_pen = pg.mkPen('#ff9999', width=2)

                    p.addItem(pg.ScatterPlotItem(x=x, y=y, pen=None, brush=brush, size=5))

                    if len(x) >= _MIN_LOESS_N:
                        xlo, ylo = loess(x, y)
                        if xlo is not None:
                            p.plot(xlo, ylo, pen=line_pen)

                    # Collect legend entries once (from first panel)
                    if key == (0, 0) and using_color:
                        group_legend.append((label, _PAL[gi % len(_PAL)]))

            self._rebuild_legend(group_legend)
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug('GOF replot error: %s', e)

    def _rebuild_legend(self, group_colors):
        """Manage the shared legend row at row=2 in the gw grid.

        The row is created on first use and hidden/shown as needed.
        It lives inside the pyqtgraph scene so ImageExporter captures it.
        """
        # Remove previous dummy items (also removes them from the LegendItem)
        for item in self._leg_items:
            try: self._leg_plot.removeItem(item)
            except Exception: pass
        self._leg_items = []

        if not group_colors:
            if self._leg_plot is not None:
                self._leg_plot.setVisible(False)
            return

        # Create the legend PlotItem once
        if self._leg_plot is None:
            self._leg_plot = self.gw.addPlot(row=2, col=0, colspan=2)
            self._leg_plot.hideAxis('left')
            self._leg_plot.hideAxis('bottom')
            self._leg_plot.setMouseEnabled(x=False, y=False)
            # Fix the row to a compact height
            try:
                self.gw.ci.layout.setRowMaximumHeight(2, 36)
                self.gw.ci.layout.setRowMinimumHeight(2, 36)
            except Exception:
                self._leg_plot.setMaximumHeight(36)
                self._leg_plot.setMinimumHeight(36)
            self._gof_legend = self._leg_plot.addLegend(offset=(5, 2))

        self._leg_plot.setVisible(True)

        # Lay out legend items horizontally when possible
        try:
            self._gof_legend.setColumnCount(len(group_colors))
        except AttributeError:
            pass

        # Add a zero-length dummy plot item per group — this auto-populates the legend
        for label, color in group_colors:
            item = self._leg_plot.plot(
                [], [], pen=None, symbol='o',
                symbolBrush=pg.mkBrush(pg.mkColor(color)),
                symbolSize=9, name=label)
            self._leg_items.append(item)

    def load(self, header, rows, mdv_filter=True):
        if not HAS_PG or not HAS_NP: return
        if not rows or not header: return
        self._header = header; self._rows = rows; self._mdv_filter = mdv_filter
        self._H = [h.upper() for h in header]
        def to_float(v):
            try: return float(v)
            except (ValueError, TypeError): return float('nan')
        self._arr = np.array([[to_float(v) for v in row] for row in rows], dtype=float)

        # Populate X-axis dropdowns
        _panel_defaults = {(1,0): 'PRED', (1,1): 'TIME', (0,0): 'PRED', (0,1): 'IPRED'}
        for key, cb in self._x_cbs.items():
            cur = cb.currentText(); cb.blockSignals(True); cb.clear()
            cb.addItems(self._H)
            idx = cb.findText(cur)
            if idx < 0:
                fallback = _panel_defaults.get(key, '')
                idx = cb.findText(fallback)
            cb.setCurrentIndex(max(0, idx)); cb.blockSignals(False)

        # Populate Color-by dropdown.
        # Columns with > _MAX_CAT unique values are prefixed with '~ ' to signal
        # that selecting them will auto-bin into quartiles.
        cur_raw = self._color_cb.currentText()
        cur_col = cur_raw[2:] if cur_raw.startswith('~ ') else cur_raw
        color_items = ['']
        for h in self._H:
            col_vals = self._arr[:, self._H.index(h)]
            finite_vals = col_vals[np.isfinite(col_vals)]
            n_uniq = len(np.unique(finite_vals[:1000]))
            color_items.append(f'~ {h}' if n_uniq > _MAX_CAT else h)
        self._color_cb.blockSignals(True); self._color_cb.clear()
        self._color_cb.addItems(color_items)
        # Restore previous selection (try exact match, then with/without prefix)
        idx = self._color_cb.findText(cur_raw)
        if idx < 0 and cur_col:
            idx = self._color_cb.findText(cur_col)
            if idx < 0:
                idx = self._color_cb.findText(f'~ {cur_col}')
        self._color_cb.setCurrentIndex(max(0, idx)); self._color_cb.blockSignals(False)

        # Populate filter column combo
        self._filt_col.blockSignals(True); self._filt_col.clear()
        self._filt_col.addItems([''] + self._H); self._filt_col.blockSignals(False)

        self._replot()

    def _export(self):
        """Export the GOF 2×2 + legend row as a 300 DPI PNG via pyqtgraph."""
        if not HAS_PG or not HAS_NP: return
        if self._arr is None:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, 'No data', 'Load data first.'); return
        from pathlib import Path
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Export GOF plot', str(Path.home() / 'gof_plot.png'),
            'PNG images (*.png)')
        if not dst: return
        try:
            from pyqtgraph.exporters import ImageExporter
            exp = ImageExporter(self.gw.scene())
            w = self.gw.width(); h = self.gw.height()
            scale = max(1, 3000 // max(w, 1))
            exp.parameters()['width']  = w * scale
            exp.parameters()['height'] = h * scale
            exp.export(dst)
            from PyQt6.QtWidgets import QMessageBox
            if QMessageBox.question(self, 'Exported', f'GOF plot saved to:\n{dst}\n\nOpen?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes:
                if sys.platform == 'win32':    os.startfile(dst)
                elif sys.platform == 'darwin': subprocess.Popen(['open', dst])
                else:                          subprocess.Popen(['xdg-open', dst])
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, 'Export failed', str(e))
