from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt
try: import pyqtgraph as pg; HAS_PG = True
except ImportError: HAS_PG = False
try: import numpy as np; HAS_NP = True
except ImportError: HAS_NP = False
from ...widgets._icons import _placeholder


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
