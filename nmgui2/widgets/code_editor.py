"""Line-numbered code editor for NONMEM control streams.

A `QPlainTextEdit` subclass that paints a line-number gutter on the left
margin via Qt's canonical "Code Editor Example" pattern: a small child
widget covers the area reserved by `setViewportMargins`, and its
`paintEvent` walks the document's visible blocks to draw right-aligned
line numbers.

The class is intentionally minimal: no folding, no find/replace, no
minimap. It is a drop-in replacement for the existing `QPlainTextEdit`
used as the model editor; all inherited methods (`toPlainText`,
`setPlainText`, `setFont`, `setPalette`, `document()`, etc.) work
unchanged, including the existing `NMHighlighter` attachment.

Public additions for future error-jumping support:
    goto_line(n: int, flash: bool = True)   — scroll to line n and
                                              briefly highlight it
    lineJumped(int)                          — emitted after goto_line
"""

from PyQt6.QtCore import Qt, QRect, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QTextCursor, QTextFormat
from PyQt6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from ..app.theme import T


class _LineNumberArea(QWidget):
    """The gutter widget. Delegates paint to the editor (which owns layout)."""

    def __init__(self, editor: 'CodeEditor'):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor._gutter_width(), 0)

    def paintEvent(self, event):
        self._editor._paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    """QPlainTextEdit with a line-number gutter and a goto_line() hook."""

    # Emitted after a successful goto_line(); useful for future wiring
    # (e.g. NMTRAN error-panel click → editor jump).
    lineJumped = pyqtSignal(int)

    # Right-edge padding inside the gutter (px)
    _RIGHT_PAD = 6
    # Left-edge padding inside the gutter (px)
    _LEFT_PAD  = 4
    # Hairline width (px)
    _BORDER_W  = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        # Control streams are line-oriented; wrapping would mis-align the gutter.
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._line_area = _LineNumberArea(self)
        # Block count changes (line added/removed) → recompute gutter width.
        self.blockCountChanged.connect(lambda _n: self._update_margins())
        # Scroll/repaint → keep gutter in sync.
        self.updateRequest.connect(self._on_update_request)
        # Repaint gutter when cursor moves, so the current-line number can
        # render in a brighter color.
        self.cursorPositionChanged.connect(self._line_area.update)
        self._update_margins()

    # ── Geometry ──────────────────────────────────────────────────────────────

    def _gutter_width(self) -> int:
        """Width in px: enough for the largest line number, with a 3-digit
        minimum reservation so the gutter doesn't jitter as the line count
        crosses 10 / 100 / 1000."""
        digits = max(3, len(str(max(1, self.blockCount()))))
        digit_w = self.fontMetrics().horizontalAdvance('9')
        return self._LEFT_PAD + digits * digit_w + self._RIGHT_PAD + self._BORDER_W

    def _update_margins(self):
        self.setViewportMargins(self._gutter_width(), 0, 0, 0)

    def _on_update_request(self, rect: QRect, dy: int):
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margins()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(cr.left(), cr.top(), self._gutter_width(), cr.height())

    def setFont(self, font):
        super().setFont(font)
        self._update_margins()

    # ── Theme ─────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        """Repaint the gutter using the currently-active theme tokens.
        Called from the containing ModelsTab on theme switch."""
        self._line_area.update()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def _paint_gutter(self, event):
        painter = QPainter(self._line_area)
        bg      = QColor(T('bg'))
        muted   = QColor(T('fg3'))
        active  = QColor(T('fg'))
        border  = QColor(T('border'))
        w = self._line_area.width()

        # Background + right-edge hairline separator
        painter.fillRect(event.rect(), bg)
        painter.setPen(border)
        painter.drawLine(w - 1, event.rect().top(), w - 1, event.rect().bottom())

        # Walk visible blocks
        block      = self.firstVisibleBlock()
        block_num  = block.blockNumber()
        top        = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom     = top + self.blockBoundingRect(block).height()
        current    = self.textCursor().blockNumber()
        text_rect_w = w - self._RIGHT_PAD - self._BORDER_W
        align       = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(active if block_num == current else muted)
                painter.drawText(
                    0, int(top), text_rect_w, int(self.blockBoundingRect(block).height()),
                    align, str(block_num + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_num += 1

    # ── Public API — for future error-jumping wiring ──────────────────────────

    def goto_line(self, n: int, flash: bool = True):
        """Scroll the editor to (1-based) line n; place cursor at column 0.

        If `flash` is true, the destination line gets a brief background
        highlight that clears after 800ms. Emits `lineJumped(n)` on success.
        """
        if n < 1:
            n = 1
        block = self.document().findBlockByNumber(n - 1)
        if not block.isValid():
            return
        cursor = self.textCursor()
        cursor.setPosition(block.position())
        self.setTextCursor(cursor)
        self.centerCursor()
        if flash:
            self._flash_current_line()
        self.lineJumped.emit(n)

    def _flash_current_line(self):
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor(T('accent')))
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.setExtraSelections([sel])
        QTimer.singleShot(800, lambda: self.setExtraSelections([]))
