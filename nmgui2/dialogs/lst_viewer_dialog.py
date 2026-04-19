import sys

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel,
    QPushButton, QPlainTextEdit,
)
from PyQt6.QtGui import QFont, QColor, QPalette
from PyQt6.QtCore import Qt

from ..app.theme import C, _active_theme

IS_MAC = sys.platform == 'darwin'


class LstViewerDialog(QDialog):
    """Non-modal .lst file viewer with search."""
    def __init__(self, stem, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'{stem}.lst')
        self.resize(820, 640)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        v = QVBoxLayout(self); v.setContentsMargins(8,8,8,8); v.setSpacing(6)

        # Search bar
        search_row = QHBoxLayout()
        self._search = QLineEdit(); self._search.setPlaceholderText('Search… (Enter = next, Shift+Enter = prev)')
        self._search.returnPressed.connect(self._find_next)
        self._match_lbl = QLabel('')
        self._match_lbl.setObjectName('mutedSmall')
        prev_btn = QPushButton('^'); prev_btn.setFixedWidth(32); prev_btn.clicked.connect(self._find_prev)
        next_btn = QPushButton('v'); next_btn.setFixedWidth(32); next_btn.clicked.connect(self._find_next)
        search_row.addWidget(self._search, 1); search_row.addWidget(prev_btn)
        search_row.addWidget(next_btn); search_row.addWidget(self._match_lbl)
        v.addLayout(search_row)

        # Text viewer
        self._editor = QPlainTextEdit()
        self._editor.setReadOnly(True)
        self._editor.setFont(QFont('Menlo' if IS_MAC else 'Consolas', 11))
        self._editor.setPlainText(text)
        pal = self._editor.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(C.bg2))
        pal.setColor(QPalette.ColorRole.Text, QColor(C.fg))
        self._editor.setPalette(pal)
        v.addWidget(self._editor, 1)

        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.close)
        btn_row = QHBoxLayout(); btn_row.addStretch(); btn_row.addWidget(close_btn)
        v.addLayout(btn_row)

        self._search.textChanged.connect(self._highlight_all)
        self._positions = []; self._pos_idx = 0

    def _highlight_all(self):
        from PyQt6.QtGui import QTextCharFormat, QTextCursor
        from ..app.theme import _active_theme as _at
        # Clear existing
        cursor = self._editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        fmt_clear = QTextCharFormat(); fmt_clear.setBackground(QColor('transparent'))
        cursor.mergeCharFormat(fmt_clear)
        self._positions = []; self._pos_idx = 0
        term = self._search.text()
        if not term: self._match_lbl.setText(''); return
        doc = self._editor.document()
        fmt = QTextCharFormat(); fmt.setBackground(QColor('#ffdd44' if _at=='light' else '#554400'))
        cursor = doc.find(term)
        while not cursor.isNull():
            self._positions.append(cursor.position())
            cursor.mergeCharFormat(fmt)
            cursor = doc.find(term, cursor)
        n = len(self._positions)
        self._match_lbl.setText(f'{n} match{"es" if n!=1 else ""}' if n else 'Not found')
        if n: self._goto(0)

    def _goto(self, idx):
        if not self._positions: return
        self._pos_idx = idx % len(self._positions)
        c = self._editor.textCursor()
        c.setPosition(self._positions[self._pos_idx])
        self._editor.setTextCursor(c)
        self._editor.ensureCursorVisible()
        self._match_lbl.setText(f'{self._pos_idx+1} / {len(self._positions)}')

    def _find_next(self): self._goto(self._pos_idx + 1)
    def _find_prev(self): self._goto(self._pos_idx - 1)
