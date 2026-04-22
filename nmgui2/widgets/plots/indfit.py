import math
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox
from PyQt6.QtCore import Qt
try: import pyqtgraph as pg; HAS_PG = True
except ImportError: HAS_PG = False
try: import numpy as np; HAS_NP = True
except ImportError: HAS_NP = False
from ...app.theme import C, T, THEMES, _active_theme
from ...widgets._icons import _placeholder


class IndFitWidget(QWidget):
    GRIDS = {'2x2':2,'3x3':3,'4x4':4}

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
                if col >= len(row): continue   # guard against ragged rows
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
        pr_p=pg.mkPen(C.red,width=1,style=Qt.PenStyle.DashLine)
        for i,rid in enumerate(ids_page):
            ri,ci_=divmod(i,g); p=self.gw.addPlot(row=ri,col=ci_,title=f'ID {rid}')
            p.showGrid(x=True,y=True,alpha=0.15)
            rws=id_rows.get(rid,[]); ok=[cm is None or r[cm]==0 for r in rws]
            def cv(idx):
                if idx is None: return None
                try: return np.array([float(r[idx]) for r,o in zip(rws,ok) if o])
                except (ValueError, TypeError, IndexError): return None
            def cv_all(idx):
                if idx is None: return None
                try: return np.array([float(r[idx]) for r in rws])
                except (ValueError, TypeError, IndexError): return None
            to=cv(ct); dvo=cv(cd); ta=cv_all(ct); pra=cv_all(cp); ipa=cv_all(ci2)
            if to is not None and dvo is not None: p.addItem(pg.ScatterPlotItem(x=to,y=dvo,pen=None,brush=dv_b,size=6))
            if ta is not None and ipa is not None:
                o=np.argsort(ta); p.plot(ta[o],ipa[o],pen=ip_p)
            if ta is not None and pra is not None:
                o=np.argsort(ta); p.plot(ta[o],pra[o],pen=pr_p)
