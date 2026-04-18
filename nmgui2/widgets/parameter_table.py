import math
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor

from ..app.theme import C, T
from ..app.format import fmt_num, fmt_rse
from ..app.model_io import _align_param_names, _parse_param_names_from_mod
from ..app.html_report import generate_html_report
from ..app.constants import HOME


class ParameterTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = None
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)
        # Toolbar
        toolbar = QWidget(); toolbar.setFixedHeight(34)
        tl = QHBoxLayout(toolbar); tl.setContentsMargins(4,4,4,4); tl.setSpacing(6)
        tl.addStretch()
        self.open_report_btn = QPushButton('Open Report')
        self.open_report_btn.setToolTip('Generate run report and open in browser')
        self.open_report_btn.setFixedHeight(26); self.open_report_btn.setEnabled(False)
        self.save_report_btn = QPushButton('Save Report…')
        self.save_report_btn.setToolTip('Save run report as HTML file')
        self.save_report_btn.setFixedHeight(26); self.save_report_btn.setEnabled(False)
        self.csv_btn = QPushButton('Export CSV')
        self.csv_btn.setToolTip('Export parameter table to CSV')
        self.csv_btn.setFixedHeight(26); self.csv_btn.setEnabled(False)
        self.open_report_btn.clicked.connect(self._open_report)
        self.save_report_btn.clicked.connect(self._save_report)
        self.csv_btn.clicked.connect(self._export_csv)
        tl.addWidget(self.open_report_btn); tl.addWidget(self.save_report_btn)
        tl.addWidget(self.csv_btn)
        v.addWidget(toolbar)
        self.table = QTableWidget(0,8)
        self.table.setHorizontalHeaderLabels(['Param','Name','Estimate','SE','RSE%','Shrink%','Etabar','Units'])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        # Sensible initial widths — all freely draggable
        hh.resizeSection(0, 85)   # Param
        hh.resizeSection(1, 140)  # Name — wide but draggable
        hh.resizeSection(2, 85)   # Estimate
        hh.resizeSection(3, 65)   # SE
        hh.resizeSection(4, 55)   # RSE%
        hh.resizeSection(5, 55)   # Shrink%
        hh.resizeSection(6, 55)   # Etabar p
        hh.resizeSection(7, 50)   # Units
        hh.setStretchLastSection(False)
        hh.setMinimumSectionSize(40)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        v.addWidget(self.table)

    def _open_report(self):
        if not self._model: return
        import tempfile, webbrowser
        html = generate_html_report(_align_param_names(self._model))
        tmp = tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8')
        tmp.write(html); tmp.flush(); tmp_name = tmp.name; tmp.close()
        webbrowser.open(f'file://{tmp_name}')
        # Schedule cleanup after browser has had time to read the file
        QTimer.singleShot(30000, lambda: Path(tmp_name).unlink(missing_ok=True))

    def _save_report(self):
        if not self._model: return
        stem = self._model.get('stem','report')
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Save report', str(HOME / f'{stem}_report.html'),
            'HTML files (*.html)')
        if not dst: return
        Path(dst).write_text(generate_html_report(_align_param_names(self._model)), encoding='utf-8')
        if QMessageBox.question(self,'Saved',f'Report saved.\nOpen in browser?',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            import webbrowser; webbrowser.open(f'file://{dst}')

    def _export_csv(self):
        if not self._model: return
        stem = self._model.get('stem','model')
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Export parameters', str(HOME / f'{stem}_params.csv'),
            'CSV files (*.csv)')
        if not dst: return
        import csv as _csv
        rows = []
        for block, ests, ses, names, units, fixed in [
            ('THETA', self._model.get('thetas',[]), self._model.get('theta_ses',[]),
             self._model.get('theta_names',[]), self._model.get('theta_units',[]),
             self._model.get('theta_fixed',[])),
            ('OMEGA', self._model.get('omegas',[]), self._model.get('omega_ses',[]),
             self._model.get('omega_names',[]), self._model.get('omega_units',[]),
             self._model.get('omega_fixed',[])),
            ('SIGMA', self._model.get('sigmas',[]), self._model.get('sigma_ses',[]),
             self._model.get('sigma_names',[]), self._model.get('sigma_units',[]),
             self._model.get('sigma_fixed',[])),
        ]:
            for i, est in enumerate(ests):
                se  = ses[i]   if i < len(ses)   else None
                nm  = names[i] if i < len(names) else ''
                un  = units[i] if i < len(units) else ''
                fx  = fixed[i] if i < len(fixed) else False
                rse = f'{abs(se/est)*100:.2f}' if se and est and abs(est)>1e-12 else ''
                rows.append([f'{block}({i+1})', nm,
                              fmt_num(est), fmt_num(se) if se is not None else '',
                              rse, un, 'FIXED' if fx else ''])
        with open(dst, 'w', newline='', encoding='utf-8') as f:
            w = _csv.writer(f)
            w.writerow(['Parameter','Name','Estimate','SE','RSE_pct','Units','Fixed'])
            w.writerows(rows)
        self.parent().parent().status_msg.emit(f'Parameters exported: {Path(dst).name}') if hasattr(self,'parent') else None

    def load(self, model, parent_model=None):
        self._model = model if model.get('has_run') else None
        has = self._model is not None
        self.open_report_btn.setEnabled(has)
        self.save_report_btn.setEnabled(has)
        self.csv_btn.setEnabled(has)
        self.table.setRowCount(0)

        # Get shrinkage and etabar arrays
        eta_shr = model.get('eta_shrinkage', [])
        eps_shr = model.get('eps_shrinkage', [])
        etabar_pval = model.get('etabar_pval', [])

        # Build parent parameter lookup for comparison
        parent_params = {}
        if parent_model and parent_model.get('has_run'):
            for block, key in [('THETA', 'thetas'), ('OMEGA', 'omegas'), ('SIGMA', 'sigmas')]:
                for i, val in enumerate(parent_model.get(key, [])):
                    parent_params[f'{block}({i+1})'] = val

        blocks = [
            ('THETA', model.get('thetas',[]), model.get('theta_ses',[]),
             model.get('theta_names',[]), model.get('theta_units',[]), model.get('theta_fixed',[]), [], []),
            ('OMEGA', model.get('omegas',[]), model.get('omega_ses',[]),
             model.get('omega_names',[]), model.get('omega_units',[]), model.get('omega_fixed',[]), eta_shr, etabar_pval),
            ('SIGMA', model.get('sigmas',[]), model.get('sigma_ses',[]),
             model.get('sigma_names',[]), model.get('sigma_units',[]), model.get('sigma_fixed',[]), eps_shr, []),
        ]
        rows = []
        for block, ests, ses, names, units, fixed, shrinkage, etabar in blocks:
            for i, est in enumerate(ests):
                se   = ses[i] if i < len(ses) else None
                nm   = names[i] if i < len(names) else ''
                un   = units[i] if i < len(units) else ''
                fx   = fixed[i] if i < len(fixed) else False
                shr  = shrinkage[i] if i < len(shrinkage) else None
                ebp  = etabar[i] if i < len(etabar) else None
                param_key = f'{block}({i+1})'
                parent_val = parent_params.get(param_key)
                rows.append((param_key, nm, est, fmt_num(est), fmt_num(se) if se is not None else '...',
                            fmt_rse(est,se), shr, ebp, un, fx, parent_val))
        self.table.setRowCount(len(rows))
        R = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        L = Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter
        grey = QBrush(QColor(C.fg2))
        changed_color = QColor('#4c8aff')  # Blue for changed parameters

        for row, (lbl, nm, est_raw, est, se, rse, shr, ebp, un, fx, parent_val) in enumerate(rows):
            # Check if parameter changed from parent
            changed_from_parent = False
            parent_tooltip = None
            if parent_val is not None and est_raw is not None:
                # Consider changed if differs by more than 0.1% or absolute diff > 1e-6
                if abs(est_raw) > 1e-10:
                    pct_diff = abs(est_raw - parent_val) / abs(est_raw) * 100
                    changed_from_parent = pct_diff > 0.1
                else:
                    changed_from_parent = abs(est_raw - parent_val) > 1e-6
                if changed_from_parent:
                    parent_tooltip = f'Changed from {fmt_num(parent_val)} in parent model'

            # Shrinkage text and color
            if shr is not None:
                shr_txt = f'{shr:.1f}'
                if shr < 20:
                    shr_color = QColor(C.green)
                elif shr < 30:
                    shr_color = QColor(C.orange)
                else:
                    shr_color = QColor(C.red)
            else:
                shr_txt = ''
                shr_color = None

            # Etabar p-value text and color
            if ebp is not None:
                ebp_txt = f'{ebp:.3f}' if ebp >= 0.001 else '<.001'
                if ebp < 0.01:
                    ebp_color = QColor(C.red)
                elif ebp < 0.05:
                    ebp_color = QColor(C.orange)
                else:
                    ebp_color = None
            else:
                ebp_txt = ''
                ebp_color = None

            for col, (txt, align) in enumerate([(lbl,L),(nm,L),(est,R),(se,R),(rse,R),(shr_txt,R),(ebp_txt,R),(un,L)]):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(align)
                if fx:
                    item.setForeground(grey)
                    item.setToolTip('FIXED')
                # Highlight changed estimate (col 2 = Estimate)
                elif col == 2 and changed_from_parent:
                    item.setText(f'* {est}')
                    item.setForeground(QBrush(changed_color))
                    item.setToolTip(parent_tooltip)
                # Apply shrinkage color
                elif col == 5 and shr_color:
                    item.setForeground(QBrush(shr_color))
                    if shr is not None and shr >= 30:
                        item.setToolTip(f'High shrinkage ({shr:.1f}%) — parameter poorly estimated')
                    elif shr is not None and shr >= 20:
                        item.setToolTip(f'Moderate shrinkage ({shr:.1f}%)')
                # Apply etabar color
                elif col == 6 and ebp is not None:
                    if ebp_color:
                        item.setForeground(QBrush(ebp_color))
                    if ebp < 0.01:
                        item.setToolTip(f'Significant etabar (p={ebp:.4f}) — systematic bias in random effect')
                    elif ebp < 0.05:
                        item.setToolTip(f'Marginally significant etabar (p={ebp:.3f})')
                self.table.setItem(row, col, item)
