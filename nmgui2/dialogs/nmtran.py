import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QPlainTextEdit, QPushButton,
)
from PyQt6.QtGui import QFont, QPalette, QColor

from ..app.theme import C

IS_MAC = sys.platform == 'darwin'

try:
    from ..parser import parse_nmtran_errors
    HAS_PARSER = True
except ImportError:
    HAS_PARSER = False


class NMTRANPanel(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'NMTRAN messages — {model.get("stem","")}')
        self.resize(700, 400)
        v = QVBoxLayout(self)
        self.text = QPlainTextEdit(); self.text.setReadOnly(True)
        self.text.setFont(QFont('Menlo' if IS_MAC else 'Consolas',12))
        pal = self.text.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(C.bg2))
        pal.setColor(QPalette.ColorRole.Text, QColor(C.fg))
        self.text.setPalette(pal)
        v.addWidget(self.text)
        close = QPushButton('Close'); close.clicked.connect(self.accept)
        v.addWidget(close)
        self._load(model)

    def _load(self, model):
        if not HAS_PARSER: self.text.setPlainText('parser.py not available'); return
        base_dir = str(Path(model['path']).parent)
        stem     = model['stem']
        errors   = parse_nmtran_errors(base_dir, stem)
        if not errors:
            # Fall back to first 3000 chars of .lst
            if model.get('lst_path'):
                try:
                    txt = Path(model['lst_path']).read_text('utf-8', errors='replace')[:3000]
                    self.text.setPlainText(txt)
                except Exception:
                    self.text.setPlainText('No NMTRAN messages found.')
            else:
                self.text.setPlainText('No NMTRAN messages found.')
            return
        lines = []
        for e in errors:
            tag = '[ERROR]' if e.get('type')=='error' else '[INFO] '
            lines.append(f'{tag} {e.get("message","")}')
        self.text.setPlainText('\n'.join(lines))
