THEMES = {
    'dark': {
        'bg':        '#1a1a20',
        'bg2':       '#22222c',
        'bg3':       '#2a2a36',
        'bg4':       '#32323f',
        'border':    '#7a7a94',
        'fg':        '#dde0ee',
        'fg2':       '#9a9db8',
        'fg3':       '#6a6d88',
        'accent':    '#4c8aff',
        'accent_h':  '#6aa0ff',
        'accent_bg': '#1a2a4a',
        'green':     '#3ec97a',
        'red':       '#e85555',
        'orange':    '#e89540',
        'yellow':    '#d4c060',
        'star':      '#f0c040',
        'sel':       '#1e3a5a',
        'pg_bg':     '#1a1a20',
        'pg_fg':     '#9a9db8',
    },
    'light': {
        'bg':        '#f2f2f7',
        'bg2':       '#ffffff',
        'bg3':       '#e8e8f0',
        'bg4':       '#d8d8e8',
        'border':    '#7878a0',
        'fg':        '#1a1a2e',
        'fg2':       '#5a5a70',
        'fg3':       '#9090a0',
        'accent':    '#2563eb',
        'accent_h':  '#1d4ed8',
        'accent_bg': '#eff6ff',
        'green':     '#16a34a',
        'red':       '#dc2626',
        'orange':    '#d97706',
        'yellow':    '#b45309',
        'star':      '#d97706',
        'sel':       '#dbeafe',
        'pg_bg':     '#ffffff',
        'pg_fg':     '#1a1a2e',
    }
}

_active_theme = 'dark'


def T(key):
    return THEMES[_active_theme][key]


class _ThemeColors:
    """Mutable singleton — attributes update live on theme change."""
    def _apply(self, theme_name):
        t = THEMES[theme_name]
        self.bg = t['bg'];    self.bg2 = t['bg2'];   self.bg3 = t['bg3']
        self.border = t['border']; self.fg = t['fg']; self.fg2 = t['fg2']
        self.green = t['green']; self.red = t['red']; self.orange = t['orange']
        self.blue = t['accent']; self.yellow = t['yellow']; self.star = t['star']
        self.stale = t['orange']


C = _ThemeColors()
C._apply('dark')


def set_active_theme(name):
    global _active_theme
    _active_theme = name
    C._apply(name)


def build_stylesheet(theme_name='dark'):
    t = THEMES[theme_name]
    return f"""
/* ── Base ─────────────────────────────────────── */
QMainWindow, QWidget, QDialog {{
    background: {t['bg']}; color: {t['fg']};
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 13px;
}}

/* ── Tabs ─────────────────────────────────────── */
QTabBar::tab {{
    background: {t['bg2']};
    color: {t['fg2']};
    padding: 7px 18px;
    border: 1px solid {t['border']};
    border-bottom: none;
    margin-right: 1px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    font-size: 13px;
}}
QTabBar::tab:selected {{
    background: {t['bg']};
    color: {t['fg']};
    border-bottom: 2px solid {t['accent']};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{ color: {t['fg']}; background: {t['bg3']}; }}

/* ── Tables ───────────────────────────────────── */
QTableWidget, QListWidget {{
    background: {t['bg2']};
    color: {t['fg']};
    gridline-color: {t['bg3']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    selection-background-color: {t['sel']};
    selection-color: {t['fg']};
    alternate-background-color: {t['bg3']};
    outline: none;
}}
QTableWidget::item {{ padding: 3px 6px; border: none; }}
QTableWidget::item:selected {{ background: {t['sel']}; color: {t['fg']}; }}
QHeaderView {{ background: {t['bg2']}; border: none; }}
QHeaderView::section {{
    background: {t['bg3']};
    color: {t['fg2']};
    padding: 5px 8px;
    border: none;
    border-right: 1px solid {t['border']};
    border-bottom: 1px solid {t['border']};
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QHeaderView::section:first {{ border-top-left-radius: 5px; }}

/* ── Buttons ──────────────────────────────────── */
QPushButton {{
    background: {t['bg3']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    padding: 5px 16px;
    min-width: 72px;
    border-radius: 5px;
    font-size: 13px;
}}
QPushButton:hover {{ background: {t['bg4']}; border-color: {t['fg3']}; }}
QPushButton:pressed {{ background: {t['accent_bg']}; border-color: {t['accent']}; }}
QPushButton:disabled {{ color: {t['fg3']}; }}
QPushButton#primary {{
    background: {t['accent']};
    color: #ffffff;
    border: none;
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {t['accent_h']}; }}
QPushButton#danger {{
    background: transparent;
    color: {t['red']};
    border: 1px solid {t['red']};
}}
QPushButton#danger:hover {{ background: {t['red']}; color: #fff; }}

/* ── Inputs ───────────────────────────────────── */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {t['bg2']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    padding: 4px 8px;
    border-radius: 5px;
    selection-background-color: {t['accent_bg']};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {t['accent']};
}}
QComboBox {{
    background: {t['bg2']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    padding: 4px 8px;
    border-radius: 5px;
}}
QComboBox:focus {{ border-color: {t['accent']}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{ width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {t['bg2']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    selection-background-color: {t['sel']};
}}

/* ── Scrollbars ───────────────────────────────── */
QScrollBar:vertical {{
    background: {t['bg']};
    width: 8px;
    margin: 0;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {t['border']};
    min-height: 24px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{ background: {t['fg3']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {t['bg']};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {t['border']};
    min-width: 24px;
    border-radius: 4px;
}}

/* ── Splitter ─────────────────────────────────── */
QSplitter::handle {{
    background: {t['border']};
}}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

/* ── Misc ─────────────────────────────────────── */
QStatusBar {{
    background: {t['bg2']};
    color: {t['fg2']};
    border-top: 1px solid {t['border']};
    font-size: 12px;
    padding: 2px 8px;
}}
QGroupBox {{
    border: 1px solid {t['border']};
    border-radius: 6px;
    margin-top: 10px;
    padding: 12px 8px 8px 8px;
    color: {t['fg2']};
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}}
QLabel {{ color: {t['fg']}; }}
QLabel#muted {{ color: {t['fg2']}; font-size: 12px; }}
QLabel#section {{ color: {t['fg2']}; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
QScrollArea {{ background: {t['bg']}; border: none; }}
QScrollArea > QWidget > QWidget {{ background: {t['bg']}; }}
QCheckBox {{ color: {t['fg']}; spacing: 6px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {t['border']};
    border-radius: 3px;
    background: {t['bg2']};
}}
QCheckBox::indicator:checked {{
    background: {t['accent']};
    border-color: {t['accent']};
}}
QRadioButton {{ color: {t['fg']}; spacing: 6px; }}
QRadioButton::indicator {{
    width: 14px; height: 14px;
    border: 2px solid {t['fg3']};
    border-radius: 8px;
    background: {t['bg2']};
}}
QRadioButton::indicator:hover {{
    border-color: {t['fg2']};
}}
QRadioButton::indicator:checked {{
    background: {t['accent']};
    border-color: {t['accent']};
}}
QMenu {{
    background: {t['bg2']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 20px;
    border-radius: 4px;
}}
QMenu::item:selected {{ background: {t['sel']}; }}
QMenu::separator {{
    height: 1px;
    background: {t['border']};
    margin: 4px 8px;
}}
QToolTip {{
    background: {t['bg3']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}}
/* ── Evaluation pill nav ──────────────────────── */
QWidget#pillBar {{
    background: {t['bg2']};
    border-bottom: 1px solid {t['border']};
}}
QWidget#evalTopBar {{
    background: {t['bg2']};
    border-bottom: 1px solid {t['border']};
}}
QPushButton#pillBtn {{
    background: {t['bg3']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    color: {t['fg2']};
    padding: 3px 14px;
    font-size: 12px;
    min-width: 0;
}}
QPushButton#pillBtn:hover {{
    background: {t['bg4']};
    color: {t['fg']};
    border-color: {t['fg2']};
}}
QPushButton#pillBtn:checked {{
    background: {t['accent']};
    color: #ffffff;
    font-weight: 600;
    border-color: {t['accent']};
}}
QPushButton#filterBtn {{
    background: {t['bg3']};
    border: 1px solid {t['border']};
    border-radius: 4px;
    color: {t['fg2']};
    padding: 2px 10px;
    font-size: 11px;
    min-width: 50px;
}}
QPushButton#filterBtn:hover {{
    background: {t['bg4']};
    color: {t['fg']};
}}
QPushButton#filterBtn:checked {{
    background: {t['accent']};
    color: #ffffff;
    border-color: {t['accent']};
}}
QPushButton#innerPillBtn {{
    background: {t['bg2']};
    border: 1px solid {t['border']};
    border-radius: 5px;
    color: {t['fg2']};
    padding: 2px 10px;
    font-size: 11px;
    min-width: 0;
}}
QPushButton#innerPillBtn:hover {{
    background: {t['bg3']};
    color: {t['fg']};
    border-color: {t['fg2']};
}}
QPushButton#innerPillBtn:checked {{
    background: {t['accent']};
    color: #ffffff;
    border-color: {t['accent']};
    font-weight: 600;
}}
/* ── Sidebar navigation ───────────────────────── */
QWidget#sidebar {{
    background: {t['bg3']};
    border-right: 1px solid {t['border']};
}}
QPushButton#navBtn {{
    background: transparent;
    border: none;
    border-radius: 8px;
    color: {t['fg2']};
    padding: 0;
    margin: 2px 6px;
}}
QPushButton#navBtn:hover {{
    background: {t['bg3']};
    color: {t['fg']};
}}
QPushButton#navBtn:checked {{
    background: {t['accent_bg']};
    color: {t['accent']};
    border-left: 3px solid {t['accent']};
}}
QPushButton#navBtn QLabel {{
    background: transparent;
    color: {t['fg2']};
}}
QPushButton#navBtn:hover QLabel {{
    color: {t['fg']};
}}
QPushButton#navBtn:checked QLabel {{
    color: {t['accent']};
}}
QWidget#appHeader {{
    background: {t['bg2']};
    border-bottom: 1px solid {t['border']};
}}
QWidget#appHeader QLabel {{
    background: transparent;
}}
QMenuBar {{
    background: {t['bg2']};
    color: {t['fg']};
    border-bottom: 1px solid {t['border']};
    padding: 2px 4px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{
    background: {t['bg3']};
}}
"""
