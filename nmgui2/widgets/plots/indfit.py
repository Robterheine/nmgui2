import math, os, subprocess, sys
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                              QLabel, QComboBox, QLineEdit, QFileDialog, QMessageBox)
from PyQt6.QtCore import Qt
try: import pyqtgraph as pg; HAS_PG = True
except ImportError: HAS_PG = False
try: import numpy as np; HAS_NP = True
except ImportError: HAS_NP = False
from ...app.theme import C, T, THEMES, _active_theme
from ...widgets._icons import _placeholder


class IndFitWidget(QWidget):
    GRIDS = {'2x2': 2, '3x3': 3, '4x4': 4}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._header = None; self._rows = None; self._ids = []; self._page = 0
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        if not HAS_PG or not HAS_NP:
            v.addWidget(_placeholder('Install pyqtgraph and numpy')); return

        # ── Toolbar ───────────────────────────────────────────────────────────
        tb = QWidget(); tb.setFixedHeight(36)
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(8, 4, 8, 4); tbl.setSpacing(6)
        tbl.addWidget(QLabel('Grid:'))
        self.grid_cb = QComboBox(); self.grid_cb.addItems(list(self.GRIDS.keys()))
        self.grid_cb.currentTextChanged.connect(self._render)
        tbl.addWidget(self.grid_cb)
        tbl.addSpacing(8)
        tbl.addWidget(QLabel('Jump to ID:'))
        self._id_search = QLineEdit()
        self._id_search.setPlaceholderText('ID…')
        self._id_search.setFixedWidth(90)
        self._id_search.returnPressed.connect(self._jump_to_id)
        tbl.addWidget(self._id_search)
        tbl.addStretch()
        self.prev_btn = QPushButton('<'); self.prev_btn.setFixedWidth(28)
        self.prev_btn.clicked.connect(self._prev)
        self.page_lbl = QLabel('')
        self.page_lbl.setFixedWidth(80)
        self.page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_btn = QPushButton('>'); self.next_btn.setFixedWidth(28)
        self.next_btn.clicked.connect(self._next)
        tbl.addWidget(self.prev_btn)
        tbl.addWidget(self.page_lbl)
        tbl.addWidget(self.next_btn)
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

    def load(self, header, rows, mdv_filter=True):
        if not HAS_PG or not HAS_NP: return
        if not rows or not header: return
        H = [h.upper() for h in header]
        # Pre-filter MDV=1 (dosing) rows so spikes are not drawn
        if mdv_filter and 'MDV' in H:
            mi = H.index('MDV')
            try:
                rows = [r for r in rows if float(r[mi]) == 0]
            except (ValueError, TypeError, IndexError):
                pass
        self._header = H; self._rows = rows
        if 'ID' in H:
            col = H.index('ID'); seen = {}
            for row in rows:
                if col >= len(row): continue
                v = row[col]
                if v not in seen: seen[v] = True
            self._ids = list(seen.keys())
        else:
            self._ids = []
        self._page = 0; self._render()
        self._exp_btn.setEnabled(bool(self._ids))

    def _pp(self): g = self.GRIDS.get(self.grid_cb.currentText(), 2); return g * g
    def _np(self): return max(1, math.ceil(len(self._ids) / self._pp()))

    def _prev(self):
        if self._page > 0: self._page -= 1; self._render()

    def _next(self):
        if self._page < self._np() - 1: self._page += 1; self._render()

    def _jump_to_id(self):
        txt = self._id_search.text().strip()
        if not txt or not self._ids: return
        target = None
        for iid in self._ids:
            if str(iid) == txt: target = iid; break
        if target is None:
            try:
                fv = float(txt)
                for iid in self._ids:
                    try:
                        if float(iid) == fv: target = iid; break
                    except (ValueError, TypeError): pass
            except ValueError: pass
        if target is None: return
        self._page = self._ids.index(target) // self._pp()
        self._render()

    def _render(self):
        if not HAS_PG or not HAS_NP or not self._ids:
            if HAS_PG and hasattr(self, 'gw'): self.gw.clear()
            return
        pp = self._pp(); g = self.GRIDS.get(self.grid_cb.currentText(), 2)
        ids_page = self._ids[self._page * pp:(self._page + 1) * pp]
        self.page_lbl.setText(f'{self._page + 1}/{self._np()}')
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < self._np() - 1)
        self.gw.clear()
        H = self._header
        def gi(name): return H.index(name) if name in H else None
        ci = gi('ID'); ct = gi('TIME'); cd = gi('DV'); cp = gi('PRED'); ci2 = gi('IPRED')
        id_rows = {}
        for row in self._rows:
            if ci is None: continue
            rid = row[ci]
            if rid not in id_rows: id_rows[rid] = []
            id_rows[rid].append(row)
        dv_b = pg.mkBrush(60, 120, 220, 160)
        ip_p = pg.mkPen('#1a1a2e' if _active_theme == 'light' else '#ffffff', width=2)
        pr_p = pg.mkPen(C.red, width=1, style=Qt.PenStyle.DashLine)
        for i, rid in enumerate(ids_page):
            ri, ci_ = divmod(i, g)
            p = self.gw.addPlot(row=ri, col=ci_, title=f'ID {rid}')
            p.showGrid(x=True, y=True, alpha=0.15)
            rws = id_rows.get(rid, [])
            def cv(idx, _rws=rws):
                if idx is None: return None
                try: return np.array([float(r[idx]) for r in _rws])
                except (ValueError, TypeError, IndexError): return None
            to = cv(ct); dvo = cv(cd); pra = cv(cp); ipa = cv(ci2)
            if to is not None and dvo is not None:
                p.addItem(pg.ScatterPlotItem(x=to, y=dvo, pen=None, brush=dv_b, size=6))
            if to is not None and ipa is not None:
                o = np.argsort(to); p.plot(to[o], ipa[o], pen=ip_p)
            if to is not None and pra is not None:
                o = np.argsort(to); p.plot(to[o], pra[o], pen=pr_p)

    def _export(self):
        if not HAS_PG or not HAS_NP or not self._ids: return
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Save Individual Fits', str(Path.home() / 'indfit.png'),
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
