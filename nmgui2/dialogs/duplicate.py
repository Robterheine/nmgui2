import re

from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QCheckBox, QDoubleSpinBox,
    QDialogButtonBox, QLabel,
)
from PyQt6.QtCore import QTimer

from ..app.config import load_settings


# New filename must start with a letter; allow letters/digits/underscore/hyphen
# and an optional .mod or .ctl extension. No path separators, no .., no spaces —
# prevents path traversal (e.g. "../etc/passwd") and shell-quoting surprises.
# Mirrors NewModelDialog's _STEM_RE pattern with the extension addendum.
_DUPLICATE_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_\-]*(?:\.(?:mod|ctl))?$')


class DuplicateDialog(QDialog):
    def __init__(self, stem, src_description='', parent=None):
        super().__init__(parent)
        self.setWindowTitle('Duplicate Model')
        self.setMinimumWidth(440)
        f = QFormLayout(self)

        self.name_edit = QLineEdit(stem + '_2')

        # Description — pre-fill verbatim from source so quick fork-and-edit flows fast.
        # Pharmacometricians typically duplicate to test a variant of a base model;
        # blank-by-default leads to many empty Description rows in practice.
        # Backed by meta['comment'] when persisted (same field as the Annotation panel).
        self.desc_edit = QLineEdit(src_description)
        self.desc_edit.setPlaceholderText('Short description (e.g. "base + ETA on V")')
        self.desc_edit.setToolTip(
            'Optional one-line description. Shown in the Description column '
            'and editable later in the Annotation panel.\n'
            'Pre-filled from the source model — edit to describe what differs.'
        )
        # Auto-select on focus so one keystroke replaces the inherited text
        QTimer.singleShot(0, self._select_description_when_focused)

        self.use_est = QCheckBox('Inject final estimates from .lst')

        self.jitter_sb = QDoubleSpinBox()
        self.jitter_sb.setRange(0, 1)
        self.jitter_sb.setSingleStep(0.05)
        self.jitter_sb.setDecimals(2)

        # Rename $TABLE / $MSFO outputs to match the new model stem.
        # Default ON: prevents the duplicate from silently overwriting the source's
        # output tables and MSF files when both runs share a directory. The user can
        # uncheck for the rare case where downstream R/PsN scripts hard-code the
        # original filenames (e.g. sdtab104) — see README changelog.
        self.rename_outputs = QCheckBox('Rename output files ($TABLE / $MSFO) to match new name')
        self.rename_outputs.setChecked(True)
        self.rename_outputs.setToolTip(
            'Recommended. Rewrites $TABLE FILE= and $MSFO= filenames in the duplicated\n'
            '.mod so the new run does not overwrite the source\'s output tables or MSF.\n\n'
            'Uncheck only if external scripts (R, PsN config) hard-code the original\n'
            'filenames and you accept that re-running either model will overwrite\n'
            'the other\'s outputs.'
        )

        f.addRow('New filename:', self.name_edit)
        f.addRow('Description:', self.desc_edit)
        f.addRow('', self.use_est)
        f.addRow('Jitter ±fraction:', self.jitter_sb)
        f.addRow('', self.rename_outputs)

        # Inline validation error label (matches NewModelDialog convention)
        self._error_lbl = QLabel('')
        self._error_lbl.setStyleSheet('color: #e05252;')
        self._error_lbl.setWordWrap(True)
        f.addRow(self._error_lbl)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._try_accept)
        btns.rejected.connect(self.reject)
        f.addRow(btns)

    def _try_accept(self):
        name = self.name_edit.text().strip()
        if not name:
            self._error_lbl.setText('New filename is required.')
            return
        if not _DUPLICATE_NAME_RE.match(name):
            self._error_lbl.setText(
                'Filename may only contain letters, digits, underscores and hyphens, '
                'must start with a letter, and may end in .mod, .ctl, or no extension. '
                'Path separators and ".." are not allowed.'
            )
            return
        self._error_lbl.setText('')
        self.accept()

    def _select_description_when_focused(self):
        """Wire selectAll() to focus events on the description field so users
        can replace the inherited text with a single keystroke."""
        original_focus_in = self.desc_edit.focusInEvent

        def _focus_in(event):
            original_focus_in(event)
            self.desc_edit.selectAll()

        self.desc_edit.focusInEvent = _focus_in
