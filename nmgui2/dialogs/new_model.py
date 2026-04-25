"""Dialog for creating a new blank NONMEM model file."""

import re
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QLabel,
    QDialogButtonBox, QPlainTextEdit, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ..app.model_templates import template_names, render


# Stem must start with a letter, contain only alphanumeric / underscore / hyphen,
# no extension, no path separators.
_STEM_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_\-]*$')


class _PreviewDialog(QDialog):
    """Read-only preview of the rendered template text."""
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Template preview')
        self.resize(640, 540)
        v = QVBoxLayout(self)
        editor = QPlainTextEdit(text)
        editor.setReadOnly(True)
        f = QFont('Menlo' if __import__('sys').platform == 'darwin' else 'Courier New')
        f.setPointSize(10)
        editor.setFont(f)
        v.addWidget(editor)
        close = QPushButton('Close')
        close.clicked.connect(self.accept)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(close)
        v.addLayout(row)


class NewModelDialog(QDialog):
    """
    Ask the user for:
      - Model stem (filename without .mod extension)
      - Template to use
      - $DATA path (with optional Browse button)

    On accept, call .stem(), .template(), .data_path() to retrieve values.
    """

    def __init__(self, default_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle('New Model')
        self.setMinimumWidth(440)
        self._default_dir = default_dir
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setSpacing(12)

        form = QFormLayout()
        form.setVerticalSpacing(8)
        form.setHorizontalSpacing(10)

        # ── Stem ──────────────────────────────────────────────────────────────
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText('e.g. run1  or  pk_base')
        self._name_edit.setToolTip(
            'File name without extension.\n'
            'Must start with a letter; may contain letters, digits, _ and -.'
        )
        form.addRow('Model name:', self._name_edit)

        # Will-write-to label (greyed)
        self._path_lbl = QLabel()
        self._path_lbl.setObjectName('muted')
        self._path_lbl.setWordWrap(True)
        self._name_edit.textChanged.connect(self._update_path_label)
        form.addRow('', self._path_lbl)

        # ── Template ──────────────────────────────────────────────────────────
        self._template_cb = QComboBox()
        for name in template_names():
            self._template_cb.addItem(name)
        self._template_cb.setToolTip('NONMEM structural model template to start from.')
        self._template_cb.currentTextChanged.connect(self._update_path_label)

        preview_btn = QPushButton('Preview…')
        preview_btn.setToolTip('Preview the rendered template before creating the file.')
        preview_btn.clicked.connect(self._show_preview)
        preview_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        tmpl_row = QHBoxLayout(); tmpl_row.setSpacing(6)
        tmpl_row.addWidget(self._template_cb, 1)
        tmpl_row.addWidget(preview_btn)
        form.addRow('Template:', tmpl_row)

        # ── $DATA path ────────────────────────────────────────────────────────
        self._data_edit = QLineEdit()
        self._data_edit.setPlaceholderText('../data.csv')
        self._data_edit.setToolTip('Path written into the $DATA record (relative or absolute).')

        data_browse = QPushButton('Browse…')
        data_browse.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        data_browse.clicked.connect(self._browse_data)

        data_row = QHBoxLayout(); data_row.setSpacing(6)
        data_row.addWidget(self._data_edit, 1)
        data_row.addWidget(data_browse)
        form.addRow('$DATA path:', data_row)

        v.addLayout(form)

        # ── Validation error label ────────────────────────────────────────────
        self._error_lbl = QLabel('')
        self._error_lbl.setObjectName('errorLabel')
        self._error_lbl.setStyleSheet('color: #e05252;')
        self._error_lbl.setWordWrap(True)
        v.addWidget(self._error_lbl)

        # ── Buttons ───────────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._try_accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

        self._update_path_label()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _update_path_label(self):
        stem = self._name_edit.text().strip()
        if stem:
            dest = str(Path(self._default_dir) / f'{stem}.mod')
            self._path_lbl.setText(f'Will create: {dest}')
        else:
            self._path_lbl.setText('')

    def _browse_data(self):
        from PyQt6.QtWidgets import QFileDialog
        f, _ = QFileDialog.getOpenFileName(
            self, 'Select dataset', self._default_dir,
            'Data files (*.csv *.tab *.dat *.txt);;All files (*)'
        )
        if f:
            # Store relative path when inside default_dir, otherwise absolute
            try:
                rel = Path(f).relative_to(self._default_dir)
                self._data_edit.setText(str(rel))
            except ValueError:
                self._data_edit.setText(f)

    def _show_preview(self):
        stem = self._name_edit.text().strip() or 'model'
        data = self._data_edit.text().strip() or '../data.csv'
        text = render(self._template_cb.currentText(), stem, data)
        dlg  = _PreviewDialog(text, self)
        dlg.exec()

    def _try_accept(self):
        stem = self._name_edit.text().strip()
        if not stem:
            self._error_lbl.setText('Model name is required.')
            return
        if not _STEM_RE.match(stem):
            self._error_lbl.setText(
                'Model name may only contain letters, digits, underscores and hyphens, '
                'and must start with a letter.'
            )
            return
        self._error_lbl.setText('')
        self.accept()

    # ── Public accessors ──────────────────────────────────────────────────────

    def stem(self) -> str:
        return self._name_edit.text().strip()

    def template(self) -> str:
        return self._template_cb.currentText()

    def data_path(self) -> str:
        return self._data_edit.text().strip() or '../data.csv'
