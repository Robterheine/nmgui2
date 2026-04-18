import math
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog, QComboBox
from PyQt6.QtCore import Qt
try: import pyqtgraph as pg; HAS_PG = True
except ImportError: HAS_PG = False
try: import numpy as np; HAS_NP = True
except ImportError: HAS_NP = False
from ...app.theme import C, T, THEMES, _active_theme
from ...app.format import loess
from ...widgets._icons import _placeholder


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

        sep = QWidget(); sep.setFixedHeight(1); sep.setStyleSheet(f'background:{C.border};')
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
                    p.plot([mn,mx],[mn,mx], pen=pg.mkPen(C.red, width=1.5))
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
        from pathlib import Path
        HOME = Path.home()
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
            import sys
            IS_WIN = sys.platform == 'win32'
            IS_MAC = sys.platform == 'darwin'
            if QMessageBox.question(self,'Exported',f'GOF plot saved to:\n{dst}\n\nOpen?',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes:
                if IS_WIN:   __import__('os').startfile(dst)
                elif IS_MAC: __import__('subprocess').Popen(['open', dst])
                else:        __import__('subprocess').Popen(['xdg-open', dst])
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self,'Export failed',str(e))
