from PyQt6.QtWidgets import QWidget, QVBoxLayout
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
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0)
        if not HAS_PG or not HAS_NP: v.addWidget(_placeholder('Install pyqtgraph and numpy')); return
        self.gw = pg.GraphicsLayoutWidget(); v.addWidget(self.gw)

    def set_theme(self, bg, fg):
        if HAS_PG: self.gw.setBackground(bg)
        # Convergence panels recreated on each load

    def load(self, ext):
        if not HAS_PG or not HAS_NP or not ext: return
        self.gw.clear(); data=ext['data']; cols=ext['columns']
        if not data: return
        iters=np.array([r.get('ITERATION',i) for i,r in enumerate(data)])
        if 'OBJ' in cols:
            p1=self.gw.addPlot(row=0,col=0,title='OFV')
            p1.setLabel('left','OFV'); p1.setLabel('bottom','Iteration'); p1.showGrid(x=True,y=True,alpha=0.2)
            p1.plot(iters,np.array([r['OBJ'] for r in data]),pen=pg.mkPen(C.green,width=2))
        pcols=[c for c in cols if c not in ('ITERATION','OBJ') and
               any(c.startswith(p) for p in ('THETA','OMEGA','SIGMA'))]
        if pcols:
            p2=self.gw.addPlot(row=1,col=0,title='Parameters')
            p2.setLabel('left','Value'); p2.setLabel('bottom','Iteration')
            p2.showGrid(x=True,y=True,alpha=0.2); p2.addLegend()
            pal=['#569cd6','#4ec994','#ce9178','#dcdcaa','#c586c0','#9cdcfe','#f44747','#6a9955','#4fc1ff','#d7ba7d']
            for i,c in enumerate(pcols[:10]):
                vals=np.array([r.get(c,float('nan')) for r in data])
                p2.plot(iters,vals,pen=pg.mkPen(pal[i%len(pal)],width=1.5),name=c)
