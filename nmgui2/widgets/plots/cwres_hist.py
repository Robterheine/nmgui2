try:
    import matplotlib
    matplotlib.use('QtAgg')
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
try: import numpy as np; HAS_NP = True
except ImportError: HAS_NP = False
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from ...app.theme import _active_theme, THEMES
from ...widgets._icons import _placeholder


class CWRESHistWidget(QWidget):
    """CWRES histogram with normal density overlay."""
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0)
        if not HAS_MPL or not HAS_NP:
            v.addWidget(_placeholder('Install matplotlib:\npip3 install matplotlib')); return
        self.fig = Figure(figsize=(6,4), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax = self.fig.add_subplot(111)
        v.addWidget(self.canvas)

    def load(self, header, rows, mdv_filter=True):
        if not HAS_MPL or not HAS_NP: return
        H = [h.upper() for h in header]
        if 'CWRES' not in H: return
        try:
            ci = H.index('CWRES'); mi = H.index('MDV') if 'MDV' in H else None
            cwres = np.array([float(r[ci]) for r in rows
                if (mi is None or not mdv_filter or r[mi]==0) and ci < len(r)
                and np.isfinite(float(r[ci]))])
            if len(cwres) < 3: return
            self.ax.clear()
            t = THEMES[_active_theme]; bg=t['bg2']; fg=t['fg']; fg2=t['fg2']
            self.fig.patch.set_facecolor(bg); self.ax.set_facecolor(bg)
            self.ax.tick_params(colors=fg2); self.ax.xaxis.label.set_color(fg2)
            self.ax.yaxis.label.set_color(fg2); self.ax.title.set_color(fg)
            for sp in self.ax.spines.values(): sp.set_color(fg2)
            self.ax.hist(cwres, bins=30, density=True, color=t['accent'], alpha=0.6, edgecolor='none')
            x = np.linspace(cwres.min(), cwres.max(), 200)
            mu, sigma = cwres.mean(), cwres.std()
            pdf = np.exp(-0.5*((x-mu)/sigma)**2) / (sigma*np.sqrt(2*np.pi))
            self.ax.plot(x, pdf, color=t['red'], linewidth=2, label='Normal')
            self.ax.axvline(0, color=fg2, linewidth=1, linestyle='--')
            self.ax.set_xlabel('CWRES'); self.ax.set_ylabel('Density')
            self.ax.set_title(f'CWRES Distribution  (n={len(cwres)}, mean={mu:.3f}, SD={sigma:.3f})')
            self.ax.legend(framealpha=0.3)
            self.canvas.draw()
        except Exception: pass  # render errors are non-fatal

    def set_theme(self, bg, fg): pass
