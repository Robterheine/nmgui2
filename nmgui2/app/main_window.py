import sys, threading, logging
from pathlib import Path
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QLabel, QApplication, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, QByteArray
from PyQt6.QtGui import QKeySequence, QColor, QAction
from .constants import IS_WIN, IS_MAC, APP_VERSION
from .theme import C, T, THEMES, _active_theme, set_active_theme, build_stylesheet, apply_palette
from .config import load_settings, save_settings
from .tools import launch_rstudio
from ..widgets._icons import _make_logo_pixmap, _make_nav_icon
from ..tabs.models import ModelsTab
from ..tabs.tree import AncestryTreeWidget
from ..tabs.evaluation import EvaluationTab
from ..tabs.vpc import VPCTab
from ..tabs.uncertainty import ParameterUncertaintyTab
from ..tabs.history import RunHistoryTab
from ..tabs.settings import SettingsTab
from ..dialogs.about import AboutDialog
from ..dialogs.shortcuts import KeyboardShortcutsDialog

try:
    import pyqtgraph as pg
    HAS_PG = True
except ImportError:
    HAS_PG = False

try:
    import numpy as np
    HAS_NP = True
except ImportError:
    HAS_NP = False

_log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('NMGUI')
        self._current_theme = 'dark'
        self._selected_model = None
        self._build_menu()
        self._build_ui()
        self._restore_geometry()
        self._check_deps()
        QTimer.singleShot(3000, self._version_check)

    def _restore_geometry(self):
        s = load_settings()
        geom = s.get('window_geometry')
        if geom:
            try:
                self.restoreGeometry(QByteArray.fromHex(bytes(geom, 'ascii')))
                return
            except Exception:
                pass
        self.resize(1300, 840)
        spl_sizes = s.get('splitter_sizes')
        if spl_sizes and hasattr(self, 'models_tab'):
            try:
                from PyQt6.QtWidgets import QSplitter
                spl = self.models_tab.findChild(QSplitter)
                if spl:
                    spl.setSizes(spl_sizes)
            except Exception:
                pass

    def closeEvent(self, event):
        s = load_settings()
        s['window_geometry'] = bytes(self.saveGeometry().toHex()).decode('ascii')
        try:
            from PyQt6.QtWidgets import QSplitter
            spl = self.models_tab.findChild(QSplitter)
            if spl:
                s['splitter_sizes'] = spl.sizes()
        except Exception:
            pass
        save_settings(s)
        super().closeEvent(event)

    def _build_menu(self):
        mb = self.menuBar()
        file_menu = mb.addMenu('File')
        open_act = QAction('Open Directory…', self)
        open_act.setShortcut(QKeySequence('Ctrl+O'))
        open_act.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        open_act.triggered.connect(self._open_directory)
        rescan_act = QAction('Rescan', self)
        rescan_act.setShortcut(QKeySequence('Ctrl+R'))
        rescan_act.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        rescan_act.triggered.connect(self._rescan)
        quit_act = QAction('Quit', self)
        quit_act.setShortcut(QKeySequence('Ctrl+Q'))
        quit_act.triggered.connect(QApplication.instance().quit)
        file_menu.addAction(open_act)
        file_menu.addAction(rescan_act)
        file_menu.addSeparator()
        file_menu.addAction(quit_act)

        help_menu = mb.addMenu('Help')
        shortcuts_act = QAction('Keyboard Shortcuts…', self)
        shortcuts_act.setShortcut(QKeySequence('F1'))
        shortcuts_act.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcuts_act.triggered.connect(self._show_shortcuts)
        about_act = QAction('About NMGUI…', self)
        about_act.triggered.connect(self._show_about)
        github_act = QAction('GitHub Repository…', self)
        github_act.triggered.connect(
            lambda: __import__('webbrowser').open('https://github.com/robterheine/NMGUI2'))
        help_menu.addAction(shortcuts_act)
        help_menu.addSeparator()
        help_menu.addAction(about_act)
        help_menu.addSeparator()
        help_menu.addAction(github_act)

        help_shortcut = QAction(self)
        help_shortcut.setShortcut(QKeySequence('Ctrl+/'))
        help_shortcut.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        help_shortcut.triggered.connect(self._show_shortcuts)
        self.addAction(help_shortcut)

        theme_shortcut = QAction(self)
        theme_shortcut.setShortcut(QKeySequence('Ctrl+Shift+T'))
        theme_shortcut.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        theme_shortcut.triggered.connect(self._toggle_theme)
        self.addAction(theme_shortcut)

        for i in range(7):
            act = QAction(self)
            act.setShortcut(QKeySequence(f'Ctrl+{i+1}'))
            act.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            act.triggered.connect(lambda _, n=i: self._nav_to(n))
            self.addAction(act)

    def _open_directory(self): self._nav_to(0); self.models_tab._browse()
    def _rescan(self):         self._nav_to(0); self.models_tab._scan()
    def _show_about(self):     AboutDialog(self).exec()
    def _show_shortcuts(self): KeyboardShortcutsDialog(self).show()

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        header = QWidget()
        header.setObjectName('appHeader')
        header.setFixedHeight(48)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(10)
        logo_lbl = QLabel()
        logo_lbl.setPixmap(_make_logo_pixmap(28))
        logo_lbl.setFixedSize(28, 28)
        name_lbl = QLabel('NMGUI')
        name_lbl.setStyleSheet(
            'font-size:16px;font-weight:700;letter-spacing:-.5px;background:transparent;')
        ver_lbl = QLabel(f'v{APP_VERSION}')
        ver_lbl.setStyleSheet(
            f'font-size:11px;color:{C.fg2};margin-top:3px;background:transparent;')
        self._ctx_lbl = QLabel('')
        self._ctx_lbl.setObjectName('ctxLabel')
        self._rs_btn = QPushButton('Open RStudio')
        self._rs_btn.setToolTip('Open RStudio with the current model directory as project')
        self._rs_btn.setFixedHeight(28)
        self._rs_btn.setEnabled(False)
        self._rs_btn.clicked.connect(self._launch_rstudio_global)
        hl.addWidget(logo_lbl)
        hl.addWidget(name_lbl)
        hl.addWidget(ver_lbl)
        hl.addSpacing(16)
        hl.addWidget(self._ctx_lbl, 1)
        about_btn = QPushButton('? About')
        about_btn.setFixedHeight(28)
        about_btn.setToolTip('About NMGUI')
        about_btn.clicked.connect(self._show_about)
        hl.addWidget(about_btn)
        hl.addWidget(self._rs_btn)
        root.addWidget(header)

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setObjectName('hairlineSep')
        root.addWidget(sep)

        # Body: sidebar + stacked pages
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = QWidget()
        self._sidebar.setFixedWidth(82)
        self._sidebar.setObjectName('sidebar')
        sv = QVBoxLayout(self._sidebar)
        sv.setContentsMargins(0, 8, 0, 8)
        sv.setSpacing(2)

        self._nav_items = []
        self._nav_icon_lbls = []
        nav_defs = [
            ('Models',      'models',      'Ctrl+1'),
            ('Tree',        'tree',        'Ctrl+2'),
            ('Evaluation',  'evaluation',  'Ctrl+3'),
            ('VPC',         'vpc',         'Ctrl+4'),
            ('Uncertainty', 'uncertainty', 'Ctrl+5'),
            ('History',     'history',     'Ctrl+6'),
            ('Settings',    'settings',    'Ctrl+7'),
        ]
        for i, (label, icon_name, shortcut) in enumerate(nav_defs):
            btn = QPushButton()
            btn.setObjectName('navBtn')
            btn.setCheckable(True)
            btn.setFixedHeight(68)
            btn.setFixedWidth(82)
            btn.setToolTip(f'{label}  ({shortcut})')
            bv = QVBoxLayout(btn)
            bv.setContentsMargins(4, 8, 4, 6)
            bv.setSpacing(3)
            icon_lbl = QLabel()
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setFixedHeight(28)
            icon_lbl.setPixmap(_make_nav_icon(icon_name, 28, C.fg))
            icon_lbl.setStyleSheet('background:transparent;')
            text_lbl = QLabel(label)
            text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text_lbl.setStyleSheet('background:transparent;')
            pal = text_lbl.palette()
            pal.setColor(pal.ColorRole.WindowText, QColor(C.fg))
            text_lbl.setPalette(pal)
            f = text_lbl.font()
            f.setPointSize(8)
            text_lbl.setFont(f)
            bv.addWidget(icon_lbl)
            bv.addWidget(text_lbl)
            btn.clicked.connect(lambda _, n=i: self._nav_to(n))
            sv.addWidget(btn)
            self._nav_items.append(btn)
            self._nav_icon_lbls.append((icon_lbl, icon_name, text_lbl))

        sv.addStretch()
        body.addWidget(self._sidebar)

        ssep = QWidget()
        ssep.setFixedWidth(1)
        ssep.setObjectName('hairlineSep')
        body.addWidget(ssep)

        self._stack = QStackedWidget()
        self.models_tab      = ModelsTab()
        self.tree_tab        = AncestryTreeWidget()
        self.eval_tab        = EvaluationTab()
        self.vpc_tab         = VPCTab()
        self.uncertainty_tab = ParameterUncertaintyTab()
        self.history_tab     = RunHistoryTab()
        self.settings_tab    = SettingsTab()
        self._stack.addWidget(self.models_tab)
        self._stack.addWidget(self.tree_tab)
        self._stack.addWidget(self.eval_tab)
        self._stack.addWidget(self.vpc_tab)
        self._stack.addWidget(self.uncertainty_tab)
        self._stack.addWidget(self.history_tab)
        self._stack.addWidget(self.settings_tab)
        body.addWidget(self._stack, 1)

        body_w = QWidget()
        body_w.setLayout(body)
        root.addWidget(body_w, 1)

        self.models_tab.status_msg.connect(self.statusBar().showMessage)
        self.eval_tab.status_msg.connect(self.statusBar().showMessage)
        self.vpc_tab.status_msg.connect(self.statusBar().showMessage)
        self.uncertainty_tab.status_msg.connect(self.statusBar().showMessage)
        self.models_tab.model_selected.connect(self._on_model_selected)
        self.models_tab.model_selected.connect(self._on_model_selected_for_tree)
        self.tree_tab.model_clicked.connect(self._tree_model_clicked)
        self.settings_tab.theme_changed.connect(self._apply_theme)

        self.setCentralWidget(central)
        self.statusBar().showMessage('Ready')
        self._nav_to(0)

    def _nav_to(self, index):
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_items):
            btn.setChecked(i == index)
        if self._selected_model:
            if index == 2 and self.eval_tab._model is not self._selected_model:
                self.eval_tab.load_model(self._selected_model)
            elif index == 3 and self.vpc_tab._model is not self._selected_model:
                self.vpc_tab.load_model(self._selected_model)
            elif index == 4 and self.uncertainty_tab._model is not self._selected_model:
                self.uncertainty_tab.load_model(self._selected_model)
        if index == 1:
            self._refresh_tree()
        elif index == 5:
            self.history_tab.load()

    def _refresh_tree(self):
        models = self.models_tab._all_models
        stem   = self._selected_model.get('stem') if self._selected_model else None
        self.tree_tab.load(models, current_stem=stem)

    def _tree_model_clicked(self, stem):
        for m in self.models_tab._all_models:
            if m['stem'] == stem:
                self._on_model_selected(m)
                for row in range(self.models_tab.table.rowCount()):
                    item = self.models_tab.table.item(row, 1)
                    if item and item.text() == stem:
                        self.models_tab.table.setCurrentCell(row, 1)
                        break
                self._nav_to(0)
                break

    def _on_model_selected_for_tree(self, model):
        self.tree_tab.set_current(model.get('stem'))

    def _on_model_selected(self, model):
        self._selected_model = model
        stem = model.get('stem', '')
        directory = Path(model.get('path', '')).parent.name
        self._ctx_lbl.setText(f'{directory}  /  {stem}')
        self._rs_btn.setEnabled(True)
        self.eval_tab.load_model(model)
        self.vpc_tab.load_model(model)

    def _launch_rstudio_global(self):
        directory = self.models_tab.current_directory()
        rs_path = load_settings().get('rstudio_path', '')
        err = launch_rstudio(directory, rs_path)
        if err:
            QMessageBox.warning(self, 'RStudio', err)
        else:
            self.statusBar().showMessage(f'RStudio opened — {Path(directory).name}')

    def _apply_theme(self, theme_name):
        set_active_theme(theme_name)
        t = THEMES[theme_name]
        if HAS_PG:
            pg.setConfigOptions(background=t['pg_bg'], foreground=t['pg_fg'])
        apply_palette(QApplication.instance(), theme_name)
        QApplication.instance().setStyleSheet(build_stylesheet(theme_name))
        bg = t['pg_bg']
        fg = t['pg_fg']
        for w in (
            self.eval_tab.gof, self.eval_tab.indfit,
            self.eval_tab.waterfall, self.eval_tab.conv,
            self.eval_tab.cwres_hist, self.eval_tab.qq_plot,
            self.eval_tab.eta_cov, self.eval_tab.data_explorer,
            self.tree_tab,
        ):
            if hasattr(w, 'set_theme'):
                w.set_theme(bg, fg)
        if self.tree_tab._models:
            self.tree_tab._rebuild()
        from ..widgets.collapsible import CollapsibleCard
        from ..widgets.highlighter import NMHighlighter
        for card in self.findChildren(CollapsibleCard):
            card.refresh_theme()
        for hl in self.findChildren(NMHighlighter):
            hl.rebuild_rules()
            hl.rehighlight()
        for icon_lbl, icon_name, text_lbl in self._nav_icon_lbls:
            icon_lbl.setPixmap(_make_nav_icon(icon_name, 28, C.fg))
            pal = text_lbl.palette()
            pal.setColor(pal.ColorRole.WindowText, QColor(C.fg))
            text_lbl.setPalette(pal)
        self.statusBar().showMessage(f'Theme: {theme_name.capitalize()}')

    def _toggle_theme(self):
        from .theme import _active_theme as _cur
        new_theme = 'light' if _cur == 'dark' else 'dark'
        self._apply_theme(new_theme)
        self.settings_tab.theme_combo.setCurrentText(new_theme.capitalize())
        s = load_settings()
        s['theme'] = new_theme
        save_settings(s)

    def _check_deps(self):
        missing = []
        if not HAS_NP:
            missing.append('numpy')
        if not HAS_PG:
            missing.append('pyqtgraph')
        if missing:
            self.statusBar().showMessage(
                f'Missing dependencies: pip3 install {" ".join(missing)}')

    def _version_check(self):
        def _fetch():
            try:
                import urllib.request, json as _j
                url = 'https://api.github.com/repos/robterheine/NMGUI2/releases/latest'
                with urllib.request.urlopen(url, timeout=5) as r:
                    tag = _j.loads(r.read()).get('tag_name', '').lstrip('v')
                def _tup(v):
                    parts = []
                    for p in v.split('.'):
                        try: parts.append(int(p))
                        except ValueError: parts.append(0)
                    return tuple(parts)
                if tag and _tup(tag) > _tup(APP_VERSION):
                    QTimer.singleShot(0, lambda: self.statusBar().showMessage(
                        f'Update available: v{tag}  —  github.com/robterheine/NMGUI2/releases'))
            except Exception:
                pass
        threading.Thread(target=_fetch, daemon=True).start()
