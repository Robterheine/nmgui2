import csv
import logging
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..app.config import load_settings, save_settings
from ..app.theme import T, monospace_font
from ..widgets.highlighter import NMHighlighter

_log = logging.getLogger(__name__)

_PRESET_EXTS    = ['mod', 'ctl', 'lst', 'tab', 'csv', 'ext', 'cov', 'cor', 'phi']
_TABLE_EXTS     = {'csv', 'tab'}
_HIGHLIGHT_EXTS = {'mod', 'ctl'}
_MAX_ROWS       = 5000


def _read_nonmem_table(path: Path):
    """Parse a NONMEM TABLE file. Returns (headers, rows)."""
    lines = path.read_text('utf-8', errors='replace').splitlines()
    if not lines:
        return [], []
    start = 1 if lines[0].strip().upper().startswith('TABLE NO') else 0
    if start >= len(lines):
        return [], []
    headers = lines[start].split()
    rows = []
    for line in lines[start + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper().startswith('TABLE NO'):
            break
        rows.append(stripped.split())
    return headers, rows


def _read_csv_file(path: Path):
    """Read CSV with auto-detected delimiter. Returns (headers, rows, delimiter)."""
    content = path.read_text('utf-8', errors='replace')
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(content[:4096], delimiters=',;\t')
        delim = dialect.delimiter
    except csv.Error:
        delim = ','
    lines = [ln for ln in content.splitlines() if ln.strip()]
    if not lines:
        return [], [], delim
    rows = list(csv.reader(lines, delimiter=delim))
    if not rows:
        return [], [], delim
    return rows[0], rows[1:], delim


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f'{n} B'
    if n < 1_048_576:
        return f'{n / 1024:.1f} KB'
    return f'{n / 1_048_576:.1f} MB'


class FileExplorerTab(QWidget):
    status_msg = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._directory     = None
        self._current_file  = None
        self._current_delim = ','
        self._highlighter   = None
        self._ext_checkboxes: dict[str, QCheckBox] = {}
        self._custom_exts:    list[str] = []
        self._build_ui()
        self._load_filter_state()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_filter_panel())
        splitter.addWidget(self._build_file_list_panel())
        splitter.addWidget(self._build_content_panel())
        splitter.setSizes([160, 240, 600])
        splitter.setStretchFactor(2, 1)
        root.addWidget(splitter)

    def _build_filter_panel(self):
        w = QWidget()
        w.setObjectName('feFilterPanel')
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 10, 8, 8)
        v.setSpacing(3)

        hdr = QLabel('Extensions')
        f = hdr.font(); f.setPointSize(9); f.setBold(True); hdr.setFont(f)
        v.addWidget(hdr)
        v.addSpacing(4)

        for ext in _PRESET_EXTS:
            cb = QCheckBox(f'.{ext}')
            cb.setChecked(True)
            cb.toggled.connect(self._on_filter_changed)
            self._ext_checkboxes[ext] = cb
            v.addWidget(cb)

        v.addSpacing(8)

        custom_hdr = QLabel('Custom:')
        f2 = custom_hdr.font(); f2.setPointSize(8); custom_hdr.setFont(f2)
        v.addWidget(custom_hdr)

        add_row = QHBoxLayout()
        add_row.setSpacing(4)
        self._custom_ext_edit = QLineEdit()
        self._custom_ext_edit.setPlaceholderText('ext')
        self._custom_ext_edit.setFixedHeight(22)
        self._custom_ext_edit.returnPressed.connect(self._add_custom_ext)
        add_row.addWidget(self._custom_ext_edit)
        add_btn = QPushButton('+')
        add_btn.setFixedWidth(26)
        add_btn.setFixedHeight(22)
        add_btn.clicked.connect(self._add_custom_ext)
        add_row.addWidget(add_btn)
        v.addLayout(add_row)

        self._custom_cb_container = QVBoxLayout()
        self._custom_cb_container.setSpacing(2)
        v.addLayout(self._custom_cb_container)

        v.addStretch()
        return w

    def _build_file_list_panel(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._file_table = QTableWidget()
        self._file_table.setColumnCount(3)
        self._file_table.setHorizontalHeaderLabels(['Name', 'Size', 'Modified'])
        self._file_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._file_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self._file_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents)
        self._file_table.verticalHeader().setVisible(False)
        self._file_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._file_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._file_table.setSortingEnabled(True)
        self._file_table.setShowGrid(False)
        self._file_table.setAlternatingRowColors(True)
        self._file_table.verticalHeader().setDefaultSectionSize(24)
        self._file_table.itemSelectionChanged.connect(self._on_file_selected)

        v.addWidget(self._file_table)
        return w

    def _build_content_panel(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Toolbar
        tb = QWidget()
        tb.setObjectName('feToolbar')
        tb.setFixedHeight(32)
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(8, 4, 8, 4)
        tl.setSpacing(6)

        self._content_title = QLabel('No file selected')
        f = self._content_title.font(); f.setPointSize(9); self._content_title.setFont(f)
        tl.addWidget(self._content_title, 1)

        self._find_edit = QLineEdit()
        self._find_edit.setPlaceholderText('Find...')
        self._find_edit.setFixedHeight(22)
        self._find_edit.setMinimumWidth(100)
        self._find_edit.setMaximumWidth(180)
        self._find_edit.textChanged.connect(self._find_in_text)
        self._find_edit.setVisible(False)
        tl.addWidget(self._find_edit)

        self._edit_btn = QPushButton('Edit')
        self._edit_btn.setCheckable(True)
        self._edit_btn.setFixedHeight(22)
        self._edit_btn.setFixedWidth(44)
        self._edit_btn.setVisible(False)
        self._edit_btn.toggled.connect(self._toggle_edit_mode)
        tl.addWidget(self._edit_btn)

        self._save_btn = QPushButton('Save')
        self._save_btn.setFixedHeight(22)
        self._save_btn.setFixedWidth(44)
        self._save_btn.setVisible(False)
        self._save_btn.clicked.connect(self._save_file)
        tl.addWidget(self._save_btn)

        self._discard_btn = QPushButton('Discard')
        self._discard_btn.setFixedHeight(22)
        self._discard_btn.setFixedWidth(56)
        self._discard_btn.setVisible(False)
        self._discard_btn.clicked.connect(self._discard_edits)
        tl.addWidget(self._discard_btn)

        v.addWidget(tb)

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setObjectName('hairlineSep')
        v.addWidget(sep)

        # Stacked: index 0 = text, index 1 = table
        self._content_stack = QStackedWidget()

        self._text_view = QPlainTextEdit()
        self._text_view.setReadOnly(True)
        self._text_view.setFont(monospace_font(11))
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Base, QColor(T('bg2')))
        pal.setColor(QPalette.ColorRole.Text, QColor(T('fg')))
        self._text_view.setPalette(pal)

        self._table_view = QTableWidget()
        self._table_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table_view.setAlternatingRowColors(True)
        self._table_view.setSortingEnabled(True)
        self._table_view.setShowGrid(True)
        self._table_view.verticalHeader().setDefaultSectionSize(22)
        self._table_view.verticalHeader().setVisible(False)
        self._table_view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)

        self._content_stack.addWidget(self._text_view)   # 0
        self._content_stack.addWidget(self._table_view)  # 1
        v.addWidget(self._content_stack, 1)

        self._row_notice = QLabel('')
        self._row_notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._row_notice.setObjectName('mutedLabel')
        self._row_notice.setVisible(False)
        v.addWidget(self._row_notice)

        return w

    # ── Public API ────────────────────────────────────────────────────────────

    def load_directory(self, path: str | None):
        self._directory = path
        self._current_file = None
        self._content_title.setText('No file selected')
        self._text_view.setPlainText('')
        self._table_view.clearContents()
        self._table_view.setRowCount(0)
        self._edit_btn.setChecked(False)
        self._edit_btn.setVisible(False)
        self._save_btn.setVisible(False)
        self._discard_btn.setVisible(False)
        self._find_edit.setVisible(False)
        self._row_notice.setVisible(False)
        self._rebuild_file_list()

    # ── Extension filter ──────────────────────────────────────────────────────

    def _active_exts(self) -> set:
        return {ext.lower() for ext, cb in self._ext_checkboxes.items() if cb.isChecked()}

    def _on_filter_changed(self):
        self._save_filter_state()
        self._rebuild_file_list()

    def _add_custom_ext(self):
        raw = self._custom_ext_edit.text().strip().lstrip('.')
        if not raw or raw in self._ext_checkboxes:
            return
        self._custom_exts.append(raw)
        self._custom_ext_edit.clear()

        cb = QCheckBox(f'.{raw}')
        cb.setChecked(True)
        cb.toggled.connect(self._on_filter_changed)
        self._ext_checkboxes[raw] = cb

        row_w = QWidget()
        rl = QHBoxLayout(row_w)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(2)
        rl.addWidget(cb)
        rm_btn = QPushButton('-')
        rm_btn.setFixedWidth(22)
        rm_btn.setFixedHeight(20)
        rm_btn.clicked.connect(lambda _, e=raw: self._remove_custom_ext(e))
        rl.addWidget(rm_btn)
        self._custom_cb_container.addWidget(row_w)

        self._save_filter_state()
        self._rebuild_file_list()

    def _remove_custom_ext(self, ext: str):
        if ext in self._custom_exts:
            self._custom_exts.remove(ext)
        cb = self._ext_checkboxes.pop(ext, None)
        if cb:
            # Find and remove the parent row widget
            for i in range(self._custom_cb_container.count()):
                item = self._custom_cb_container.itemAt(i)
                w = item.widget() if item else None
                if w and w.layout():
                    for j in range(w.layout().count()):
                        child = w.layout().itemAt(j)
                        if child and child.widget() is cb:
                            w.deleteLater()
                            break
        self._save_filter_state()
        self._rebuild_file_list()

    # ── File list ─────────────────────────────────────────────────────────────

    def _rebuild_file_list(self):
        self._file_table.setSortingEnabled(False)
        self._file_table.setRowCount(0)
        if not self._directory:
            return
        d = Path(self._directory)
        if not d.is_dir():
            return
        active = self._active_exts()
        files = sorted(
            (f for f in d.iterdir()
             if f.is_file() and f.suffix.lstrip('.').lower() in active),
            key=lambda f: f.name.lower(),
        )
        self._file_table.setRowCount(len(files))
        for row, f in enumerate(files):
            stat = f.stat()
            name_it = QTableWidgetItem(f.name)
            name_it.setData(Qt.ItemDataRole.UserRole, str(f))
            name_it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

            size_it = QTableWidgetItem(_fmt_size(stat.st_size))
            size_it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            size_it.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            mtime = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
            mod_it = QTableWidgetItem(mtime)
            mod_it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

            self._file_table.setItem(row, 0, name_it)
            self._file_table.setItem(row, 1, size_it)
            self._file_table.setItem(row, 2, mod_it)
        self._file_table.setSortingEnabled(True)

    # ── File selection / content viewer ──────────────────────────────────────

    def _on_file_selected(self):
        row = self._file_table.currentRow()
        if row < 0:
            return
        item = self._file_table.item(row, 0)
        if not item:
            return
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        p = Path(path_str)
        if p == self._current_file:
            return
        if self._edit_btn.isChecked():
            reply = QMessageBox.question(
                self, 'Unsaved changes',
                'You have unsaved changes. Discard and open new file?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._edit_btn.setChecked(False)
        self._current_file = p
        self._load_file(p)

    def _load_file(self, path: Path):
        ext = path.suffix.lstrip('.').lower()
        self._content_title.setText(path.name)
        self._row_notice.setVisible(False)
        if ext in _TABLE_EXTS:
            self._load_table_file(path, ext)
        else:
            self._load_text_file(path, ext)

    def _load_text_file(self, path: Path, ext: str):
        try:
            text = path.read_text('utf-8', errors='replace')
        except Exception as e:
            self._content_stack.setCurrentIndex(0)
            self._text_view.setPlainText(f'Error reading file:\n{e}')
            self._find_edit.setVisible(False)
            self._edit_btn.setVisible(False)
            return

        self._content_stack.setCurrentIndex(0)
        self._text_view.setReadOnly(True)
        self._text_view.setPlainText(text)

        if ext in _HIGHLIGHT_EXTS:
            if (self._highlighter is None
                    or self._highlighter.document() is not self._text_view.document()):
                self._highlighter = NMHighlighter(self._text_view.document())
        else:
            if self._highlighter is not None:
                self._highlighter.setDocument(None)
                self._highlighter = None

        self._find_edit.setVisible(True)
        self._find_edit.clear()
        self._edit_btn.setVisible(True)
        self._save_btn.setVisible(False)
        self._discard_btn.setVisible(False)

    def _load_table_file(self, path: Path, ext: str):
        try:
            if ext == 'tab':
                headers, rows = _read_nonmem_table(path)
                self._current_delim = None
            else:
                headers, rows, self._current_delim = _read_csv_file(path)
        except Exception as e:
            self._content_stack.setCurrentIndex(0)
            self._text_view.setPlainText(f'Error reading file:\n{e}')
            self._find_edit.setVisible(True)
            self._edit_btn.setVisible(False)
            self._save_btn.setVisible(False)
            self._discard_btn.setVisible(False)
            return

        truncated = len(rows) > _MAX_ROWS
        display_rows = rows[:_MAX_ROWS]

        self._table_view.setSortingEnabled(False)
        self._table_view.clearContents()
        self._table_view.setColumnCount(len(headers))
        self._table_view.setHorizontalHeaderLabels(headers)
        self._table_view.setRowCount(len(display_rows))

        for r, row in enumerate(display_rows):
            for c in range(min(len(row), len(headers))):
                it = QTableWidgetItem(row[c])
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self._table_view.setItem(r, c, it)

        self._table_view.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self._table_view.setSortingEnabled(True)
        self._content_stack.setCurrentIndex(1)

        if truncated:
            self._row_notice.setText(
                f'Showing first {_MAX_ROWS:,} of {len(rows):,} rows')
            self._row_notice.setVisible(True)

        self._find_edit.setVisible(False)
        self._edit_btn.setVisible(True)
        self._save_btn.setVisible(False)
        self._discard_btn.setVisible(False)

    # ── Edit / save / discard ─────────────────────────────────────────────────

    def _toggle_edit_mode(self, checked: bool):
        if self._content_stack.currentIndex() == 0:
            self._text_view.setReadOnly(not checked)
        else:
            trigger = (QAbstractItemView.EditTrigger.DoubleClicked
                       if checked else QAbstractItemView.EditTrigger.NoEditTriggers)
            self._table_view.setEditTriggers(trigger)
        self._save_btn.setVisible(checked)
        self._discard_btn.setVisible(checked)

    def _save_file(self):
        if not self._current_file:
            return
        try:
            if self._content_stack.currentIndex() == 0:
                self._current_file.write_text(
                    self._text_view.toPlainText(), 'utf-8')
            else:
                if self._current_file.suffix.lower() == '.tab':
                    QMessageBox.information(
                        self, 'Read-only',
                        '.tab files are NONMEM output — direct editing is not supported.')
                    return
                headers = [
                    self._table_view.horizontalHeaderItem(c).text()
                    for c in range(self._table_view.columnCount())
                ]
                out_rows = [headers]
                for r in range(self._table_view.rowCount()):
                    row = []
                    for c in range(self._table_view.columnCount()):
                        it = self._table_view.item(r, c)
                        row.append(it.text() if it else '')
                    out_rows.append(row)
                delim = self._current_delim or ','
                with self._current_file.open('w', newline='', encoding='utf-8') as fh:
                    writer = csv.writer(fh, delimiter=delim)
                    writer.writerows(out_rows)
            self.status_msg.emit(f'Saved {self._current_file.name}')
            self._edit_btn.setChecked(False)
        except Exception as e:
            QMessageBox.critical(self, 'Save error', str(e))

    def _discard_edits(self):
        self._edit_btn.setChecked(False)
        if self._current_file:
            self._load_file(self._current_file)

    # ── Find (text view only) ─────────────────────────────────────────────────

    def _find_in_text(self, term: str):
        if not term:
            self._text_view.setExtraSelections([])
            return
        fmt = QTextCharFormat()
        fmt.setBackground(QColor('#f0c040'))
        fmt.setForeground(QColor('#000000'))
        selections = []
        doc = self._text_view.document()
        cursor = QTextCursor(doc)
        while True:
            cursor = doc.find(term, cursor)
            if cursor.isNull():
                break
            sel = QPlainTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = fmt
            selections.append(sel)
        self._text_view.setExtraSelections(selections)
        if selections:
            self._text_view.setTextCursor(selections[0].cursor)

    # ── Settings persistence ──────────────────────────────────────────────────

    def _save_filter_state(self):
        s = load_settings()
        s['file_explorer_checked_exts'] = [
            ext for ext, cb in self._ext_checkboxes.items() if cb.isChecked()
        ]
        s['file_explorer_custom_exts'] = self._custom_exts[:]
        save_settings(s)

    def _load_filter_state(self):
        s = load_settings()
        checked = s.get('file_explorer_checked_exts')
        if checked is not None:
            checked_set = set(checked)
            for ext, cb in self._ext_checkboxes.items():
                cb.setChecked(ext in checked_set)
        for ext in s.get('file_explorer_custom_exts', []):
            self._custom_ext_edit.setText(ext)
            self._add_custom_ext()
