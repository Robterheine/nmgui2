import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QFrame, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt

from ..app.theme import C, T
from ..app.config import load_settings
from ..app.constants import HOME


class RunRecordDialog(QDialog):
    """Dialog to display a run record for audit purposes."""
    def __init__(self, record, parent=None):
        super().__init__(parent)
        self.record = record
        self.setWindowTitle(f'Run Record: {record.get("model_stem", "unknown")}')
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)

        v = QVBoxLayout(self); v.setSpacing(12); v.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QLabel(f'<b style="font-size:16px;">{record.get("model_stem", "unknown")}</b>')
        v.addWidget(header)

        # Info grid
        info = QGridLayout(); info.setSpacing(8)
        row = 0

        def add_row(label, value):
            nonlocal row
            lbl = QLabel(f'<b>{label}:</b>')
            lbl.setStyleSheet(f'color:{T("fg2")};')
            val = QLabel(str(value) if value else '—')
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            val.setWordWrap(True)
            info.addWidget(lbl, row, 0, Qt.AlignmentFlag.AlignTop)
            info.addWidget(val, row, 1)
            row += 1

        add_row('Run ID', record.get('run_id'))
        add_row('Status', record.get('status'))
        add_row('Started', record.get('started'))
        add_row('Completed', record.get('completed'))
        if record.get('duration_seconds'):
            mins, secs = divmod(record['duration_seconds'], 60)
            add_row('Duration', f'{mins}m {secs}s')
        add_row('Tool', record.get('tool'))
        add_row('NONMEM version', record.get('nonmem_version'))
        add_row('PsN version', record.get('psn_version'))
        add_row('NMGUI version', record.get('nmgui_version'))

        v.addLayout(info)

        # Separator
        sep1 = QFrame(); sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet(f'color:{T("border")};'); v.addWidget(sep1)

        # Results section
        results_lbl = QLabel('<b>Results</b>')
        v.addWidget(results_lbl)

        results = QGridLayout(); results.setSpacing(8)
        row = 0

        def add_result(label, value):
            nonlocal row
            lbl = QLabel(f'{label}:')
            lbl.setStyleSheet(f'color:{T("fg2")};')
            val = QLabel(str(value) if value is not None else '—')
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            results.addWidget(lbl, row, 0)
            results.addWidget(val, row, 1)
            row += 1

        add_result('OFV', f'{record.get("ofv"):.4f}' if record.get('ofv') is not None else None)
        add_result('Minimization', 'Successful' if record.get('minimization_successful') else
                   ('Failed' if record.get('minimization_successful') is False else None))
        add_result('Covariance step', 'Yes' if record.get('covariance_step') else
                   ('No' if record.get('covariance_step') is False else None))

        warnings = record.get('warnings', [])
        if warnings:
            add_result('Warnings', ', '.join(warnings))

        v.addLayout(results)

        # Separator
        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f'color:{T("border")};'); v.addWidget(sep2)

        # Hashes section
        hashes_lbl = QLabel('<b>File Hashes</b>')
        v.addWidget(hashes_lbl)

        hashes = QGridLayout(); hashes.setSpacing(4)
        hashes.addWidget(QLabel('Control stream:'), 0, 0)
        cs_hash = QLabel(record.get('control_stream_hash', '—'))
        cs_hash.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cs_hash.setStyleSheet('font-family: monospace; font-size: 11px;')
        hashes.addWidget(cs_hash, 0, 1)

        hashes.addWidget(QLabel('Data file:'), 1, 0)
        df_hash = QLabel(record.get('data_file_hash', '—'))
        df_hash.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        df_hash.setStyleSheet('font-family: monospace; font-size: 11px;')
        hashes.addWidget(df_hash, 1, 1)

        if record.get('data_file'):
            hashes.addWidget(QLabel('Data file name:'), 2, 0)
            hashes.addWidget(QLabel(record.get('data_file')), 2, 1)

        out_hashes = record.get('output_hashes', {})
        r = 3
        for ext, h in out_hashes.items():
            hashes.addWidget(QLabel(f'{ext.upper()} hash:'), r, 0)
            h_lbl = QLabel(h)
            h_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            h_lbl.setStyleSheet('font-family: monospace; font-size: 11px;')
            hashes.addWidget(h_lbl, r, 1)
            r += 1

        v.addLayout(hashes)
        v.addStretch()

        # Buttons
        btn_row = QHBoxLayout()
        export_btn = QPushButton('Export JSON')
        export_btn.clicked.connect(self._export_json)
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(export_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        v.addLayout(btn_row)

    def _export_json(self):
        stem = self.record.get('model_stem', 'record')
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Export Run Record',
            str(HOME / f'{stem}_run_record.json'),
            'JSON files (*.json)')
        if not dst: return
        Path(dst).write_text(json.dumps(self.record, indent=2, default=str), encoding='utf-8')
        QMessageBox.information(self, 'Exported', f'Run record exported to:\n{dst}')
