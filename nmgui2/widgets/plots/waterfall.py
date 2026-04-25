import os, subprocess, sys
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                              QFileDialog, QMessageBox)
from PyQt6.QtCore import Qt
try: import pyqtgraph as pg; HAS_PG = True
except ImportError: HAS_PG = False
try: import numpy as np; HAS_NP = True
except ImportError: HAS_NP = False
from ...app.theme import C, T
from ...widgets._icons import _placeholder


class WaterfallWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        if not HAS_PG or not HAS_NP:
            v.addWidget(_placeholder('Install pyqtgraph and numpy')); return

        self._ids_sorted = []; self._obj_sorted = np.array([])

        # ── Toolbar ───────────────────────────────────────────────────────────
        tb = QWidget(); tb.setFixedHeight(34)
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(8, 4, 8, 4); tbl.setSpacing(6)
        tbl.addStretch()
        self._exp_btn = QPushButton('Save PNG…')
        self._exp_btn.setFixedHeight(26)
        self._exp_btn.setEnabled(False)
        self._exp_btn.clicked.connect(self._export)
        tbl.addWidget(self._exp_btn)
        v.addWidget(tb)

        sep = QWidget(); sep.setFixedHeight(1); sep.setObjectName('hairlineSep')
        v.addWidget(sep)

        self.pw = pg.PlotWidget(title='Individual OFV Contributions')
        self.pw.setLabel('left', 'iOFV'); self.pw.setLabel('bottom', 'Subject rank')
        self.pw.showGrid(x=True, y=True, alpha=0.2)
        self.pw.getAxis('bottom').enableAutoSIPrefix(False)
        self.pw.getAxis('left').enableAutoSIPrefix(False)
        # Tooltip box
        self._hover_lbl = pg.TextItem(
            '', anchor=(0.5, 1.3),
            color='#ffffff',
            fill=pg.mkBrush(30, 30, 40, 220),
            border=pg.mkPen('#4c8aff', width=1))
        self._hover_lbl.setZValue(10)
        self.pw.addItem(self._hover_lbl); self._hover_lbl.hide()
        self.pw.scene().sigMouseMoved.connect(self._on_mouse)
        v.addWidget(self.pw, 1)

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
        obj = np.array(phi.get('obj', []), dtype=float)
        ids = phi.get('ids', [])
        if len(obj) == 0: return
        order = np.argsort(obj)
        self._obj_sorted = obj[order]
        self._ids_sorted = [ids[i] for i in order] if ids else list(range(len(order)))
        n = len(self._obj_sorted)
        mn, mx = self._obj_sorted.min(), self._obj_sorted.max()

        # Outlier threshold: mean + 2 SD — bars above this are drawn red
        threshold = float(self._obj_sorted.mean() + 2 * self._obj_sorted.std())

        def _bar_color(v):
            if v > threshold:
                return pg.mkBrush(220, 60, 60, 210)
            t = (v - mn) / (mx - mn + 1e-12)
            return pg.mkBrush(
                int(244 * t + 86 * (1 - t)),
                100,
                int(71 * t + 156 * (1 - t)),
                200)

        brushes = [_bar_color(v) for v in self._obj_sorted]
        self.pw.addItem(pg.BarGraphItem(
            x=np.arange(n, dtype=float), height=self._obj_sorted,
            width=0.8, brushes=brushes))

        # Threshold line with label
        thr_line = pg.InfiniteLine(
            pos=threshold, angle=0,
            pen=pg.mkPen(C.red, width=1.5, style=Qt.PenStyle.DashLine),
            label=f'mean+2SD = {threshold:.1f}',
            labelOpts={'color': C.red, 'position': 0.95})
        self.pw.addItem(thr_line)
        self._exp_btn.setEnabled(True)

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

    def _export(self):
        if not HAS_PG or not HAS_NP: return
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Save Waterfall Plot', str(Path.home() / 'waterfall.png'),
            'PNG images (*.png)')
        if not dst: return
        try:
            from pyqtgraph.exporters import ImageExporter
            exp = ImageExporter(self.pw.scene())
            w = self.pw.width(); h = self.pw.height()
            scale = max(1, 3000 // max(w, 1))
            exp.parameters()['width']  = w * scale
            exp.parameters()['height'] = h * scale
            exp.export(dst)
            if QMessageBox.question(self, 'Saved', f'Saved to:\n{dst}\n\nOpen?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes:
                if sys.platform == 'win32':    os.startfile(dst)
                elif sys.platform == 'darwin': subprocess.Popen(['open', dst])
                else:                          subprocess.Popen(['xdg-open', dst])
        except Exception as e:
            QMessageBox.warning(self, 'Export failed', str(e))
