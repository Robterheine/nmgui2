from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTableWidget,
                              QTableWidgetItem, QAbstractItemView,
                              QStyledItemDelegate)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt

from ..app.theme import C

_BG_ROLE = Qt.ItemDataRole.UserRole + 1


class _BgDelegate(QStyledItemDelegate):
    """Paint cell backgrounds from _BG_ROLE.

    The app stylesheet has a QTableWidget::item rule, which makes Qt's
    stylesheet style ignore item background brushes — so the band color
    must be painted here instead of via setBackground().
    """
    def paint(self, painter, option, index):
        bg = index.data(_BG_ROLE)
        if bg:
            painter.fillRect(option.rect, QColor(bg))
        super().paint(painter, option, index)


def _text_on(bg_hex):
    """Black or white text for WCAG-adequate contrast on the given background."""
    c = QColor(bg_hex)

    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    lum = 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue())
    # Contrast vs black is (L+0.05)/0.05; >= 4.5 when L >= 0.175
    return '#000000' if lum >= 0.175 else '#ffffff'


class CorrelationWidget(QWidget):
    """Color-coded correlation matrix of the estimates ($COV step)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._matrix = []
        self._labels = []

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        self._legend = QLabel(
            '|r| ≥ 0.9 very high (identifiability concern)   ·   '
            '0.7 – 0.9 high   ·   0.3 – 0.7 moderate   ·   < 0.3 uncolored')
        self._legend.setObjectName('muted')
        v.addWidget(self._legend)

        self._empty = QLabel('No covariance step — run with $COV to see parameter correlations.')
        self._empty.setObjectName('mutedLarge')
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self._empty, 1)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setItemDelegate(_BgDelegate(self.table))
        self.table.verticalHeader().setDefaultSectionSize(24)
        v.addWidget(self.table, 1)
        self.table.setVisible(False)

    def load(self, matrix, labels):
        self._matrix = matrix or []
        self._labels = labels or []
        self._populate()

    def refresh_theme(self):
        """Re-run cell coloring with the current theme palette."""
        self._populate()

    def _cell_bg(self, r):
        a = abs(r)
        if a >= 0.9:
            return C.red
        if a >= 0.7:
            return C.orange
        if a >= 0.3:
            return C.yellow
        return None

    def _populate(self):
        has_data = bool(self._matrix)
        self._empty.setVisible(not has_data)
        self._legend.setVisible(has_data)
        self.table.setVisible(has_data)
        if not has_data:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        n = max(len(self._matrix), len(self._labels))
        labels = [self._labels[i] if i < len(self._labels) else f'P{i + 1}'
                  for i in range(n)]
        self.table.setRowCount(n)
        self.table.setColumnCount(n)
        self.table.setHorizontalHeaderLabels(labels)
        self.table.setVerticalHeaderLabels(labels)

        for i in range(n):
            row = self._matrix[i] if i < len(self._matrix) else []
            for j in range(n):
                if j > i:
                    # Upper triangle (not filled by the parser) — blank
                    self.table.setItem(i, j, QTableWidgetItem(''))
                    continue
                val = row[j] if j < len(row) else None
                item = QTableWidgetItem('—' if val is None else f'{val:.2f}')
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if val is None:
                    item.setForeground(QColor(C.fg3))
                    item.setToolTip(f'{labels[i]} × {labels[j]}: not estimated')
                elif i == j:
                    # Diagonal — neutral treatment
                    bg = C.bg3
                    item.setData(_BG_ROLE, bg)
                    item.setForeground(QColor(_text_on(bg)))
                else:
                    bg = self._cell_bg(val)
                    if bg:
                        item.setData(_BG_ROLE, bg)
                        item.setForeground(QColor(_text_on(bg)))
                    item.setToolTip(f'{labels[i]} × {labels[j]}: r = {val:.3f}')
                self.table.setItem(i, j, item)
        self.table.resizeColumnsToContents()
