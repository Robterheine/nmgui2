from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

from ..app.theme import C, T


class KeyboardShortcutsDialog(QDialog):
    """Non-modal dialog showing keyboard shortcuts."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Keyboard Shortcuts')
        self.setFixedWidth(420)
        self.setModal(False)  # Non-modal so users can try shortcuts while viewing

        v = QVBoxLayout(self); v.setContentsMargins(20,20,20,20); v.setSpacing(16)

        # Define shortcuts by category
        shortcuts = [
            ('Navigation', [
                ('Ctrl+1 – 7', 'Switch sidebar tabs'),
                ('Ctrl+Q', 'Quit application'),
                ('Ctrl+Shift+T', 'Toggle light/dark theme'),
                ('F1 or Ctrl+/', 'Show this help'),
            ]),
            ('Models Tab', [
                ('Up / Down', 'Navigate model list'),
                ('Enter', 'Switch to Output tab'),
                ('Space', 'Toggle star on selected model'),
                ('Double-click', 'Open .lst file in default app'),
            ]),
            ('Editor', [
                ('Ctrl+S', 'Save control stream'),
                ('Ctrl+Z / Ctrl+Y', 'Undo / Redo'),
            ]),
            ('General', [
                ('Escape', 'Close dialog'),
            ]),
        ]

        for section, keys in shortcuts:
            # Section header
            header = QLabel(section)
            header.setStyleSheet(f'font-weight:600;font-size:12px;color:{T("fg")};margin-top:4px;')
            v.addWidget(header)

            # Shortcuts grid
            for key, desc in keys:
                row = QHBoxLayout(); row.setSpacing(12)
                key_lbl = QLabel(key)
                key_lbl.setFixedWidth(120)
                key_lbl.setStyleSheet(f'font-family:monospace;font-size:11px;color:{T("accent")};background:{T("bg3")};padding:2px 6px;border-radius:3px;')
                desc_lbl = QLabel(desc)
                desc_lbl.setStyleSheet(f'font-size:12px;color:{T("fg2")};')
                row.addWidget(key_lbl)
                row.addWidget(desc_lbl, 1)
                v.addLayout(row)

        v.addStretch()

        # Close button
        close_btn = QPushButton('Close')
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.close)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        v.addLayout(btn_row)
