from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView, QFileDialog,
    QPushButton, QFrame,
)
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtCore import Qt
from pathlib import Path

from ..app.theme import C, T
from ..app.format import fmt_num, fmt_rse, fmt_ofv
from ..app.constants import HOME

try:
    from scipy.stats import chi2 as _chi2
    def _lrt_pval(dofv, df):
        if df <= 0 or dofv >= 0:
            return None
        return float(1.0 - _chi2.cdf(-dofv, df=df))
except ImportError:
    def _lrt_pval(dofv, df):
        return None


class ModelComparisonDialog(QDialog):
    """Side-by-side parameter comparison for two models."""

    def __init__(self, model_a, model_b, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Compare: {model_a["stem"]}  vs  {model_b["stem"]}')
        self.resize(900, 620)
        v = QVBoxLayout(self); v.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        for m, align in [(model_a, Qt.AlignmentFlag.AlignLeft),
                         (model_b, Qt.AlignmentFlag.AlignRight)]:
            lbl = QLabel(f'<b>{m["stem"]}</b><br>'
                         f'<span style="color:{C.fg2};font-size:11px;">'
                         f'OFV: {fmt_ofv(m.get("ofv"))}  ·  '
                         f'{m.get("estimation_method","")}  ·  '
                         f'{"✓ COV" if m.get("covariance_step") else ""}</span>')
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setAlignment(align)
            hdr.addWidget(lbl, 1)
        dofv = None
        if model_a.get('ofv') is not None and model_b.get('ofv') is not None:
            dofv = model_b['ofv'] - model_a['ofv']
        mid_lbl = QLabel(f'<b>ΔOFV: {dofv:+.3f}</b>' if dofv is not None else 'ΔOFV: —')
        mid_lbl.setTextFormat(Qt.TextFormat.RichText)
        mid_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col = C.green if dofv is not None and dofv < -3.84 else \
              C.orange if dofv is not None and dofv < 0 else C.red if dofv is not None else C.fg2
        mid_lbl.setStyleSheet(f'color:{col};font-size:14px;')
        hdr.insertWidget(1, mid_lbl)
        v.addLayout(hdr)

        # Comparison table
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        cols = ['Parameter', 'Name',
                f'{model_a["stem"]} Est.', f'{model_a["stem"]} RSE%',
                f'{model_b["stem"]} Est.', f'{model_b["stem"]} RSE%',
                'Δ Est.', 'Δ%']
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        chh = self.table.horizontalHeader()
        chh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        chh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c in range(2, len(cols)):
            chh.resizeSection(c, 90)
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

        rows = self._build_rows(model_a, model_b)
        self.table.setRowCount(len(rows))
        R = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        L = Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter
        grey = QBrush(QColor(C.fg2))

        for ri, row_data in enumerate(rows):
            lbl, nm, est_a, rse_a, est_b, rse_b, delta, delta_pct, is_block, is_fixed = row_data
            if is_block:
                for ci in range(len(cols)):
                    item = QTableWidgetItem(lbl if ci == 0 else '')
                    item.setBackground(QBrush(QColor(C.bg3)))
                    item.setForeground(QBrush(QColor(C.blue)))
                    f = item.font(); f.setBold(True); f.setPointSize(10); item.setFont(f)
                    self.table.setItem(ri, ci, item)
                continue
            vals = [lbl, nm, est_a, rse_a, est_b, rse_b, delta, delta_pct]
            aligns = [L, L, R, R, R, R, R, R]
            for ci, (txt, align) in enumerate(zip(vals, aligns)):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(align)
                if is_fixed: item.setForeground(grey)
                # Colour delta: green = improved RSE, red = worse
                if ci == 6 and txt and txt not in ('—', ''):
                    try:
                        d = float(txt)
                        item.setForeground(QBrush(QColor(C.green if d < 0 else C.red)))
                    except ValueError: pass
                if ci == 7 and txt and txt not in ('—', ''):
                    try:
                        dp = float(txt.rstrip('%'))
                        item.setForeground(QBrush(QColor(C.green if abs(dp) < 20 else C.orange if abs(dp) < 50 else C.red)))
                    except ValueError: pass
                self.table.setItem(ri, ci, item)

        v.addWidget(self.table, 1)

        # Shrinkage comparison
        shr_a = model_a.get('eta_shrinkage',[])
        shr_b = model_b.get('eta_shrinkage',[])
        if shr_a or shr_b:
            def fmt_shr(s): return '  '.join(f'ETA{i+1}: {v:.1f}%' for i,v in enumerate(s)) if s else '—'
            shr_lbl = QLabel(f'Shrinkage  {model_a["stem"]}: {fmt_shr(shr_a)}    '
                             f'{model_b["stem"]}: {fmt_shr(shr_b)}')
            shr_lbl.setStyleSheet(f'color:{C.fg2};font-size:11px;')
            v.addWidget(shr_lbl)

        # LRT / statistics strip
        v.addWidget(self._build_stats_strip(model_a, model_b))

        # Buttons
        btn_row = QHBoxLayout()
        export_btn = QPushButton('Export CSV')
        export_btn.clicked.connect(lambda: self._export_csv(model_a, model_b, rows))
        close_btn = QPushButton('Close'); close_btn.setObjectName('primary')
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(export_btn); btn_row.addStretch(); btn_row.addWidget(close_btn)
        v.addLayout(btn_row)

    def _build_stats_strip(self, ma, mb):
        """Horizontal strip showing ΔOFV, ΔAIC, ΔBIC, LRT p-value."""
        strip = QFrame()
        strip.setFrameShape(QFrame.Shape.StyledPanel)
        strip.setStyleSheet(f'background:{C.bg3};border-radius:6px;padding:2px;')
        row = QHBoxLayout(strip)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(24)

        ofv_a = ma.get('ofv'); ofv_b = mb.get('ofv')
        aic_a = ma.get('aic'); aic_b = mb.get('aic')
        bic_a = ma.get('bic'); bic_b = mb.get('bic')
        np_a  = ma.get('n_estimated_params'); np_b = mb.get('n_estimated_params')

        dofv  = (ofv_b - ofv_a) if (ofv_a is not None and ofv_b is not None) else None
        daic  = (aic_b - aic_a) if (aic_a is not None and aic_b is not None) else None
        dbic  = (bic_b - bic_a) if (bic_a is not None and bic_b is not None) else None
        dnpar = (np_b - np_a)   if (np_a  is not None and np_b  is not None) else None
        lrt_p = _lrt_pval(dofv, -dnpar) if (dofv is not None and dnpar is not None) else None

        def _stat(label, value_str, color=None):
            w = QLabel(f'<span style="font-size:10px;color:{C.fg2};">{label}</span><br>'
                       f'<b style="font-size:14px;{f"color:{color};" if color else ""}">{value_str}</b>')
            w.setTextFormat(Qt.TextFormat.RichText)
            return w

        ofv_col  = C.green if dofv is not None and dofv < -3.84 else \
                   C.orange if dofv is not None and dofv < 0 else \
                   C.red if dofv is not None else None
        aic_col  = C.green if daic is not None and daic < -2 else \
                   C.orange if daic is not None and daic < 0 else \
                   C.red if daic is not None else None

        if lrt_p is not None:
            lrt_col = C.green if lrt_p < 0.001 else C.orange if lrt_p < 0.05 else C.red
            lrt_str = f'{lrt_p:.4f}' if lrt_p >= 0.0001 else '<0.0001'
        else:
            lrt_col = None
            lrt_str = '—'

        row.addWidget(_stat('ΔOFV',  f'{dofv:+.3f}' if dofv is not None else '—', ofv_col))
        row.addWidget(_stat('ΔAIC',  f'{daic:+.2f}' if daic is not None else '—', aic_col))
        row.addWidget(_stat('ΔBIC',  f'{dbic:+.2f}' if dbic is not None else '—', aic_col))
        row.addWidget(_stat('Δ parameters', str(dnpar) if dnpar is not None else '—'))
        row.addWidget(_stat('LRT p-value', lrt_str, lrt_col))
        if lrt_p is not None:
            sig = ('Significant (p<0.001)' if lrt_p < 0.001 else
                   'Significant (p<0.05)'  if lrt_p < 0.05  else
                   'Not significant')
            sig_col = C.green if lrt_p < 0.05 else C.red
            row.addWidget(_stat('Verdict', sig, sig_col))
        row.addStretch()
        return strip

    def _build_rows(self, ma, mb):
        """Build comparison rows. Returns list of tuples."""
        rows = []
        blocks = [
            ('THETA', 'thetas','theta_ses','theta_names','theta_units','theta_fixed'),
            ('OMEGA', 'omegas','omega_ses','omega_names','omega_units','omega_fixed'),
            ('SIGMA', 'sigmas','sigma_ses','sigma_names','sigma_units','sigma_fixed'),
        ]
        for block, ek, sk, nk, uk, fk in blocks:
            ests_a = ma.get(ek,[]); ses_a = ma.get(sk,[]); names_a = ma.get(nk,[])
            units_a = ma.get(uk,[]); fixed_a = ma.get(fk,[])
            ests_b = mb.get(ek,[]); ses_b = mb.get(sk,[]); names_b = mb.get(nk,[])
            n = max(len(ests_a), len(ests_b))
            if n == 0: continue
            # Block header row
            rows.append((block,'','','','','','','', True, False))
            for i in range(n):
                ea  = ests_a[i] if i < len(ests_a) else None
                se_a= ses_a[i]  if i < len(ses_a)  else None
                eb  = ests_b[i] if i < len(ests_b) else None
                se_b= ses_b[i]  if i < len(ses_b)  else None
                nm  = (names_a[i] if i < len(names_a) else '') or \
                      (names_b[i] if i < len(names_b) else '')
                fx  = (fixed_a[i] if i < len(fixed_a) else False) or \
                      (mb.get(fk,[])[i] if i < len(mb.get(fk,[])) else False)
                lbl = f'{block}({i+1})'

                def _est(e): return fmt_num(e) if e is not None else '—'
                def _rse(e,s):
                    if e is None: return '—'
                    return fmt_rse(e,s) if s is not None else '...'
                def _delta(a,b):
                    if a is None or b is None: return '—'
                    return f'{b-a:+.4g}'
                def _dpct(a,b):
                    if a is None or b is None or abs(a) < 1e-12: return '—'
                    return f'{(b-a)/abs(a)*100:+.1f}%'

                rows.append((lbl, nm,
                             _est(ea), _rse(ea, se_a),
                             _est(eb), _rse(eb, se_b),
                             _delta(ea, eb), _dpct(ea, eb),
                             False, fx))
        return rows

    def _export_csv(self, ma, mb, rows):
        import csv as _csv
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Export comparison',
            str(HOME / f'compare_{ma["stem"]}_vs_{mb["stem"]}.csv'),
            'CSV files (*.csv)')
        if not dst: return
        with open(dst, 'w', newline='', encoding='utf-8') as f:
            w = _csv.writer(f)
            w.writerow(['Parameter','Name',
                        f'{ma["stem"]}_estimate', f'{ma["stem"]}_RSE',
                        f'{mb["stem"]}_estimate', f'{mb["stem"]}_RSE',
                        'delta_estimate', 'delta_pct'])
            for row in rows:
                if not row[8]:  # skip block headers
                    w.writerow(row[:8])
