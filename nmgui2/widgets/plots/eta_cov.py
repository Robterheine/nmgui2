import math
import re
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QListWidget, QAbstractItemView,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
try: import pyqtgraph as pg; HAS_PG = True
except ImportError: HAS_PG = False
try: import numpy as np; HAS_NP = True
except ImportError: HAS_NP = False
from ...app.theme import C, T, THEMES, _active_theme
from ...app.format import loess
from ...widgets._icons import _placeholder


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

        sep = QWidget(); sep.setFixedHeight(1); sep.setObjectName('hairlineSep')
        v.addWidget(sep)

        self.gw = pg.GraphicsLayoutWidget(); v.addWidget(self.gw, 1)

    def set_theme(self, bg, fg):
        if HAS_PG and hasattr(self,'gw'): self.gw.setBackground(bg)

    def load(self, header, rows, mdv_filter=True):
        if not HAS_PG or not HAS_NP: return
        self._header = [h.upper() for h in header]
        # Filter out MDV=1 (dosing-only) rows so each individual contributes
        # one representative observation point rather than N_doses extra copies.
        if mdv_filter and 'MDV' in self._header:
            mdv_idx = self._header.index('MDV')
            try:
                rows = [r for r in rows if float(r[mdv_idx]) == 0]
            except (ValueError, TypeError, IndexError):
                pass
        self._rows = rows
        # ETAs: ETA\d+, ET\d+ (NONMEM truncates ETA(12) → ET12 in TABLE output), PHI\d+
        _eta = re.compile(r'^(?:ETA|ET|PHI)\d+$')
        etas = [h for h in self._header if _eta.match(h)]
        # Covariates: non-ETA numeric columns, excluding NONMEM bookkeeping columns
        skip = {'DV','PRED','IPRED','CWRES','NPDE','IWRES','WRES',
                'MDV','EVID','AMT','CMT','SS','II','ADDL','RATE'}
        cov_candidates = [h for h in self._header if not _eta.match(h)
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
            except (ValueError, TypeError): return float('nan')
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
