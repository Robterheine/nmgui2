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
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                              QPushButton, QFileDialog, QMessageBox)
from ...app.theme import _active_theme, THEMES
from ...widgets._icons import _placeholder


class NPDEDistWidget(QWidget):
    """NPDE histogram with normal density overlay.

    Shows a 'No NPDE column' notice when the loaded table does not contain NPDE.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        if not HAS_MPL or not HAS_NP:
            v.addWidget(_placeholder('Install matplotlib:\npip3 install matplotlib')); return

        tb = QWidget(); tb.setFixedHeight(30)
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(8, 3, 8, 3); tbl.setSpacing(6)
        tbl.addStretch()
        self._export_btn = QPushButton('Save PNG…')
        self._export_btn.setFixedHeight(22); self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export_png)
        tbl.addWidget(self._export_btn)
        v.addWidget(tb)

        self.fig = Figure(figsize=(6, 4), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax = self.fig.add_subplot(111)
        v.addWidget(self.canvas)

    def _export_png(self):
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Save PNG', str(Path.home() / 'npde_dist.png'), 'PNG images (*.png)')
        if not dst: return
        try:
            self.fig.savefig(dst, dpi=300, bbox_inches='tight',
                             facecolor=self.fig.get_facecolor())
        except Exception as e:
            QMessageBox.critical(self, 'Export error', str(e))

    def load(self, header, rows, mdv_filter=True):
        if not HAS_MPL or not HAS_NP: return
        self._last_args = (header, rows, mdv_filter)
        H = [h.upper() for h in header]
        t = THEMES[_active_theme]; bg = t['bg2']; fg = t['fg']; fg2 = t['fg2']
        self.ax.clear()
        self.fig.patch.set_facecolor(bg); self.ax.set_facecolor(bg)
        self.ax.tick_params(colors=fg2)
        for sp in self.ax.spines.values(): sp.set_color(fg2)

        if 'NPDE' not in H:
            self.ax.text(0.5, 0.5, 'No NPDE column found in table file.\n\n'
                         'Add NPDE to the $TABLE record in your NONMEM control stream.',
                         ha='center', va='center', color=fg2,
                         transform=self.ax.transAxes, fontsize=11,
                         multialignment='center')
            self.ax.axis('off')
            self.canvas.draw()
            self._export_btn.setEnabled(False)
            return

        try:
            ni = H.index('NPDE'); mi = H.index('MDV') if 'MDV' in H else None
            npde = np.array([float(r[ni]) for r in rows
                             if (mi is None or not mdv_filter or r[mi] == 0)
                             and ni < len(r) and np.isfinite(float(r[ni]))])
            if len(npde) < 3: return

            self.ax.xaxis.label.set_color(fg2)
            self.ax.yaxis.label.set_color(fg2); self.ax.title.set_color(fg)
            self.ax.hist(npde, bins=30, density=True,
                         color=t['accent'], alpha=0.6, edgecolor='none')
            x = np.linspace(npde.min(), npde.max(), 200)
            mu, sigma = npde.mean(), npde.std()
            pdf = np.exp(-0.5 * ((x - mu) / sigma) ** 2) / (sigma * np.sqrt(2 * np.pi))
            self.ax.plot(x, pdf, color=t['red'], linewidth=2, label='Normal')
            self.ax.axvline(0, color=fg2, linewidth=1, linestyle='--')
            self.ax.set_xlabel('NPDE'); self.ax.set_ylabel('Density')
            self.ax.set_title(
                f'NPDE Distribution  (n={len(npde)}, mean={mu:.3f}, SD={sigma:.3f})')
            self.ax.legend(framealpha=0.3)
            self.canvas.draw()
            self._export_btn.setEnabled(True)
        except Exception: pass

    def set_theme(self, bg, fg):
        if HAS_MPL and hasattr(self, '_last_args'):
            self.load(*self._last_args)
