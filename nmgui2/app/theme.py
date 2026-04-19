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
        'syn_record':  '#569cd6',
        'syn_flow':    '#dcdcaa',
        'syn_builtin': '#9cdcfe',
        'syn_block':   '#ce9178',
        'syn_comment': '#6a9955',
        'syn_number':  '#b5cea8',
        'syn_string':  '#ce9178',
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
        'syn_record':  '#0000c0',
        'syn_flow':    '#7a5900',
        'syn_builtin': '#0d6e6e',
        'syn_block':   '#a03000',
        'syn_comment': '#098600',
        'syn_number':  '#0a6e3c',
        'syn_string':  '#a31515',
    }
}

_active_theme = 'dark'


def T(key):
    return THEMES[_active_theme][key]


class _ThemeColors:
    """Mutable singleton — attributes update live on theme change."""
    def _apply(self, theme_name):
        t = THEMES[theme_name]
        self.bg = t['bg'];    self.bg2 = t['bg2'];   self.bg3 = t['bg3'];  self.bg4 = t['bg4']
        self.border = t['border']; self.fg = t['fg']; self.fg2 = t['fg2']; self.fg3 = t['fg3']
        self.green = t['green']; self.red = t['red']; self.orange = t['orange']
        self.blue = t['accent']; self.yellow = t['yellow']; self.star = t['star']
        self.stale = t['orange']


C = _ThemeColors()
C._apply('dark')


def set_active_theme(name):
    global _active_theme
    _active_theme = name
    C._apply(name)


_arrow_cache_dir = None

def _arrow_png_uri(color_hex, direction):
    """Render a triangle arrow to a cached PNG file and return a url()-safe path.

    Data URIs work for QComboBox::down-arrow but are flaky for
    QSpinBox::up-arrow/::down-arrow across Qt versions — the image silently
    fails to render. Writing to a tmp file and referencing by path is
    reliable for all sub-controls.
    """
    import hashlib, tempfile, os
    from PyQt6.QtCore import Qt, QPointF
    from PyQt6.QtGui import QPixmap, QPainter, QPolygonF, QColor

    global _arrow_cache_dir
    if _arrow_cache_dir is None:
        _arrow_cache_dir = os.path.join(tempfile.gettempdir(), 'nmgui2_arrows')
        os.makedirs(_arrow_cache_dir, exist_ok=True)

    key = hashlib.md5(f'{color_hex}-{direction}-v2'.encode()).hexdigest()[:10]
    path = os.path.join(_arrow_cache_dir, f'arrow_{direction}_{key}.png')
    if not os.path.exists(path):
        w, h = 20, 14   # 2x for HiDPI
        pm = QPixmap(w, h)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color_hex))
        if direction == 'up':
            tri = QPolygonF([QPointF(w / 2, 2), QPointF(w - 3, h - 2), QPointF(3, h - 2)])
        else:
            tri = QPolygonF([QPointF(3, 2), QPointF(w - 3, 2), QPointF(w / 2, h - 2)])
        p.drawPolygon(tri)
        p.end()
        pm.save(path, 'PNG')
    return path.replace('\\', '/')


def apply_palette(app, theme_name='dark'):
    """Set QApplication palette from the theme.

    Required in addition to setStyleSheet because Qt widgets with internal
    sub-widgets (QSpinBox's internal QLineEdit, QDoubleSpinBox, editable
    QComboBox lineEdit) consult QPalette.ColorRole.Base for their content
    background — stylesheet `background:` does not reach those sub-widgets.
    """
    from PyQt6.QtGui import QPalette, QColor
    t = THEMES[theme_name]
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Base,            QColor(t['bg2']))
    pal.setColor(QPalette.ColorRole.AlternateBase,   QColor(t['bg3']))
    pal.setColor(QPalette.ColorRole.Text,            QColor(t['fg']))
    pal.setColor(QPalette.ColorRole.Window,          QColor(t['bg']))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor(t['fg']))
    pal.setColor(QPalette.ColorRole.Button,          QColor(t['bg3']))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor(t['fg']))
    pal.setColor(QPalette.ColorRole.Highlight,       QColor(t['accent']))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor('#ffffff'))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(t['fg3']))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,
                 QColor(t['fg3']))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText,
                 QColor(t['fg3']))
    app.setPalette(pal)


def build_stylesheet(theme_name='dark'):
    t = THEMES[theme_name]
    _up = _arrow_png_uri(t['fg2'], 'up')
    _dn = _arrow_png_uri(t['fg2'], 'down')
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
QPushButton#success {{
    background: {t['green']};
    color: #000000;
    border: 1px solid {t['border']};
    font-weight: 600;
    padding: 5px 18px;
}}
QPushButton#success:hover {{ background: {t['green']}; border-color: {t['fg3']}; }}

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
QSpinBox, QDoubleSpinBox {{
    padding: 4px 22px 4px 8px;
    min-height: 24px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 16px;
    height: 11px;
    margin-right: 2px;
    margin-top: 1px;
    border: none;
    background: transparent;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 16px;
    height: 11px;
    margin-right: 2px;
    margin-bottom: 1px;
    border: none;
    background: transparent;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {t['bg3']};
    border-radius: 3px;
}}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
    background: {t['accent_bg']};
    border-radius: 3px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({_up}); width: 9px; height: 6px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({_dn}); width: 9px; height: 6px;
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
QComboBox::down-arrow {{ image: url({_dn}); width: 8px; height: 5px; }}
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
QLabel#mutedSmall {{ color: {t['fg2']}; font-size: 11px; }}
QLabel#mutedBold {{ color: {t['fg2']}; font-size: 12px; font-weight: 600; }}
QLabel#mutedLarge {{ color: {t['fg2']}; font-size: 14px; }}
QLabel#error {{ color: {t['red']}; font-size: 10px; }}
QLabel#ctxLabel {{ color: {t['fg2']}; font-size: 12px; background: transparent; }}
QLabel#section {{ color: {t['fg2']}; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
QWidget#hairlineSep {{ background: {t['border']}; }}
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
/* ── Collapsible card body ─── */
QWidget#cardBody {{
    background: {t['bg2']};
    border-left: 1px solid {t['border']};
    border-right: 1px solid {t['border']};
    border-bottom: 1px solid {t['border']};
    border-bottom-left-radius: 6px;
    border-bottom-right-radius: 6px;
}}
"""
