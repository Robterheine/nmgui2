import sys

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QWidget,
)
from PyQt6.QtCore import Qt

from ..app.constants import APP_VERSION
from ..app.theme import C, T
from ..widgets._icons import _make_logo_pixmap

try:
    import pyqtgraph as pg
    HAS_PG = True
except ImportError:
    HAS_PG = False

try:
    import numpy  # noqa: F401
    HAS_NP = True
except ImportError:
    HAS_NP = False


def _pyqt6_version():
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR
        return PYQT_VERSION_STR
    except Exception:
        return 'unknown'


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('About NMGUI')
        self.setFixedWidth(480)
        self.setModal(True)
        v = QVBoxLayout(self); v.setSpacing(0); v.setContentsMargins(0,0,0,0)

        # Coloured header band
        header = QWidget()
        header.setStyleSheet(f'background:{C.blue};')
        header.setFixedHeight(80)
        hl = QHBoxLayout(header); hl.setContentsMargins(24,0,24,0); hl.setSpacing(16)
        logo_lbl = QLabel(); logo_lbl.setPixmap(_make_logo_pixmap(48)); logo_lbl.setFixedSize(48,48)
        title_col = QVBoxLayout(); title_col.setSpacing(2)
        title_lbl = QLabel('NMGUI')
        title_lbl.setStyleSheet('font-size:24px;font-weight:800;color:#ffffff;background:transparent;')
        sub_lbl   = QLabel(f'v{APP_VERSION}  ·  NONMEM Run Manager')
        sub_lbl.setStyleSheet('font-size:11px;color:rgba(255,255,255,180);background:transparent;')
        title_col.addWidget(title_lbl); title_col.addWidget(sub_lbl)
        hl.addWidget(logo_lbl); hl.addLayout(title_col); hl.addStretch()
        v.addWidget(header)

        # Body
        body = QWidget(); bv = QVBoxLayout(body)
        bv.setContentsMargins(24,20,24,20); bv.setSpacing(14)

        # Purpose
        purpose = QLabel(
            'A standalone desktop application for pharmacometric modelling workflows — '
            'manage NONMEM models, visualise diagnostics, run PsN tools, and compare '
            'model output without leaving one window.')
        purpose.setWordWrap(True)
        purpose.setStyleSheet(f'font-size:12px;color:{C.fg};line-height:1.5;')
        bv.addWidget(purpose)

        sep1 = QFrame(); sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet(f'color:{C.border};'); bv.addWidget(sep1)

        # Author
        author = QLabel(
            f'<b>Author</b><br>'
            f'Rob ter Heine — Hospital pharmacist &amp; clinical pharmacologist<br>'
            f'<a href="https://www.radboudumc.nl/en/research/research-groups/'
            f'radboud-applied-pharmacometrics" style="color:#4c8aff;">'
            f'Radboud Applied Pharmacometrics</a>  ·  Radboudumc, Nijmegen')
        author.setOpenExternalLinks(True)
        author.setWordWrap(True)
        author.setStyleSheet(f'font-size:12px;color:{C.fg};')
        bv.addWidget(author)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f'color:{C.border};'); bv.addWidget(sep2)

        # Source & contribute
        source = QLabel(
            f'<b>Source code</b><br>'
            f'<a href="https://github.com/robterheine/NMGUI2" style="color:#4c8aff;">'
            f'github.com/robterheine/NMGUI2</a><br><br>'
            f'<b>Contributions welcome!</b> Open an issue or pull request if you\'d like '
            f'to improve NMGUI — bug reports, feature requests and code contributions '
            f'are all appreciated.')
        source.setOpenExternalLinks(True)
        source.setWordWrap(True)
        source.setStyleSheet(f'font-size:12px;color:{C.fg};')
        bv.addWidget(source)

        sep3 = QFrame(); sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet(f'color:{C.border};'); bv.addWidget(sep3)

        # AI + environment
        pg_ver = pg.__version__ if HAS_PG else 'not installed'
        np_ver = 'installed' if HAS_NP else 'not installed'
        env = QLabel(
            f'<b>Developed with</b>  <a href="https://claude.ai" style="color:{C.blue};">Anthropic Claude</a><br><br>'
            f'<b>Environment</b><br>'
            f'Python {sys.version.split()[0]}  ·  '
            f'PyQt6 {_pyqt6_version()}  ·  '
            f'pyqtgraph {pg_ver}  ·  numpy {np_ver}')
        env.setOpenExternalLinks(True)
        env.setWordWrap(True)
        env.setStyleSheet(f'font-size:11px;color:{C.fg2};')
        bv.addWidget(env)

        v.addWidget(body)

        # Footer buttons
        foot = QWidget(); foot.setStyleSheet(f'background:{T("bg3")};border-top:1px solid {T("border")};')
        fl = QHBoxLayout(foot); fl.setContentsMargins(16,12,16,12)
        gh_btn = QPushButton('Open GitHub')
        gh_btn.setFixedHeight(32)
        gh_btn.setStyleSheet(f'''
            QPushButton {{
                background: {T("bg2")};
                color: {T("fg")};
                border: 1px solid {T("border")};
                border-radius: 6px;
                padding: 4px 16px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: {T("bg3")};
                border-color: {T("fg2")};
            }}
        ''')
        gh_btn.clicked.connect(lambda: __import__('webbrowser').open('https://github.com/robterheine/NMGUI2'))
        close = QPushButton('Close')
        close.setFixedHeight(32)
        close.setStyleSheet(f'''
            QPushButton {{
                background: {T("accent")};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 4px 24px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: #3a7ae0;
            }}
        ''')
        close.clicked.connect(self.accept)
        fl.addWidget(gh_btn); fl.addStretch(); fl.addWidget(close)
        v.addWidget(foot)
