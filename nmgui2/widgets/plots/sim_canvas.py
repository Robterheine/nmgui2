"""Matplotlib canvas for Monte Carlo simulation prediction interval plots."""
import re
from pathlib import Path

try:
    import matplotlib
    matplotlib.use('QtAgg')
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

try:
    import numpy as np
    HAS_NP = True
except ImportError:
    HAS_NP = False

try:
    import pandas as pd
    HAS_PD = True
except ImportError:
    HAS_PD = False

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                              QFileDialog, QMessageBox)
from PyQt6.QtCore import QThread, pyqtSignal

from ...app.theme import THEMES, _active_theme
from ...widgets._icons import _placeholder


# ── Background worker ──────────────────────────────────────────────────────────

class _SimWorker(QThread):
    """Compute per-x-point quantiles across replicates in a background thread."""
    finished = pyqtSignal(dict)   # keys: times, bands (list of lo/med/hi arrays)
    error    = pyqtSignal(str)

    def __init__(self, df, x_col, y_col, rep_col, band_pcts, filters, mdv_filter):
        super().__init__()
        self._df         = df
        self._x_col      = x_col
        self._y_col      = y_col
        self._rep_col    = rep_col
        self._band_pcts  = band_pcts   # list of (lo_pct, hi_pct) floats 0-100
        self._filters    = filters     # list of (col, op, val_str)
        self._mdv_filter = mdv_filter

    def run(self):
        try:
            df = self._df.copy()

            # MDV filter first
            if self._mdv_filter and 'MDV' in df.columns:
                df = df[df['MDV'] != 1]

            # User-defined column filters (ANDed)
            for col, op, val_str in self._filters:
                if col not in df.columns or not val_str:
                    continue
                try:
                    val = float(val_str)
                    numeric = True
                except ValueError:
                    val = val_str
                    numeric = False
                try:
                    if numeric:
                        col_data = df[col].astype(float)
                        if op == '==':  df = df[col_data == val]
                        elif op == '!=': df = df[col_data != val]
                        elif op == '>':  df = df[col_data >  val]
                        elif op == '<':  df = df[col_data <  val]
                        elif op == '>=': df = df[col_data >= val]
                        elif op == '<=': df = df[col_data <= val]
                    else:
                        col_str = df[col].astype(str)
                        if op == '==':  df = df[col_str == val]
                        elif op == '!=': df = df[col_str != val]
                except Exception:
                    pass  # skip broken filter silently

            if df.empty:
                self.error.emit('No rows remain after applying filters.')
                return

            x_col   = self._x_col
            y_col   = self._y_col
            rep_col = self._rep_col

            for col in (x_col, y_col, rep_col):
                if col not in df.columns:
                    self.error.emit(f"Column '{col}' not found after filtering.")
                    return

            # Coerce to numeric; non-numeric rows become NaN
            df[x_col]   = pd.to_numeric(df[x_col],   errors='coerce')
            df[y_col]   = pd.to_numeric(df[y_col],   errors='coerce')
            df[rep_col] = pd.to_numeric(df[rep_col], errors='coerce')
            df = df.dropna(subset=[x_col, y_col, rep_col])

            if df.empty:
                self.error.emit('No valid numeric rows for selected columns.')
                return

            # Pivot: index=x_col (time), columns=rep_col (replicate), values=y_col
            # aggfunc='mean' handles duplicate (time, rep) combos gracefully.
            # Missing (time, rep) combinations → NaN (ragged grid handled).
            pivot = df.pivot_table(index=x_col, columns=rep_col,
                                   values=y_col, aggfunc='mean')
            times = pivot.index.to_numpy(dtype=float)
            vals  = pivot.to_numpy(dtype=float)   # shape: (n_times, n_reps)

            # Guard against empty-slice nanquantile (all-NaN column)
            n_valid = np.sum(~np.isnan(vals), axis=1)
            good = n_valid > 0
            if not np.any(good):
                self.error.emit('All values are NaN for the selected columns.')
                return

            result = {'times': times[good], 'bands': []}
            for lo_pct, hi_pct in self._band_pcts:
                lo  = np.nanquantile(vals[good], lo_pct / 100.0, axis=1)
                med = np.nanquantile(vals[good], 0.50,           axis=1)
                hi  = np.nanquantile(vals[good], hi_pct / 100.0, axis=1)
                result['bands'].append({'lo': lo, 'med': med, 'hi': hi})

            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ── Canvas widget ──────────────────────────────────────────────────────────────

class SimCanvas(QWidget):
    """Matplotlib canvas showing simulated PI ribbons + median."""

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        if not HAS_MPL or not HAS_NP or not HAS_PD:
            missing = [p for p, h in [('matplotlib', HAS_MPL),
                                       ('numpy', HAS_NP), ('pandas', HAS_PD)] if not h]
            v.addWidget(_placeholder(f"Install: pip3 install {' '.join(missing)}"))
            return

        # Toolbar row
        tb = QWidget(); tb.setFixedHeight(30)
        tbl = QHBoxLayout(tb)
        tbl.setContentsMargins(8, 3, 8, 3); tbl.setSpacing(6)
        tbl.addStretch()
        self._export_btn = QPushButton('Save PNG…')
        self._export_btn.setFixedHeight(22)
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export_png)
        tbl.addWidget(self._export_btn)
        v.addWidget(tb)

        self.fig    = Figure(figsize=(8, 5), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax     = self.fig.add_subplot(111)
        v.addWidget(self.canvas, 1)

        self._apply_theme_colors()

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_theme(self, bg, fg):
        if not HAS_MPL: return
        self._apply_theme_colors()
        self.canvas.draw()

    def plot_result(self, result, band_specs, x_label='', y_label='',
                    log_y=False, obs_xy=None):
        """Render quantile ribbons from a worker result dict.

        band_specs: list of {'lo_pct', 'hi_pct', 'color', 'alpha', 'visible'}
        obs_xy: (x_array, y_array) or None
        """
        if not HAS_MPL: return
        self.ax.clear()
        self._apply_theme_colors()

        t = THEMES[_active_theme]
        fg  = t['fg'];  fg2 = t['fg2']

        times  = result['times']
        bands  = result['bands']    # list of {lo, med, hi}

        plotted_any = False
        for spec, band in zip(band_specs, bands):
            if not spec.get('visible', True):
                continue
            color = spec['color']
            alpha = float(spec.get('alpha', 0.25))
            lo_p  = spec['lo_pct'];  hi_p = spec['hi_pct']
            label = f'{lo_p}–{hi_p}% PI'
            self.ax.fill_between(times, band['lo'], band['hi'],
                                 color=color, alpha=alpha, label=label)
            plotted_any = True

        # Draw median from last visible band (all bands share the same median)
        last_med = None
        for spec, band in zip(band_specs, bands):
            if spec.get('visible', True):
                last_med = band['med']
        if last_med is not None:
            med_color = band_specs[0].get('median_color', fg)
            med_lw    = band_specs[0].get('median_lw', 2.0)
            self.ax.plot(times, last_med, color=med_color,
                         linewidth=med_lw, label='Median', zorder=5)
            plotted_any = True

        # Observed overlay (scatter)
        if obs_xy is not None:
            ox, oy = obs_xy
            self.ax.scatter(ox, oy, s=12, color=fg2, alpha=0.5,
                            zorder=6, label='Observed')

        if log_y:
            self.ax.set_yscale('log')
        else:
            self.ax.set_yscale('linear')

        self.ax.set_xlabel(x_label, color=fg2)
        self.ax.set_ylabel(y_label, color=fg2)
        self.ax.legend(framealpha=0.3, fontsize=9)
        self.canvas.draw()
        self._export_btn.setEnabled(plotted_any)

    def clear_plot(self):
        if not HAS_MPL: return
        self.ax.clear()
        self._apply_theme_colors()
        self.canvas.draw()
        self._export_btn.setEnabled(False)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _apply_theme_colors(self):
        if not HAS_MPL: return
        t   = THEMES[_active_theme]
        bg  = t['bg2'];  fg = t['fg'];  fg2 = t['fg2']
        self.fig.patch.set_facecolor(bg)
        self.ax.set_facecolor(bg)
        self.ax.tick_params(colors=fg2)
        self.ax.xaxis.label.set_color(fg2)
        self.ax.yaxis.label.set_color(fg2)
        for sp in self.ax.spines.values():
            sp.set_color(fg2)

    def _export_png(self):
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Save PNG', str(Path.home() / 'sim_plot.png'), 'PNG images (*.png)')
        if not dst: return
        try:
            self.fig.savefig(dst, dpi=300, bbox_inches='tight',
                             facecolor=self.fig.get_facecolor())
        except Exception as e:
            QMessageBox.critical(self, 'Export error', str(e))
