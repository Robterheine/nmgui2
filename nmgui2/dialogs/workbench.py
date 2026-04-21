"""
Multi-model comparison workbench.

Shows all models from a directory in a single sortable table with
LRT p-values, ΔOFV, ΔAIC, and ΔBIC relative to a selected reference.
"""
import csv as _csv
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView, QComboBox,
    QPushButton, QFileDialog,
)
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtCore import Qt
from ..app.theme import C
from ..app.format import fmt_ofv, fmt_num
from ..app.constants import HOME

try:
    from scipy.stats import chi2 as _chi2
    def _lrt_pval(delta_ofv, delta_par):
        if delta_par <= 0 or delta_ofv >= 0:
            return None
        return float(1.0 - _chi2.cdf(-delta_ofv, df=delta_par))
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    def _lrt_pval(delta_ofv, delta_par):
        return None


_COL_LABELS = ['Model', 'Status', 'Method', 'nPar', 'OFV', 'ΔOFV', 'ΔAIC', 'ΔBIC', 'LRT p', 'COV', 'CN']
_C_MODEL, _C_STATUS, _C_METHOD, _C_NPAR, _C_OFV, _C_DOFV, _C_DAIC, _C_DBIC, _C_LRT, _C_COV, _C_CN = range(11)


class ModelWorkbenchDialog(QDialog):
    """Multi-model comparison workbench."""

    def __init__(self, models, ref_path=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Model Comparison Workbench')
        self.resize(1100, 580)
        self._models = [m for m in models if m.get('has_run')]
        self._ref_path = ref_path or (self._models[0]['path'] if self._models else None)

        v = QVBoxLayout(self)
        v.setSpacing(8)

        # ── Top bar ───────────────────────────────────────────────────────────
        top = QHBoxLayout()
        top.addWidget(QLabel('Reference model:'))
        self._ref_combo = QComboBox()
        self._ref_combo.setMinimumWidth(200)
        for m in self._models:
            self._ref_combo.addItem(m['stem'], m['path'])
        if self._ref_path:
            idx = next((i for i, m in enumerate(self._models) if m['path'] == self._ref_path), 0)
            self._ref_combo.setCurrentIndex(idx)
        self._ref_combo.currentIndexChanged.connect(self._on_ref_changed)
        top.addWidget(self._ref_combo)
        top.addStretch()
        if not HAS_SCIPY:
            lrt_lbl = QLabel('LRT p-values require scipy (pip install scipy)')
            lrt_lbl.setStyleSheet(f'color:{C.orange};font-size:11px;')
            top.addWidget(lrt_lbl)
        v.addLayout(top)

        # ── Table ─────────────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(len(_COL_LABELS))
        self._table.setHorizontalHeaderLabels(_COL_LABELS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(True)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(_C_MODEL,  QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(_C_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        for c in range(2, len(_COL_LABELS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

        # Tooltips on column headers
        tips = {
            _C_DOFV: 'ΔOFV relative to reference model',
            _C_DAIC:  'ΔAIC = ΔOFV + 2·Δk (lower is better)',
            _C_DBIC:  'ΔBIC = ΔOFV + ln(N)·Δk (lower is better, penalises parameters more)',
            _C_LRT:   'Likelihood ratio test p-value (chi-squared, df = |Δk|)\nOnly shown when alternative has fewer parameters than reference',
            _C_CN:    'Condition number — requires $COV PRINT=E',
        }
        for col, tip in tips.items():
            item = self._table.horizontalHeaderItem(col)
            if item:
                item.setToolTip(tip)

        v.addWidget(self._table, 1)

        # ── Significance legend ───────────────────────────────────────────────
        leg = QHBoxLayout()
        leg.addWidget(QLabel('Significance:'))
        for label, col in [('p < 0.001', C.green), ('p < 0.05', C.orange), ('not sig.', C.red), ('ref model', C.blue)]:
            dot = QLabel(f'  {label}')
            dot.setStyleSheet(f'color:{col};font-size:11px;font-weight:600;')
            leg.addWidget(dot)
        leg.addStretch()
        if not HAS_SCIPY:
            leg.addWidget(QLabel('Install scipy for LRT p-values'))
        v.addLayout(leg)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        export_btn = QPushButton('Export CSV')
        export_btn.clicked.connect(self._export_csv)
        close_btn = QPushButton('Close')
        close_btn.setObjectName('primary')
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(export_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        v.addLayout(btn_row)

        self._populate()

    def _on_ref_changed(self, idx):
        self._ref_path = self._ref_combo.itemData(idx)
        self._populate()

    def _ref_model(self):
        for m in self._models:
            if m['path'] == self._ref_path:
                return m
        return self._models[0] if self._models else None

    def _populate(self):
        ref = self._ref_model()
        ref_ofv    = ref.get('ofv')  if ref else None
        ref_aic    = ref.get('aic')  if ref else None
        ref_bic    = ref.get('bic')  if ref else None
        ref_npar   = ref.get('n_estimated_params') if ref else None
        ref_method = (ref.get('estimation_method', '') or '') if ref else ''
        n_obs_ref  = ref.get('n_observations') if ref else None

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(self._models))

        R = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        C_CENTER = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter

        for ri, m in enumerate(self._models):
            is_ref = (m['path'] == self._ref_path)
            ofv    = m.get('ofv')
            aic    = m.get('aic')
            bic    = m.get('bic')
            npar   = m.get('n_estimated_params')
            cov    = m.get('covariance_step')
            cn     = m.get('condition_number')
            status = m.get('minimization_message', '') or ''
            method = m.get('estimation_method', '') or ''

            # Deltas
            dofv = (ofv - ref_ofv) if (ofv is not None and ref_ofv is not None) else None
            daic = (aic - ref_aic) if (aic is not None and ref_aic is not None) else None
            dbic = (bic - ref_bic) if (bic is not None and ref_bic is not None) else None
            dnpar = (npar - ref_npar) if (npar is not None and ref_npar is not None) else None

            # LRT p-value — flip sign when the reference has more parameters
            # so df and dofv always have the signs _lrt_pval expects.
            lrt_p = None
            lrt_method_mismatch = (
                not is_ref
                and bool(method) and bool(ref_method)
                and method.upper() != ref_method.upper()
            )
            if not is_ref and not lrt_method_mismatch and dofv is not None and dnpar is not None and dnpar != 0:
                if dnpar > 0:
                    lrt_p = _lrt_pval(dofv, dnpar)
                else:
                    lrt_p = _lrt_pval(-dofv, -dnpar)

            def _item(txt, align=None, bold=False):
                it = QTableWidgetItem(txt)
                if align:
                    it.setTextAlignment(align)
                if bold:
                    f = it.font(); f.setBold(True); it.setFont(f)
                return it

            # Model name
            name_item = _item(m['stem'], bold=is_ref)
            if is_ref:
                name_item.setForeground(QBrush(QColor(C.blue)))
            self._table.setItem(ri, _C_MODEL, name_item)

            # Status — abbreviated
            if 'SUCCESSFUL' in status or 'COMPLETED' in status:
                st_txt, st_col = 'OK', C.green
            elif status:
                st_txt, st_col = 'FAIL', C.red
            else:
                st_txt, st_col = '—', C.fg2
            st_item = _item(st_txt, C_CENTER)
            st_item.setForeground(QBrush(QColor(st_col)))
            self._table.setItem(ri, _C_STATUS, st_item)

            # Method
            self._table.setItem(ri, _C_METHOD, _item(method))

            # nPar
            npar_item = _item(str(npar) if npar is not None else '—', R)
            self._table.setItem(ri, _C_NPAR, npar_item)

            # OFV
            self._table.setItem(ri, _C_OFV, _item(fmt_ofv(ofv), R))

            # ΔOFV
            if is_ref:
                dofv_item = _item('— ref —', C_CENTER)
                dofv_item.setForeground(QBrush(QColor(C.blue)))
            elif dofv is None:
                dofv_item = _item('—', R)
            else:
                dofv_item = _item(f'{dofv:+.3f}', R)
                dofv_item.setForeground(QBrush(QColor(
                    C.green if dofv < -3.84 else C.orange if dofv < 0 else C.red)))
            self._table.setItem(ri, _C_DOFV, dofv_item)

            # ΔAIC
            if is_ref:
                daic_item = _item('— ref —', C_CENTER)
                daic_item.setForeground(QBrush(QColor(C.blue)))
            elif daic is None:
                daic_item = _item('—', R)
            else:
                daic_item = _item(f'{daic:+.2f}', R)
                daic_item.setForeground(QBrush(QColor(C.green if daic < -2 else C.orange if daic < 0 else C.red)))
            self._table.setItem(ri, _C_DAIC, daic_item)

            # ΔBIC
            if is_ref:
                dbic_item = _item('— ref —', C_CENTER)
                dbic_item.setForeground(QBrush(QColor(C.blue)))
            elif dbic is None:
                dbic_item = _item('—', R)
            else:
                dbic_item = _item(f'{dbic:+.2f}', R)
                dbic_item.setForeground(QBrush(QColor(C.green if dbic < -2 else C.orange if dbic < 0 else C.red)))
            self._table.setItem(ri, _C_DBIC, dbic_item)

            # LRT p-value
            if is_ref:
                lrt_item = _item('', C_CENTER)
            elif lrt_method_mismatch:
                lrt_item = _item('N/A', C_CENTER)
                lrt_item.setForeground(QBrush(QColor(C.fg2)))
                lrt_item.setToolTip(
                    f'LRT invalid: methods differ ({ref_method} vs {method})')
            elif lrt_p is None:
                lrt_item = _item('—', R)
            else:
                lrt_item = _item(f'{lrt_p:.4f}' if lrt_p >= 0.0001 else '<0.0001', R)
                lrt_item.setForeground(QBrush(QColor(
                    C.green if lrt_p < 0.001 else C.orange if lrt_p < 0.05 else C.red)))
            self._table.setItem(ri, _C_LRT, lrt_item)

            # COV
            cov_txt = ('OK' if cov else ('FAIL' if cov is False else '—'))
            cov_col = C.green if cov else (C.red if cov is False else C.fg2)
            cov_item = _item(cov_txt, C_CENTER)
            cov_item.setForeground(QBrush(QColor(cov_col)))
            self._table.setItem(ri, _C_COV, cov_item)

            # CN
            cn_txt = f'{cn:.0f}' if cn else '—'
            cn_item = _item(cn_txt, R)
            if cn and cn > 10000:
                cn_item.setForeground(QBrush(QColor(C.red)))
            elif cn and cn > 1000:
                cn_item.setForeground(QBrush(QColor(C.orange)))
            self._table.setItem(ri, _C_CN, cn_item)

        self._table.setSortingEnabled(True)

    def _export_csv(self):
        ref = self._ref_model()
        stem = ref['stem'] if ref else 'workbench'
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Export workbench',
            str(HOME / f'workbench_{stem}.csv'), 'CSV files (*.csv)')
        if not dst:
            return
        ref_ofv    = ref.get('ofv')  if ref else None
        ref_aic    = ref.get('aic')  if ref else None
        ref_bic    = ref.get('bic')  if ref else None
        ref_npar   = ref.get('n_estimated_params') if ref else None
        ref_method = (ref.get('estimation_method', '') or '') if ref else ''
        with open(dst, 'w', newline='', encoding='utf-8') as f:
            w = _csv.writer(f)
            w.writerow(['model','status','method','n_par','ofv','delta_ofv',
                        'delta_aic','delta_bic','lrt_pval','cov','condition_number'])
            for m in self._models:
                is_ref = m['path'] == self._ref_path
                ofv = m.get('ofv'); aic = m.get('aic'); bic = m.get('bic')
                npar = m.get('n_estimated_params')
                method_csv = m.get('estimation_method', '') or ''
                dofv = (ofv - ref_ofv) if (ofv is not None and ref_ofv is not None) else None
                daic = (aic - ref_aic) if (aic is not None and ref_aic is not None) else None
                dbic = (bic - ref_bic) if (bic is not None and ref_bic is not None) else None
                dnpar = (npar - ref_npar) if (npar is not None and ref_npar is not None) else None
                method_mismatch = (
                    not is_ref and bool(method_csv) and bool(ref_method)
                    and method_csv.upper() != ref_method.upper()
                )
                lrt_p = None
                if not is_ref and not method_mismatch and dofv is not None and dnpar not in (None, 0):
                    lrt_p = _lrt_pval(dofv, dnpar) if dnpar > 0 else _lrt_pval(-dofv, -dnpar)
                w.writerow([
                    m['stem'],
                    m.get('minimization_message','')[:40],
                    method_csv,
                    npar if npar is not None else '',
                    ofv if ofv is not None else '',
                    f'{dofv:.4f}' if dofv is not None else '',
                    f'{daic:.4f}' if daic is not None else '',
                    f'{dbic:.4f}' if dbic is not None else '',
                    'method_mismatch' if method_mismatch else (f'{lrt_p:.6f}' if lrt_p is not None else ''),
                    'OK' if m.get('covariance_step') else ('FAIL' if m.get('covariance_step') is False else ''),
                    m.get('condition_number') or '',
                ])
