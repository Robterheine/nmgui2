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
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QFileDialog, QMessageBox)
from PyQt6.QtCore import Qt
from ...app.theme import _active_theme, THEMES
from ...widgets._icons import _placeholder


class QQPlotWidget(QWidget):
    """Normal QQ plot of CWRES with normality statistics."""
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

        self.fig = Figure(figsize=(5, 5), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax = self.fig.add_subplot(111)
        v.addWidget(self.canvas, 1)

        self.stats_lbl = QLabel('')
        self.stats_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_lbl.setWordWrap(True)
        self.stats_lbl.setStyleSheet('font-size:12px;padding:8px 16px;')
        v.addWidget(self.stats_lbl)

    def _export_png(self):
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Save PNG', str(Path.home() / 'cwres_qq.png'), 'PNG images (*.png)')
        if not dst: return
        try:
            self.fig.savefig(dst, dpi=300, bbox_inches='tight',
                             facecolor=self.fig.get_facecolor())
        except Exception as e:
            QMessageBox.critical(self, 'Export error', str(e))

    @staticmethod
    def _norm_ppf(p):
        """Rational approximation for normal quantile (Beasley-Springer-Moro)."""
        a = np.array([2.515517, 0.802853, 0.010328])
        b = np.array([1.432788, 0.189269, 0.001308])
        p = np.clip(p, 1e-10, 1-1e-10)
        t = np.sqrt(-2*np.log(np.where(p < 0.5, p, 1-p)))
        num = a[0] + t*(a[1] + t*a[2])
        den = 1 + t*(b[0] + t*(b[1] + t*b[2]))
        z = t - num/den
        return np.where(p < 0.5, -z, z)

    @staticmethod
    def _shapiro_wilk_approx(x):
        """
        Approximate Shapiro-Wilk W statistic (numpy only, no scipy).
        Returns (W, p_value). Valid for n=3..5000.
        Uses the Royston (1992) approximation.
        """
        n = len(x)
        if n < 3: return None, None
        x = np.sort(x)
        m = np.arange(1, n+1, dtype=float)
        mi = (m - 3/8) / (n + 1/4)
        c = QQPlotWidget._norm_ppf(mi)
        c = c / np.sqrt((c**2).sum())
        a = np.zeros(n)
        half = n // 2
        a[-half:] = c[-half:]
        b = np.dot(a, x)
        W = b**2 / ((x - x.mean())**2).sum()
        W = min(max(W, 0.0), 1.0)
        if n <= 11:
            gamma = np.polyval([-2.706056, 4.434685, -2.071190, -0.147981, 0.221157, 0.0], W)
            mu_w  = np.polyval([0.0, 0.459, -2.273], n**(-0.5))
            sig_w = np.exp(np.polyval([0.0, -0.0006714, 0.025054, -0.6714, 1.3822], n**(-0.5)))
        else:
            u = np.log(1 - W)
            mu_w  = np.polyval([0.0, 0.0038915, -0.083751, -0.31082, -1.5861], np.log(n))
            sig_w = np.exp(np.polyval([0.0, -0.0023776, -0.0006714, 1.3822], np.log(n)))
            gamma = (u - mu_w) / sig_w
        p = 1 - 0.5*(1 + np.sign(gamma)*
            (1 - np.exp(-gamma**2*(0.196854 + 0.115194*abs(gamma) +
             0.000344*gamma**2 + 0.019527*abs(gamma)**3)**(-4))))
        p = float(np.clip(p, 1e-6, 1.0))
        return float(W), p

    def load(self, header, rows, mdv_filter=True):
        if not HAS_MPL or not HAS_NP: return
        H = [h.upper() for h in header]
        if 'CWRES' not in H: return
        try:
            ci = H.index('CWRES'); mi = H.index('MDV') if 'MDV' in H else None
            cwres = np.sort(np.array([float(r[ci]) for r in rows
                                      if (mi is None or not mdv_filter or r[mi] == 0)
                                      and ci < len(r) and np.isfinite(float(r[ci]))]))
            if len(cwres) < 3: return
            n = len(cwres)
            p = (np.arange(1, n+1) - 0.5) / n
            theoretical = self._norm_ppf(p)

            self.ax.clear()
            t = THEMES[_active_theme]; bg = t['bg2']; fg = t['fg']; fg2 = t['fg2']
            self.fig.patch.set_facecolor(bg); self.ax.set_facecolor(bg)
            self.ax.tick_params(colors=fg2); self.ax.xaxis.label.set_color(fg2)
            self.ax.yaxis.label.set_color(fg2); self.ax.title.set_color(fg)
            for sp in self.ax.spines.values(): sp.set_color(fg2)
            self.ax.scatter(theoretical, cwres, s=8, alpha=0.5, color=t['accent'])
            mn = min(theoretical.min(), cwres.min())
            mx = max(theoretical.max(), cwres.max())
            self.ax.plot([mn, mx], [mn, mx], color=t['red'], linewidth=1.5)
            self.ax.set_xlabel('Theoretical quantiles')
            self.ax.set_ylabel('Sample quantiles (CWRES)')
            self.ax.set_title(f'Normal QQ Plot — CWRES  (n={n})')
            self.canvas.draw()
            self._export_btn.setEnabled(True)

            W, p_val = self._shapiro_wilk_approx(cwres)
            if W is not None:
                normal = p_val > 0.05
                color = t['green'] if normal else t['red']
                verdict = 'consistent with normality' if normal else 'significant departure from normality'
                self.stats_lbl.setText(
                    f'Shapiro-Wilk  W = {W:.4f},  p = {p_val:.4f}\n'
                    f'{"✓" if normal else "✗"}  CWRES {verdict} (α = 0.05)')
                self.stats_lbl.setStyleSheet(
                    f'font-size:12px;padding:8px 16px;color:{color};')
            else:
                self.stats_lbl.setText('')
        except Exception:
            pass

    def set_theme(self, bg, fg): pass
