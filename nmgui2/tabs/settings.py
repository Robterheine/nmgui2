from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
                              QLineEdit, QPushButton, QComboBox, QListWidget, QFileDialog,
                              QInputDialog, QMessageBox, QFormLayout, QGridLayout)
from PyQt6.QtCore import pyqtSignal

from ..app.theme import C, T
from ..app.constants import IS_WIN, IS_MAC
from ..app.config import load_settings, save_settings, load_bookmarks, save_bookmarks


class SettingsTab(QWidget):
    theme_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self); v.setContentsMargins(20, 20, 20, 20); v.setSpacing(16)
        s = load_settings()

        # ── Appearance ────────────────────────────────────────────────────────
        appear_grp = QGroupBox('Appearance')
        ag = QHBoxLayout(appear_grp); ag.setContentsMargins(12, 16, 12, 12)
        ag.addWidget(QLabel('Theme:'))
        self.theme_combo = QComboBox(); self.theme_combo.addItems(['Dark', 'Light'])
        saved_theme = (s.get('theme') or 'dark').capitalize()
        self.theme_combo.setCurrentText(saved_theme); self.theme_combo.setFixedWidth(120)
        self.theme_combo.currentTextChanged.connect(
            lambda t: self.theme_changed.emit(t.lower()))
        ag.addWidget(self.theme_combo); ag.addStretch()
        v.addWidget(appear_grp)

        # ── Paths ─────────────────────────────────────────────────────────────
        paths_grp = QGroupBox('Paths')
        pg = QGridLayout(paths_grp); pg.setContentsMargins(12, 16, 12, 12); pg.setSpacing(8)
        pg.setColumnStretch(1, 1)
        self.wd_edit  = QLineEdit(s.get('working_directory', ''))
        self.psn_edit = QLineEdit(s.get('psn_path', '')); self.psn_edit.setPlaceholderText('Leave blank — auto-detect from PATH')
        self.nm_edit  = QLineEdit(s.get('nonmem_path', '')); self.nm_edit.setPlaceholderText('Leave blank — auto-detect from PATH')
        self.rs_edit  = QLineEdit(s.get('rstudio_path', '')); self.rs_edit.setPlaceholderText('Leave blank — auto-detect (RStudio on PATH or default install)')
        wd_btn = QPushButton('Browse…'); wd_btn.setFixedWidth(90)
        wd_btn.clicked.connect(self._browse_wd)
        rs_btn = QPushButton('Browse…'); rs_btn.setFixedWidth(90)
        rs_btn.clicked.connect(self._browse_rs)
        pg.addWidget(QLabel('Default directory:'), 0, 0); pg.addWidget(self.wd_edit, 0, 1); pg.addWidget(wd_btn, 0, 2)
        pg.addWidget(QLabel('PsN bin path:'),      1, 0); pg.addWidget(self.psn_edit, 1, 1, 1, 2)
        pg.addWidget(QLabel('NONMEM bin path:'),   2, 0); pg.addWidget(self.nm_edit,  2, 1, 1, 2)
        pg.addWidget(QLabel('RStudio path:'),      3, 0); pg.addWidget(self.rs_edit,  3, 1); pg.addWidget(rs_btn, 3, 2)
        v.addWidget(paths_grp)

        # ── Bookmarks ─────────────────────────────────────────────────────────
        bm_grp = QGroupBox('Bookmarks')
        bv = QVBoxLayout(bm_grp); bv.setContentsMargins(12, 16, 12, 12); bv.setSpacing(8)
        self.bm_list = QListWidget(); self.bm_list.setMaximumHeight(180)
        for b in load_bookmarks():
            self.bm_list.addItem(f"{b.get('name', '')}  —  {b.get('path', '')}")
        rem_btn = QPushButton('Remove selected bookmark')
        rem_btn.setObjectName('danger'); rem_btn.setFixedWidth(200)
        rem_btn.clicked.connect(self._remove_bm)
        bv.addWidget(self.bm_list)
        rem_row = QHBoxLayout(); rem_row.addWidget(rem_btn); rem_row.addStretch()
        bv.addLayout(rem_row)
        v.addWidget(bm_grp)

        # ── Save ─────────────────────────────────────────────────────────────
        save_row = QHBoxLayout()
        save_btn = QPushButton('Save settings'); save_btn.setObjectName('primary')
        save_btn.setFixedWidth(140); save_btn.clicked.connect(self._save)
        save_row.addWidget(save_btn); save_row.addStretch()
        v.addLayout(save_row)
        v.addStretch()

    def _browse_wd(self):
        d = QFileDialog.getExistingDirectory(self, 'Select directory', self.wd_edit.text())
        if d: self.wd_edit.setText(d)

    def _browse_rs(self):
        if IS_WIN:
            f, _ = QFileDialog.getOpenFileName(self, 'Select RStudio executable',
                r'C:\Program Files\Posit\RStudio', 'Executables (*.exe)')
        elif IS_MAC:
            f, _ = QFileDialog.getOpenFileName(self, 'Select RStudio.app',
                '/Applications', 'Applications (*.app);;All files (*)')
        else:
            f, _ = QFileDialog.getOpenFileName(self, 'Select RStudio executable',
                '/usr/bin', 'All files (*)')
        if f: self.rs_edit.setText(f)

    def _save(self):
        s = load_settings()
        s['working_directory'] = self.wd_edit.text().strip()
        s['psn_path']          = self.psn_edit.text().strip()
        s['nonmem_path']       = self.nm_edit.text().strip()
        s['rstudio_path']      = self.rs_edit.text().strip()
        s['theme']             = self.theme_combo.currentText().lower()
        save_settings(s); QMessageBox.information(self, 'Saved', 'Settings saved.')

    def _remove_bm(self):
        row = self.bm_list.currentRow()
        if row < 0: return
        bms = load_bookmarks()
        if row < len(bms): bms.pop(row)
        save_bookmarks(bms); self.bm_list.takeItem(row)
