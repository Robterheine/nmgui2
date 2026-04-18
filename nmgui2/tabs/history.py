import sys, json
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
                              QLineEdit, QPlainTextEdit, QMessageBox)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont

from ..app.theme import C, T
from ..app.constants import RUNS_FILE


def _load_runs():
    if RUNS_FILE.exists():
        try:
            return json.loads(RUNS_FILE.read_text('utf-8'))
        except Exception:
            pass
    return []


def _save_runs(runs):
    tmp = RUNS_FILE.with_suffix('.tmp')
    try:
        tmp.write_text(json.dumps(runs, indent=2, default=str), encoding='utf-8')
        tmp.replace(RUNS_FILE)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


class RunHistoryTab(QWidget):
    """Displays all recorded NONMEM runs from runs.json."""

    COLS = ['Model', 'Tool', 'Status', 'Started', 'Duration', 'Directory']

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self); v.setContentsMargins(16, 12, 16, 12); v.setSpacing(8)

        # Toolbar
        tb = QHBoxLayout()
        tb.addWidget(QLabel('Run History'))
        tb.addStretch()
        self._filter = QLineEdit(); self._filter.setPlaceholderText('Filter by model name or tool…')
        self._filter.setFixedWidth(280); self._filter.textChanged.connect(self._apply_filter)
        refresh_btn = QPushButton('Refresh'); refresh_btn.setFixedHeight(26)
        refresh_btn.clicked.connect(self.load)
        clear_btn = QPushButton('Clear history'); clear_btn.setFixedHeight(26)
        clear_btn.clicked.connect(self._clear)
        tb.addWidget(self._filter); tb.addWidget(refresh_btn); tb.addWidget(clear_btn)
        v.addLayout(tb)

        # Table
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.resizeSection(1, 90)
        hh.resizeSection(2, 90)
        hh.resizeSection(3, 145)
        hh.resizeSection(4, 75)
        hh.resizeSection(5, 200)
        self.table.setMinimumHeight(200)
        v.addWidget(self.table, 1)

        # Command preview
        sep = QWidget(); sep.setFixedHeight(1)
        sep.setStyleSheet(f'background:{C.border};'); v.addWidget(sep)
        cmd_lbl = QLabel('Command')
        cmd_lbl.setStyleSheet(f'color:{C.fg2};font-size:11px;font-weight:700;text-transform:uppercase;')
        v.addWidget(cmd_lbl)
        self._cmd_view = QPlainTextEdit()
        self._cmd_view.setReadOnly(True)
        self._cmd_view.setFixedHeight(52)
        self._cmd_view.setFont(QFont('Menlo' if sys.platform == 'darwin' else 'Consolas', 11))
        self._cmd_view.setPlaceholderText('Select a row to see the full command')
        v.addWidget(self._cmd_view)

        self.table.currentCellChanged.connect(lambda row, _, __, ___: self._on_row(row))
        self._runs = []; self._filtered_runs = []
        self.load()

    def load(self):
        self._runs = _load_runs()
        self._apply_filter(self._filter.text())

    def _apply_filter(self, text=''):
        term = text.strip().lower()
        self.table.setRowCount(0)
        self._filtered_runs = []  # track what's visible for _on_row
        R = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        L = Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter
        for run in self._runs:
            name = run.get('run_name', ''); tool = run.get('tool', '')
            if term and term not in name.lower() and term not in tool.lower():
                continue
            self._filtered_runs.append(run)
        for run in self._filtered_runs:
            name = run.get('run_name', ''); tool = run.get('tool', '')
            status = run.get('status', 'running')
            finished = run.get('finished')
            # Normalise legacy statuses from before the status-fix
            if status == 'finished' or (status == 'running' and finished):
                status_display = 'ok'; status_col = QColor(C.green)
            elif status == 'ok':
                status_display = 'ok'; status_col = QColor(C.green)
            elif 'fail' in str(status):
                status_display = status; status_col = QColor(C.red)
            elif status == 'running' and not finished:
                status_display = 'unknown'; status_col = QColor(C.fg2)
            else:
                status_display = status; status_col = QColor(C.fg2)
            started = run.get('started', '')
            # Format started timestamp
            try:
                dt = datetime.fromisoformat(started)
                started_fmt = dt.strftime('%Y-%m-%d  %H:%M:%S')
            except Exception:
                started_fmt = started[:19] if started else '—'
            # Duration
            duration = '—'
            try:
                if finished and started:
                    s = datetime.fromisoformat(started); f = datetime.fromisoformat(finished)
                    secs = int((f - s).total_seconds())
                    duration = f'{secs//60}m {secs%60}s' if secs >= 60 else f'{secs}s'
                elif status == 'running' and not finished:
                    duration = '…'
            except Exception:
                pass
            directory = str(Path(run.get('working_dir', run.get('model', ''))).name)
            row = self.table.rowCount(); self.table.insertRow(row)
            cells = [(name, L), (tool, L), (status_display, L), (started_fmt, L), (duration, R), (directory, L)]
            for ci, (txt, align) in enumerate(cells):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(align)
                if ci == 2:
                    item.setForeground(QBrush(status_col))
                self.table.setItem(row, ci, item)
        self.table.setRowCount(self.table.rowCount())

    def _on_row(self, row):
        if 0 <= row < len(getattr(self, '_filtered_runs', [])):
            self._cmd_view.setPlainText(self._filtered_runs[row].get('command', ''))

    def _clear(self):
        if QMessageBox.question(self, 'Clear history',
            'Delete all run history? This cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            _save_runs([])
            self.load()
