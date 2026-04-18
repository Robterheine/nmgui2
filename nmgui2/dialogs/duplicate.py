from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QCheckBox, QDoubleSpinBox,
    QDialogButtonBox,
)

from ..app.config import load_settings


class DuplicateDialog(QDialog):
    def __init__(self, stem, parent=None):
        super().__init__(parent); self.setWindowTitle('Duplicate Model'); self.setFixedWidth(360)
        f = QFormLayout(self)
        self.name_edit  = QLineEdit(stem+'_2')
        self.use_est    = QCheckBox('Inject final estimates from .lst')
        self.jitter_sb  = QDoubleSpinBox(); self.jitter_sb.setRange(0,1); self.jitter_sb.setSingleStep(0.05); self.jitter_sb.setDecimals(2)
        f.addRow('New filename:', self.name_edit)
        f.addRow('', self.use_est)
        f.addRow('Jitter ±fraction:', self.jitter_sb)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        f.addRow(btns)
