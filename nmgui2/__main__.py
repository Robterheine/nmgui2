import sys
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt
from .app.constants import APP_VERSION
from .app.theme import THEMES, set_active_theme, build_stylesheet, apply_palette
from .app.config import load_settings

try:
    import pyqtgraph as pg
    HAS_PG = True
except ImportError:
    HAS_PG = False

try:
    from . import parser as _parser_mod
    HAS_PARSER = True
    _PARSER_ERR = ''
except ImportError as e:
    HAS_PARSER = False
    _PARSER_ERR = str(e)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('NMGUI')
    app.setApplicationVersion(APP_VERSION)
    app.setStyle('Fusion')

    saved_theme = (load_settings().get('theme') or 'dark')
    set_active_theme(saved_theme)
    if HAS_PG:
        t = THEMES[saved_theme]
        pg.setConfigOptions(background=t['pg_bg'], foreground=t['pg_fg'])
    apply_palette(app, saved_theme)
    app.setStyleSheet(build_stylesheet(saved_theme))

    if not HAS_PARSER:
        msg = QMessageBox(QMessageBox.Icon.Critical, 'Setup required', '')
        msg.setText('<b>parser module not found</b>')
        msg.setInformativeText(
            'The nmgui2 package requires the parser module.<br><br>'
            '<b>Steps to fix:</b><br>'
            '1. Clone or download the NMGUI repository from GitHub<br>'
            '2. Make sure parser.py is present in the nmgui2/ package folder<br>'
            '3. Run: <tt>python3 -m nmgui2</tt> from the repository directory<br><br>'
            f'<small>Technical detail: {_PARSER_ERR}</small>'
        )
        msg.setTextFormat(Qt.TextFormat.RichText)
        github_btn = msg.addButton('Open GitHub', QMessageBox.ButtonRole.HelpRole)
        msg.addButton('Quit', QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is github_btn:
            import webbrowser
            webbrowser.open('https://github.com/robterheine/NMGUI2')
        sys.exit(1)

    from .app.main_window import MainWindow
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
