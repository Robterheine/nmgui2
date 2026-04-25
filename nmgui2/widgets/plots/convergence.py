import os, subprocess, sys
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QListWidget, QAbstractItemView, QFileDialog, QMessageBox)
from PyQt6.QtCore import Qt
try: import pyqtgraph as pg; HAS_PG = True
except ImportError: HAS_PG = False
try: import numpy as np; HAS_NP = True
except ImportError: HAS_NP = False
from ...app.theme import C, T, THEMES, _active_theme
from ...widgets._icons import _placeholder


class ConvergenceWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ext = None
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        if not HAS_PG or not HAS_NP:
            v.addWidget(_placeholder('Install pyqtgraph and numpy')); return

        # ── Toolbar ───────────────────────────────────────────────────────────
        tb = QWidget(); tb.setFixedHeight(44)
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(8, 4, 8, 4); tbl.setSpacing(6)
        tbl.addWidget(QLabel('Parameters:'))
        self._param_list = QListWidget()
        self._param_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self._param_list.setFlow(QListWidget.Flow.LeftToRight)
        self._param_list.setFixedHeight(36)
        self._param_list.setMaximumWidth(600)
        self._param_list.itemSelectionChanged.connect(self._replot)
        tbl.addWidget(self._param_list, 1)
        tbl.addStretch()
        self._exp_btn = QPushButton('Save PNG…')
        self._exp_btn.setFixedHeight(26)
        self._exp_btn.setEnabled(False)
        self._exp_btn.clicked.connect(self._export)
        tbl.addWidget(self._exp_btn)
        v.addWidget(tb)

        sep = QWidget(); sep.setFixedHeight(1); sep.setObjectName('hairlineSep')
        v.addWidget(sep)

        self.gw = pg.GraphicsLayoutWidget()
        v.addWidget(self.gw, 1)

    def set_theme(self, bg, fg):
        if HAS_PG and hasattr(self, 'gw'): self.gw.setBackground(bg)

    def load(self, ext):
        if not HAS_PG or not HAS_NP or not ext: return
        self._ext = ext
        cols = ext.get('columns', [])
        pcols = [c for c in cols if c not in ('ITERATION', 'OBJ') and
                 any(c.startswith(p) for p in ('THETA', 'OMEGA', 'SIGMA'))]
        self._param_list.blockSignals(True)
        self._param_list.clear()
        for c in pcols:
            self._param_list.addItem(c)
        for i in range(self._param_list.count()):
            self._param_list.item(i).setSelected(True)
        self._param_list.blockSignals(False)
        self._replot()
        self._exp_btn.setEnabled(True)

    def _replot(self):
        if not HAS_PG or not HAS_NP or self._ext is None: return
        self.gw.clear()
        data = self._ext['data']; cols = self._ext['columns']
        if not data: return
        iters = np.array([r.get('ITERATION', i) for i, r in enumerate(data)])
        if 'OBJ' in cols:
            p1 = self.gw.addPlot(row=0, col=0, title='OFV')
            p1.setLabel('left', 'OFV'); p1.setLabel('bottom', 'Iteration')
            p1.showGrid(x=True, y=True, alpha=0.2)
            p1.plot(iters, np.array([r['OBJ'] for r in data]),
                    pen=pg.mkPen(C.green, width=2))
        selected = [item.text() for item in self._param_list.selectedItems()]
        if selected:
            p2 = self.gw.addPlot(row=1, col=0, title='Parameters')
            p2.setLabel('left', 'Value'); p2.setLabel('bottom', 'Iteration')
            p2.showGrid(x=True, y=True, alpha=0.2); p2.addLegend()
            pal = ['#569cd6', '#4ec994', '#ce9178', '#dcdcaa', '#c586c0',
                   '#9cdcfe', '#f44747', '#6a9955', '#4fc1ff', '#d7ba7d']
            for i, c in enumerate(selected):
                vals = np.array([r.get(c, float('nan')) for r in data])
                p2.plot(iters, vals, pen=pg.mkPen(pal[i % len(pal)], width=1.5), name=c)

    def _export(self):
        if not HAS_PG or not HAS_NP or self._ext is None: return
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Save Convergence Plot', str(Path.home() / 'convergence.png'),
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
            if QMessageBox.question(self, 'Saved', f'Saved to:\n{dst}\n\nOpen?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes:
                if sys.platform == 'win32':    os.startfile(dst)
                elif sys.platform == 'darwin': subprocess.Popen(['open', dst])
                else:                          subprocess.Popen(['xdg-open', dst])
        except Exception as e:
            QMessageBox.warning(self, 'Export failed', str(e))
