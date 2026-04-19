"""Reusable collapsible card widget."""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSizePolicy
from PyQt6.QtCore import Qt
from ..app.theme import C


class CollapsibleCard(QWidget):
    """A titled card with a clickable header that shows/hides its body."""

    def __init__(self, title: str, expanded: bool = True, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 6)
        outer.setSpacing(0)

        self._btn = QPushButton()
        self._btn.setCheckable(True)
        self._btn.setChecked(expanded)
        self._btn.setFixedHeight(28)
        self._btn.setStyleSheet(self._header_css())
        self._btn.toggled.connect(self._on_toggle)
        self._set_label(title, expanded)
        outer.addWidget(self._btn)

        self._body = QWidget()
        self._body.setObjectName('cardBody')
        self._body.setStyleSheet(self._body_css())
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(10, 10, 10, 10)
        self._body_layout.setSpacing(6)
        self._body.setVisible(expanded)
        outer.addWidget(self._body)

        self._title = title

    def _body_css(self):
        # ID selector ensures this rule only matches the body itself, not child
        # input widgets — a bare 'background:' would block the global app stylesheet
        # from reaching QLineEdit/QTextEdit descendants.
        return (
            f'QWidget#cardBody{{background:{C.bg2};'
            f'border-left:1px solid {C.border};'
            f'border-right:1px solid {C.border};'
            f'border-bottom:1px solid {C.border};'
            f'border-bottom-left-radius:6px;border-bottom-right-radius:6px;}}')

    def _header_css(self):
        return (
            f'QPushButton{{background:{C.bg3};color:{C.fg};'
            f'border:1px solid {C.border};border-radius:0;'
            f'border-top-left-radius:6px;border-top-right-radius:6px;'
            f'padding:0 10px;font-size:11px;font-weight:600;'
            f'text-transform:uppercase;letter-spacing:0.5px;text-align:left;min-width:0;}}'
            f'QPushButton:checked{{border-bottom-left-radius:0;border-bottom-right-radius:0;}}'
            f'QPushButton:hover{{background:{C.bg4};}}'
        )

    def _set_label(self, title, expanded):
        arrow = '\u25bc' if expanded else '\u25b6'   # ▼ / ▶
        self._btn.setText(f' {arrow}  {title}')

    def _on_toggle(self, checked):
        self._set_label(self._title, checked)
        self._body.setVisible(checked)

    def body_layout(self) -> QVBoxLayout:
        return self._body_layout

    def add_widget(self, widget):
        self._body_layout.addWidget(widget)

    def add_layout(self, layout):
        self._body_layout.addLayout(layout)

    def set_expanded(self, expanded: bool):
        self._btn.setChecked(expanded)

    def refresh_theme(self):
        self._btn.setStyleSheet(self._header_css())
        self._body.setStyleSheet(self._body_css())
