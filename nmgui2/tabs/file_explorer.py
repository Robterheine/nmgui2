"""
File-browser tab — two-pane layout with subfolder navigation.

Layout
------
[←]  ABIRATERON / run104        [All] [.mod] [.lst] … [ext…]
──────────────────────────────────────────────────────────────────────────────
[   file list (folders first)  ] | [          content preview              ]

Behaviour
---------
- Default: show ALL files and ALL subfolders in the current directory.
- Filter pills (All / .mod / .lst / …): selecting one or more extensions
  shows only matching files; folders are always shown regardless of filter.
- Single-click file  → load preview in right pane.
- Double-click folder → navigate into it (push to back-stack).
- Double-click file   → open with the OS default application.
- ← back button       → return to the previous directory.
- Inline ext field: typing an extension (with or without leading dot) overrides
  the pill selection for a quick temporary filter; clears when leaving the tab.
"""

import csv
import logging
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor, QDesktopServices, QPalette, QTextCharFormat, QTextCursor,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QStackedWidget, QTableWidget, QTableWidgetItem, QTableView,
    QVBoxLayout, QWidget,
)

from ..app.config import load_settings, save_settings
from ..app.theme import T, monospace_font
from ..widgets.highlighter import NMHighlighter
from ..widgets.data_explorer import DataExplorerWidget

_log = logging.getLogger(__name__)

_PRESET_EXTS    = ['mod', 'ctl', 'lst', 'tab', 'csv', 'ext', 'cov', 'cor', 'phi',
                   'cnv', 'coi', 'txt', 'pdf', 'png', 'r']
_PILL_LABELS    = {'r': '.R'}   # override default ".{ext}" display label
# Extensions shown as table/plot — NONMEM space-separated format
_NONMEM_TABLE_EXTS = {'tab', 'ext', 'cov', 'cor', 'phi', 'cnv', 'coi'}
# Extensions shown as table/plot — CSV-style
_CSV_TABLE_EXTS    = {'csv'}
_TABLE_EXTS        = _NONMEM_TABLE_EXTS | _CSV_TABLE_EXTS
_HIGHLIGHT_EXTS    = {'mod', 'ctl'}
# Known binary types — show a friendly "no preview" message instead of garbled text
_BINARY_EXTS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'tif', 'ico',
    'zip', 'tar', 'gz', 'bz2', 'xz', '7z', 'rar',
    'exe', 'dll', 'so', 'dylib',
    'mp3', 'mp4', 'wav', 'avi', 'mov',
}

# Qt roles stored on column-0 items in the file list
_ROLE_PATH   = Qt.ItemDataRole.UserRole        # Path object
_ROLE_IS_DIR = Qt.ItemDataRole.UserRole + 1    # bool — True for folder rows


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_size(n: int) -> str:
    if n < 1024:
        return f'{n} B'
    if n < 1_048_576:
        return f'{n / 1024:.1f} KB'
    return f'{n / 1_048_576:.1f} MB'


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


def _merge_csv_sections(rows: list, delim: str):
    """Merge a multi-section CSV into one flat table.

    Algorithm
    ---------
    1. Find the dominant column count (max across all rows).
    2. The first row with that count becomes the canonical header.
    3. Iterate the rows that follow:
       - Rows matching the canonical header exactly → repeated section
         header; flush any pending section title as a label row then skip.
       - Rows with the dominant column count → data rows.
       - Rows with far fewer columns → section-title text; held as
         ``pending_title`` until the next data row consumes it.
       - All other rows are ignored.

    Returns ``(header, data_rows, delim)``, or ``(None, None, delim)`` if
    no usable data could be extracted.
    """
    max_cols = max(len(r) for r in rows)
    header_idx = next((i for i, r in enumerate(rows) if len(r) == max_cols), None)
    if header_idx is None:
        return None, None, delim
    header = rows[header_idx]

    data_rows: list = []
    pending_title: str | None = None

    for i, r in enumerate(rows):
        if i <= header_idx:
            continue                         # skip info rows before main header
        ncols = len(r)
        if ncols == max_cols:
            if r == header:                  # repeated section header
                if pending_title:
                    data_rows.append([f'── {pending_title} ──'] + [''] * (max_cols - 1))
                    pending_title = None
            else:                            # data row
                if pending_title:
                    data_rows.append([f'── {pending_title} ──'] + [''] * (max_cols - 1))
                    pending_title = None
                data_rows.append(r)
        elif ncols < max_cols / 2:           # section-title row
            title = ' '.join(c.strip() for c in r if c.strip())
            if title:
                pending_title = title
        # rows with an intermediate column count are silently skipped

    return (header, data_rows, delim) if data_rows else (None, None, delim)


def _read_csv_file(path: Path):
    """Read CSV with auto-detected delimiter.

    For simple flat files returns ``(headers, rows, delimiter)``.
    For multi-section PsN-style reports (section titles interspersed with
    repeated header rows) the sections are merged via
    :func:`_merge_csv_sections` so the file still opens as a proper table.
    Falls back to ``(None, None, delimiter)`` only when no usable table can
    be extracted at all — the caller should then display the file as text.
    """
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

    # Detect multi-section structure: the first row has far fewer columns
    # than the dominant data rows → merge all sections into one flat table.
    if len(rows) > 1:
        sample_max = max(len(r) for r in rows[1:min(8, len(rows))])
        if sample_max > 0 and len(rows[0]) < sample_max / 2:
            return _merge_csv_sections(rows, delim)

    return rows[0], rows[1:], delim


# ── Virtualised table model (data viewer) ─────────────────────────────────────

class _TableModel(QAbstractTableModel):
    """Lightweight virtualised model — Qt only fetches data for visible rows."""

    def __init__(self, headers: list, rows: list, parent=None):
        super().__init__(parent)
        self._headers  = headers
        self._rows     = rows
        self._editable = False

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            row = self._rows[index.row()]
            col = index.column()
            return row[col] if col < len(row) else ''
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._headers[section] if section < len(self._headers) else ''
        return str(section + 1)

    def flags(self, index):
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self._editable:
            base |= Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.EditRole and index.isValid():
            row = self._rows[index.row()]
            col = index.column()
            if col < len(row):
                row[col] = str(value)
                self.dataChanged.emit(index, index, [role])
                return True
        return False

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self.layoutAboutToBeChanged.emit()
        reverse = (order == Qt.SortOrder.DescendingOrder)
        def _key(row):
            val = row[column] if column < len(row) else ''
            try:
                return (0, float(val))
            except (ValueError, TypeError):
                return (1, val.lower())
        self._rows.sort(key=_key, reverse=reverse)
        self.layoutChanged.emit()

    def get_headers(self):
        return self._headers

    def get_rows(self):
        return self._rows

    def set_editable(self, editable: bool):
        self._editable = editable
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._rows) - 1, len(self._headers) - 1),
            )


# ── Main tab widget ───────────────────────────────────────────────────────────

class FileExplorerTab(QWidget):
    status_msg = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._directory:    str | None  = None   # root set by load_directory()
        self._cwd:          Path | None = None   # currently displayed directory
        self._back_stack:   list[Path]  = []     # navigation history
        self._current_file: Path | None = None
        self._current_delim = ','
        self._highlighter:  NMHighlighter | None = None
        self._table_model:  _TableModel  | None  = None
        self._active_exts:  set[str]     = set() # empty = All
        self._filter_btns:  dict[str, QPushButton] = {}  # ext → pill
        self._pills_layout: QHBoxLayout | None = None    # ref for dynamic insert
        self._build_ui()
        self._load_filter_state()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_nav_bar())

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setObjectName('hairlineSep')
        root.addWidget(sep)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_file_list_panel())
        splitter.addWidget(self._build_content_panel())
        splitter.setSizes([380, 620])
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

    def _build_nav_bar(self) -> QWidget:
        """Full-width toolbar: [←] [breadcrumb ···] [All][.mod]…[+]"""
        bar = QWidget()
        bar.setObjectName('feNavBar')
        bar.setFixedHeight(34)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # ── Back button ───────────────────────────────────────────────────────
        self._back_btn = QPushButton('←')
        self._back_btn.setFixedWidth(28)
        self._back_btn.setFixedHeight(24)
        self._back_btn.setEnabled(False)
        self._back_btn.setToolTip('Go up one level')
        self._back_btn.clicked.connect(self._nav_back)
        layout.addWidget(self._back_btn)

        # ── Breadcrumb ────────────────────────────────────────────────────────
        self._breadcrumb = QLabel('—')
        self._breadcrumb.setObjectName('feBreadcrumb')
        f = self._breadcrumb.font()
        f.setPointSize(10)
        self._breadcrumb.setFont(f)
        layout.addWidget(self._breadcrumb, 1)   # stretch to fill centre

        # ── Filter pills ──────────────────────────────────────────────────────
        pills = QWidget()
        pills_layout = QHBoxLayout(pills)
        pills_layout.setContentsMargins(0, 0, 0, 0)
        pills_layout.setSpacing(3)
        self._pills_layout = pills_layout

        # "All" pill
        all_btn = QPushButton('All')
        all_btn.setObjectName('innerPillBtn')
        all_btn.setCheckable(True)
        all_btn.setChecked(True)
        all_btn.setFixedHeight(22)
        all_btn.setToolTip('Show all files')
        all_btn.clicked.connect(lambda: self._on_filter_pill_clicked('__all__'))
        self._filter_btns['__all__'] = all_btn
        pills_layout.addWidget(all_btn)

        # Preset extension pills
        for ext in _PRESET_EXTS:
            self._make_pill(ext, pills_layout)

        # Inline free-text extension filter
        self._ext_field = QLineEdit()
        self._ext_field.setPlaceholderText('ext…')
        self._ext_field.setFixedHeight(22)
        self._ext_field.setFixedWidth(64)
        self._ext_field.setToolTip('Type an extension to filter (e.g. r or .py); '
                                   'clears when you switch tabs')
        self._ext_field.textChanged.connect(self._on_ext_text_changed)
        pills_layout.addWidget(self._ext_field)

        layout.addWidget(pills)
        return bar

    def _make_pill(self, ext: str, layout: QHBoxLayout | None = None) -> QPushButton:
        """Create and register a filter pill for *ext*; append to layout if given."""
        label = _PILL_LABELS.get(ext, f'.{ext}')
        btn = QPushButton(label)
        btn.setObjectName('innerPillBtn')
        btn.setCheckable(True)
        btn.setChecked(False)
        btn.setFixedHeight(22)
        btn.setToolTip(f'Show only {label} files (folders always visible)')
        btn.clicked.connect(lambda _, e=ext: self._on_filter_pill_clicked(e))
        self._filter_btns[ext] = btn
        if layout is not None:
            layout.addWidget(btn)
        return btn

    def _build_file_list_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._file_table = QTableWidget()
        self._file_table.setColumnCount(3)
        self._file_table.setHorizontalHeaderLabels(['Name', 'Size', 'Modified'])
        hdr = self._file_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(False)
        self._file_table.setColumnWidth(0, 220)
        self._file_table.setColumnWidth(1, 72)
        self._file_table.setColumnWidth(2, 130)
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
        self._file_table.cellDoubleClicked.connect(self._on_double_click)
        self._file_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._file_table.customContextMenuRequested.connect(self._on_file_context_menu)

        v.addWidget(self._file_table)
        return w

    def _build_content_panel(self) -> QWidget:
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
        f = self._content_title.font()
        f.setPointSize(9)
        self._content_title.setFont(f)
        tl.addWidget(self._content_title, 1)

        self._find_edit = QLineEdit()
        self._find_edit.setPlaceholderText('Find...')
        self._find_edit.setFixedHeight(22)
        self._find_edit.setMinimumWidth(100)
        self._find_edit.setMaximumWidth(180)
        self._find_edit.textChanged.connect(self._find_in_text)
        self._find_edit.setVisible(False)
        tl.addWidget(self._find_edit)

        self._table_pill = QPushButton('Table')
        self._table_pill.setObjectName('innerPillBtn')
        self._table_pill.setCheckable(True)
        self._table_pill.setFixedHeight(22)
        self._table_pill.setVisible(False)
        self._table_pill.clicked.connect(self._switch_to_table_view)
        tl.addWidget(self._table_pill)

        self._plot_pill = QPushButton('Plot')
        self._plot_pill.setObjectName('innerPillBtn')
        self._plot_pill.setCheckable(True)
        self._plot_pill.setFixedHeight(22)
        self._plot_pill.setVisible(False)
        self._plot_pill.clicked.connect(self._switch_to_plot_view)
        tl.addWidget(self._plot_pill)

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
        self._discard_btn.setMinimumWidth(66)
        self._discard_btn.setVisible(False)
        self._discard_btn.clicked.connect(self._discard_edits)
        tl.addWidget(self._discard_btn)

        v.addWidget(tb)

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setObjectName('hairlineSep')
        v.addWidget(sep)

        # Stacked: 0=text, 1=table, 2=plot
        self._content_stack = QStackedWidget()

        self._text_view = QPlainTextEdit()
        self._text_view.setReadOnly(True)
        self._text_view.setFont(monospace_font(11))
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Base, QColor(T('bg2')))
        pal.setColor(QPalette.ColorRole.Text, QColor(T('fg')))
        self._text_view.setPalette(pal)

        self._table_view = QTableView()
        self._table_view.setAlternatingRowColors(True)
        self._table_view.setSortingEnabled(True)
        self._table_view.setShowGrid(True)
        self._table_view.verticalHeader().setDefaultSectionSize(22)
        self._table_view.verticalHeader().setVisible(False)
        self._table_view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table_view.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table_view.horizontalHeader().setDefaultSectionSize(100)
        self._table_view.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)

        self.data_explorer = DataExplorerWidget(show_browser=False)
        self._content_stack.addWidget(self._text_view)     # 0
        self._content_stack.addWidget(self._table_view)    # 1
        self._content_stack.addWidget(self.data_explorer)  # 2
        v.addWidget(self._content_stack, 1)

        return w

    # ── View switching ────────────────────────────────────────────────────────

    def _switch_to_table_view(self):
        self._content_stack.setCurrentIndex(1)
        self._table_pill.setChecked(True)
        self._plot_pill.setChecked(False)
        self._edit_btn.setVisible(True)

    def _switch_to_plot_view(self):
        self._content_stack.setCurrentIndex(2)
        self._plot_pill.setChecked(True)
        self._table_pill.setChecked(False)
        self._edit_btn.setChecked(False)
        self._edit_btn.setVisible(False)
        self._save_btn.setVisible(False)
        self._discard_btn.setVisible(False)
        self.data_explorer._de_switch(1)  # always land on the plot sub-page

    # ── Public API ────────────────────────────────────────────────────────────

    def load_directory(self, path: str | None):
        """Called externally when the working directory changes."""
        self._directory    = path
        self._cwd          = Path(path) if path else None
        self._back_stack   = []
        self._current_file = None
        self._table_model  = None
        self._table_view.setModel(None)
        self._back_btn.setEnabled(False)
        self._content_title.setText('No file selected')
        self._text_view.setPlainText('')
        self._edit_btn.setChecked(False)
        self._edit_btn.setVisible(False)
        self._save_btn.setVisible(False)
        self._discard_btn.setVisible(False)
        self._find_edit.setVisible(False)
        self._table_pill.setVisible(False)
        self._plot_pill.setVisible(False)
        self._rebuild_file_list()

    def select_file(self, path: str):
        """Select and preview a file by full path (navigates to its parent if needed)."""
        p = Path(path)
        parent = p.parent
        if parent != self._cwd:
            # Navigate to the file's parent if it's under the root
            root = Path(self._directory) if self._directory else None
            if root and (parent == root or str(parent).startswith(str(root) + '/')):
                self._navigate_to(parent)
            else:
                return
        for row in range(self._file_table.rowCount()):
            item = self._file_table.item(row, 0)
            if item and item.data(_ROLE_PATH) == p:
                self._file_table.setCurrentCell(row, 0)
                return

    # ── Navigation ────────────────────────────────────────────────────────────

    def _navigate_into(self, folder: Path):
        if self._cwd:
            self._back_stack.append(self._cwd)
        self._cwd = folder
        self._back_btn.setEnabled(True)
        self._current_file = None
        self._content_title.setText('No file selected')
        self._text_view.setPlainText('')
        self._rebuild_file_list()

    def _navigate_to(self, directory: Path):
        """Jump directly to *directory*, building a back-stack from root."""
        root = Path(self._directory) if self._directory else None
        if root is None:
            return
        try:
            rel = directory.relative_to(root)
        except ValueError:
            return
        # Build back stack: root → each ancestor → directory
        parts = rel.parts
        self._back_stack = [root] + [root.joinpath(*parts[:i]) for i in range(1, len(parts))]
        self._cwd = directory
        self._back_btn.setEnabled(bool(self._back_stack))
        self._rebuild_file_list()

    def _nav_back(self):
        if self._back_stack:
            self._cwd = self._back_stack.pop()
            self._back_btn.setEnabled(bool(self._back_stack))
            self._current_file = None
            self._content_title.setText('No file selected')
            self._text_view.setPlainText('')
            self._rebuild_file_list()

    def _update_breadcrumb(self):
        if not self._cwd:
            self._breadcrumb.setText('—')
            return
        root = Path(self._directory) if self._directory else None
        if root and self._cwd != root:
            try:
                rel = self._cwd.relative_to(root)
                text = f'{root.name}  /  {str(rel).replace("/", "  /  ")}'
            except ValueError:
                text = str(self._cwd)
        else:
            text = self._cwd.name if self._cwd else '—'
        self._breadcrumb.setText(text)

    # ── Filter pills ──────────────────────────────────────────────────────────

    def _on_filter_pill_clicked(self, ext: str):
        if ext == '__all__':
            self._active_exts.clear()
        else:
            if ext in self._active_exts:
                self._active_exts.discard(ext)
            else:
                self._active_exts.add(ext)
            # If nothing remains active, revert to All
            if not self._active_exts:
                pass  # handled by _sync_pill_states
        self._sync_pill_states()
        self._save_filter_state()
        self._rebuild_file_list()

    def _sync_pill_states(self):
        """Update pill checked states to match self._active_exts."""
        all_active = len(self._active_exts) == 0
        for key, btn in self._filter_btns.items():
            if key == '__all__':
                btn.setChecked(all_active)
            else:
                btn.setChecked(key in self._active_exts)

    def _on_ext_text_changed(self, _text: str):
        self._rebuild_file_list()

    # ── File list ─────────────────────────────────────────────────────────────

    def _rebuild_file_list(self):
        self._file_table.setSortingEnabled(False)
        self._file_table.setRowCount(0)

        if not self._cwd or not self._cwd.is_dir():
            self._update_breadcrumb()
            return

        try:
            entries = list(self._cwd.iterdir())
        except PermissionError:
            self._update_breadcrumb()
            return

        # Free-text field overrides pills when non-empty; otherwise use active pills
        typed = self._ext_field.text().strip().lstrip('.')
        active = {typed.lower()} if typed else self._active_exts  # set; empty = show all

        folders = sorted(
            [e for e in entries if e.is_dir() and not e.name.startswith('.')],
            key=lambda e: e.name.lower(),
        )
        if active:
            files = sorted(
                [e for e in entries
                 if e.is_file() and e.suffix.lstrip('.').lower() in active],
                key=lambda f: f.name.lower(),
            )
        else:
            files = sorted(
                [e for e in entries if e.is_file()],
                key=lambda f: f.name.lower(),
            )

        rows = folders + files
        self._file_table.setRowCount(len(rows))

        for row, entry in enumerate(rows):
            is_dir = entry.is_dir()
            if is_dir:
                display_name = f'📁  {entry.name}'
                size_str     = '—'
                mtime_str    = '—'
            else:
                try:
                    stat      = entry.stat()
                    size_str  = _fmt_size(stat.st_size)
                    mtime_str = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                except OSError:
                    size_str  = '—'
                    mtime_str = '—'
                display_name = entry.name

            name_it = QTableWidgetItem(display_name)
            name_it.setData(_ROLE_PATH,   entry)
            name_it.setData(_ROLE_IS_DIR, is_dir)
            name_it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if is_dir:
                f = name_it.font()
                f.setBold(True)
                name_it.setFont(f)

            size_it = QTableWidgetItem(size_str)
            size_it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            size_it.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            mod_it = QTableWidgetItem(mtime_str)
            mod_it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

            self._file_table.setItem(row, 0, name_it)
            self._file_table.setItem(row, 1, size_it)
            self._file_table.setItem(row, 2, mod_it)

        self._file_table.setSortingEnabled(True)
        self._update_breadcrumb()

    # ── Context menu ──────────────────────────────────────────────────────────

    def _on_file_context_menu(self, pos):
        """Show a context menu for right-clicked file rows."""
        row = self._file_table.rowAt(pos.y())   # right-click row, not current selection
        if row < 0:
            return
        item = self._file_table.item(row, 0)
        if not item or item.data(_ROLE_IS_DIR):
            return
        path: Path = item.data(_ROLE_PATH)
        if path is None:
            return

        # Currently only .tab files have a context action
        if path.suffix.lower() != '.tab':
            return

        menu = QMenu(self)
        convert_act = menu.addAction('Convert to CSV')
        action = menu.exec(self._file_table.viewport().mapToGlobal(pos))
        if action == convert_act:
            self._convert_tab_to_csv(path)

    def _convert_tab_to_csv(self, path: Path):
        """Convert a NONMEM TABLE file to CSV, then reload the file list."""
        csv_path = path.with_suffix('.csv')

        if csv_path.exists():
            QMessageBox.warning(
                self, 'File already exists',
                f'<b>{csv_path.name}</b> already exists in this folder.<br>'
                f'Remove or rename it before converting.',
            )
            return

        try:
            headers, rows = _read_nonmem_table(path)
        except Exception as e:
            QMessageBox.critical(self, 'Read error', f'Could not read {path.name}:\n{e}')
            return

        if not headers:
            QMessageBox.warning(
                self, 'Conversion failed',
                f'No table data could be parsed from {path.name}.\n'
                f'The file may be empty or in an unexpected format.',
            )
            return

        try:
            with csv_path.open('w', newline='', encoding='utf-8') as fh:
                writer = csv.writer(fh)
                writer.writerow(headers)
                writer.writerows(rows)
        except Exception as e:
            QMessageBox.critical(self, 'Write error', f'Could not write {csv_path.name}:\n{e}')
            return

        self.status_msg.emit(f'Converted {path.name}  →  {csv_path.name}')
        self._rebuild_file_list()

        # Re-select the newly created CSV without triggering a second rebuild
        for r in range(self._file_table.rowCount()):
            it = self._file_table.item(r, 0)
            if it and it.data(_ROLE_PATH) == csv_path:
                self._file_table.setCurrentCell(r, 0)
                break

    # ── File selection / double-click ─────────────────────────────────────────

    def _on_file_selected(self):
        """Single-click: load preview for files; ignore folder rows."""
        row = self._file_table.currentRow()
        if row < 0:
            return
        item = self._file_table.item(row, 0)
        if not item:
            return
        if item.data(_ROLE_IS_DIR):
            return  # folder row — no preview
        path = item.data(_ROLE_PATH)
        if not path or path == self._current_file:
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
        self._current_file = path
        self._load_file(path)

    def _on_double_click(self, row: int, _col: int):
        """Double-click: navigate into folder or open file with system app."""
        item = self._file_table.item(row, 0)
        if not item:
            return
        path:   Path = item.data(_ROLE_PATH)
        is_dir: bool = item.data(_ROLE_IS_DIR)
        if path is None:
            return
        if is_dir:
            self._navigate_into(path)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ── Content loading ───────────────────────────────────────────────────────

    def _load_file(self, path: Path):
        ext = path.suffix.lstrip('.').lower()
        self._content_title.setText(path.name)
        if ext in _BINARY_EXTS:
            self._show_no_preview(path)
        elif ext in _TABLE_EXTS:
            self._load_table_file(path, ext)
        else:
            self._load_text_file(path, ext)

    def _show_no_preview(self, path: Path):
        """Show a friendly placeholder for binary / non-previewable files."""
        self._content_stack.setCurrentIndex(0)
        self._text_view.setReadOnly(True)
        self._text_view.setPlainText(
            f'No preview available for {path.suffix.upper() or "this"} files.\n\n'
            f'Double-click the file in the browser to open it with the system application.'
        )
        if self._highlighter is not None:
            self._highlighter.setDocument(None)
            self._highlighter = None
        self._find_edit.setVisible(False)
        self._table_pill.setVisible(False)
        self._table_pill.setChecked(False)
        self._plot_pill.setVisible(False)
        self._plot_pill.setChecked(False)
        self._edit_btn.setVisible(False)
        self._save_btn.setVisible(False)
        self._discard_btn.setVisible(False)

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
        self._table_pill.setVisible(False)
        self._table_pill.setChecked(False)
        self._plot_pill.setVisible(False)
        self._plot_pill.setChecked(False)
        if self._content_stack.currentIndex() == 2:
            self._content_stack.setCurrentIndex(0)
        self._edit_btn.setVisible(True)
        self._save_btn.setVisible(False)
        self._discard_btn.setVisible(False)

    def _load_table_file(self, path: Path, ext: str):
        try:
            if ext in _NONMEM_TABLE_EXTS:
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
            self._table_pill.setVisible(False)
            self._plot_pill.setVisible(False)
            return

        # _read_csv_file returns None headers when the file is a multi-section
        # report (e.g. PsN sir_results.csv) — fall back to the text viewer.
        if headers is None:
            self._load_text_file(path, ext)
            return

        seen:   dict = {}
        deduped: list = []
        for c in headers:
            cu = c.upper()
            if cu in seen:
                seen[cu] += 1
                deduped.append(f'{c}_{seen[cu]}')
            else:
                seen[cu] = 1
                deduped.append(c)
        headers = deduped

        self._table_model = _TableModel(headers, rows)
        self._table_view.setModel(self._table_model)
        self._table_view.resizeColumnsToContents()
        self.data_explorer.load(headers, rows)

        self._content_stack.setCurrentIndex(1)
        self._find_edit.setVisible(False)
        self._table_pill.setVisible(True)
        self._table_pill.setChecked(True)
        self._plot_pill.setVisible(True)
        self._plot_pill.setChecked(False)
        self._edit_btn.setVisible(True)
        self._save_btn.setVisible(False)
        self._discard_btn.setVisible(False)

    # ── Edit / save / discard ─────────────────────────────────────────────────

    def _toggle_edit_mode(self, checked: bool):
        idx = self._content_stack.currentIndex()
        if idx == 0:
            self._text_view.setReadOnly(not checked)
        elif idx == 1:
            if self._table_model:
                self._table_model.set_editable(checked)
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
                self._current_file.write_text(self._text_view.toPlainText(), 'utf-8')
            else:
                if self._current_file.suffix.lower() == '.tab':
                    QMessageBox.information(
                        self, 'Read-only',
                        '.tab files are NONMEM output — direct editing is not supported.')
                    return
                if not self._table_model:
                    return
                out_rows = [self._table_model.get_headers()] + self._table_model.get_rows()
                delim = self._current_delim or ','
                with self._current_file.open('w', newline='', encoding='utf-8') as fh:
                    csv.writer(fh, delimiter=delim).writerows(out_rows)
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
            sel.format  = fmt
            selections.append(sel)
        self._text_view.setExtraSelections(selections)
        if selections:
            self._text_view.setTextCursor(selections[0].cursor)

    # ── Settings persistence ──────────────────────────────────────────────────

    def _save_filter_state(self):
        s = load_settings()
        s['file_explorer_active_exts'] = sorted(self._active_exts)
        save_settings(s)

    def _load_filter_state(self):
        s = load_settings()
        active = s.get('file_explorer_active_exts')
        if active is None:
            # Migrate from old checkbox format
            checked = s.get('file_explorer_checked_exts', list(_PRESET_EXTS))
            active = [] if set(checked) == set(_PRESET_EXTS) else [
                e for e in checked if e in self._filter_btns]
        self._active_exts = set(active) & set(self._filter_btns.keys()) - {'__all__'}
        self._sync_pill_states()

    def hideEvent(self, event):
        """Clear the free-text ext field when the tab is hidden (non-persistent)."""
        if hasattr(self, '_ext_field'):
            self._ext_field.clear()
        super().hideEvent(event)
