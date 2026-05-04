import math
from PyQt6.QtWidgets import QLabel, QWidget, QVBoxLayout
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QBrush, QPainterPath
from PyQt6.QtCore import Qt
from ..app.theme import C, T


def _make_logo_pixmap(size=32):
    """Draw the NM logo using QPainter — no SVG dependency."""
    from PyQt6.QtGui import QPainter, QFont, QFontMetrics
    from PyQt6.QtCore import QRectF

    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)

    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # Blue rounded rectangle
    radius = size * 0.22
    painter.setBrush(QColor('#4c8aff'))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    # White "NM" text — manually centred via QFontMetrics to avoid the
    # drawText(QRect, flags, str) overload which triggers sipBadCatcherResult
    # in some PyQt6 builds.
    painter.setPen(QColor('#eef2ff'))
    font = QFont()
    font.setPixelSize(max(10, int(size * 0.42)))
    font.setWeight(QFont.Weight.Black)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.5)
    painter.setFont(font)
    fm = QFontMetrics(font)
    tw = fm.horizontalAdvance('NM')
    x = (size - tw) // 2
    y = (size - fm.height()) // 2 + fm.ascent()
    painter.drawText(x, y, 'NM')

    painter.end()
    return px


_NAV_ICON_CACHE: dict = {}


def _make_nav_icon(name: str, size: int = 28, color: str = '#cccccc') -> QPixmap:
    """
    Draw a sidebar nav icon using QPainter — no image files, no emoji, no fonts.
    Works identically on macOS, Windows, Linux at any DPI.
    name: 'models' | 'tree' | 'evaluation' | 'vpc' | 'history' | 'settings'
    color: hex colour string, should match current theme fg
    """
    cache_key = (name, size, color)
    cached = _NAV_ICON_CACHE.get(cache_key)
    if cached is not None:
        return cached

    from PyQt6.QtGui import QPainter, QPainterPath, QPen, QBrush
    from PyQt6.QtCore import QPointF, QRectF

    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    pen = QPen(c); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    s = size

    if name == 'models':
        # Folder: tab on top-left, rectangle body
        sw = max(1.5, s * 0.07); pen.setWidthF(sw); p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        m = s * 0.12  # margin
        tab_w = s * 0.35; tab_h = s * 0.16
        body_t = m + tab_h * 0.8
        # folder tab
        path = QPainterPath()
        path.moveTo(m, body_t)
        path.lineTo(m, m + tab_h)
        path.lineTo(m + tab_w, m + tab_h)
        path.lineTo(m + tab_w + tab_h * 0.6, body_t)
        p.drawPath(path)
        # folder body
        p.drawRoundedRect(QRectF(m, body_t, s - 2*m, s - body_t - m), s*0.06, s*0.06)
        # three horizontal lines inside
        pen2 = QPen(c); pen2.setWidthF(sw * 0.8); pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen2)
        for i, frac in enumerate([0.42, 0.57, 0.72]):
            y = s * frac
            p.drawLine(QPointF(s*0.28, y), QPointF(s*0.82, y))

    elif name == 'tree':
        # Lineage tree: root node top-centre, two children below
        sw = max(1.5, s * 0.07); pen.setWidthF(sw); p.setPen(pen)
        r = s * 0.11  # node radius
        # root
        rx, ry = s*0.5, s*0.18
        p.setBrush(QBrush(c))
        p.drawEllipse(QPointF(rx, ry), r, r)
        # left child
        lx, ly = s*0.25, s*0.75
        p.drawEllipse(QPointF(lx, ly), r, r)
        # right child
        rx2, ry2 = s*0.75, s*0.75
        p.drawEllipse(QPointF(rx2, ry2), r, r)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # trunk down
        mid_y = s * 0.52
        p.drawLine(QPointF(s*0.5, ry+r), QPointF(s*0.5, mid_y))
        # horizontal bar
        p.drawLine(QPointF(lx, mid_y), QPointF(rx2, mid_y))
        # drops to children
        p.drawLine(QPointF(lx,  mid_y), QPointF(lx,  ly-r))
        p.drawLine(QPointF(rx2, mid_y), QPointF(rx2, ry2-r))

    elif name == 'evaluation':
        # Bar chart: three bars of increasing height
        sw = max(1.5, s * 0.07); pen.setWidthF(sw); p.setPen(pen)
        m = s * 0.12; bw = (s - 2*m) / 4.2
        heights = [0.35, 0.55, 0.78]
        baseline = s - m
        for i, h in enumerate(heights):
            x = m + i * (bw + bw*0.4)
            bar_h = s * h
            rect = QRectF(x, baseline - bar_h, bw, bar_h)
            p.setBrush(QBrush(c)); p.drawRoundedRect(rect, bw*0.2, bw*0.2)
        # baseline
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(m*0.6, baseline), QPointF(s-m*0.6, baseline))

    elif name == 'vpc':
        # Scatter plot with observation dots + prediction band
        sw = max(1.2, s * 0.06); pen.setWidthF(sw); p.setPen(pen)
        m = s * 0.13
        # axes
        p.drawLine(QPointF(m, m*0.8), QPointF(m, s-m))
        p.drawLine(QPointF(m, s-m), QPointF(s-m*0.8, s-m))
        # prediction band (filled, semi-transparent)
        band = QPainterPath()
        band.moveTo(m, s - m - s*0.1)
        band.cubicTo(s*0.35, s - m - s*0.35, s*0.55, s - m - s*0.25, s-m*0.9, s - m - s*0.55)
        band.lineTo(s-m*0.9, s - m - s*0.45)
        band.cubicTo(s*0.55, s - m - s*0.15, s*0.35, s - m - s*0.22, m, s - m - s*0.02)
        band.closeSubpath()
        band_color = QColor(color); band_color.setAlphaF(0.25)
        p.setBrush(QBrush(band_color)); p.setPen(Qt.PenStyle.NoPen); p.drawPath(band)
        # median line
        pen2 = QPen(c); pen2.setWidthF(sw*1.3)
        p.setPen(pen2); p.setBrush(Qt.BrushStyle.NoBrush)
        med = QPainterPath()
        med.moveTo(m, s - m - s*0.06)
        med.cubicTo(s*0.35, s - m - s*0.28, s*0.55, s - m - s*0.20, s-m*0.9, s - m - s*0.50)
        p.drawPath(med)
        # scatter dots
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
        for dx, dy in [(0.25,0.52),(0.38,0.35),(0.52,0.42),(0.65,0.28),(0.75,0.20)]:
            p.drawEllipse(QPointF(m + dx*(s-2*m), s-m - dy*(s-2*m)), s*0.04, s*0.04)

    elif name == 'history':
        # Clock face
        sw = max(1.5, s * 0.07); pen.setWidthF(sw); p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy, r = s*0.5, s*0.5, s*0.38
        p.drawEllipse(QPointF(cx, cy), r, r)
        # hour hand (pointing ~10 o'clock)
        h_angle = math.radians(-60); h_len = r * 0.55
        p.drawLine(QPointF(cx, cy),
                   QPointF(cx + h_len*math.sin(h_angle), cy - h_len*math.cos(h_angle)))
        # minute hand (pointing ~12)
        m_angle = math.radians(0); m_len = r * 0.75
        p.drawLine(QPointF(cx, cy),
                   QPointF(cx + m_len*math.sin(m_angle), cy - m_len*math.cos(m_angle)))
        # centre dot
        p.setBrush(QBrush(c)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), s*0.05, s*0.05)

    elif name == 'settings':
        # Gear: circle with teeth
        sw = max(1.2, s * 0.06); pen.setWidthF(sw); p.setPen(pen)
        cx, cy = s*0.5, s*0.5
        outer_r = s * 0.38; inner_r = s * 0.24; hole_r = s * 0.12
        teeth = 8; tooth_h = s * 0.09
        path = QPainterPath()
        for i in range(teeth * 2):
            angle = math.radians(i * 180 / teeth)
            r = outer_r if i % 2 == 0 else outer_r - tooth_h
            x = cx + r * math.cos(angle); y = cy + r * math.sin(angle)
            if i == 0: path.moveTo(x, y)
            else: path.lineTo(x, y)
        path.closeSubpath()
        p.setBrush(QBrush(c)); p.setPen(Qt.PenStyle.NoPen); p.drawPath(path)
        # inner cutout (draw in bg colour — transparent workaround)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.drawEllipse(QPointF(cx, cy), inner_r, inner_r)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        # centre hole
        p.setBrush(QBrush(c)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), hole_r, hole_r)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.drawEllipse(QPointF(cx, cy), hole_r * 0.5, hole_r * 0.5)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

    elif name == 'uncertainty':
        # Bell curve with confidence interval whiskers
        sw = max(1.5, s * 0.07); pen.setWidthF(sw); p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        m = s * 0.12
        cx, cy = s * 0.5, s * 0.65
        # Bell curve via bezier
        path = QPainterPath()
        path.moveTo(m, cy)
        path.cubicTo(s*0.25, cy, s*0.32, s*0.18, cx, s*0.18)
        path.cubicTo(s*0.68, s*0.18, s*0.75, cy, s-m, cy)
        p.drawPath(path)
        # Baseline
        p.drawLine(QPointF(m - s*0.02, cy + s*0.12), QPointF(s - m + s*0.02, cy + s*0.12))
        # Whiskers for CI
        whisker_y_top = cy - s*0.05
        whisker_y_bot = cy + s*0.12
        # Left whisker
        left_x = s * 0.28
        p.drawLine(QPointF(left_x, whisker_y_top), QPointF(left_x, whisker_y_bot))
        p.drawLine(QPointF(left_x - s*0.04, whisker_y_top), QPointF(left_x + s*0.04, whisker_y_top))
        # Right whisker
        right_x = s * 0.72
        p.drawLine(QPointF(right_x, whisker_y_top), QPointF(right_x, whisker_y_bot))
        p.drawLine(QPointF(right_x - s*0.04, whisker_y_top), QPointF(right_x + s*0.04, whisker_y_top))
        # Centre dot (mean)
        p.setBrush(QBrush(c)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy + s*0.12), s*0.04, s*0.04)

    elif name == 'simplot':
        # Simulation plot: axes + two filled PI ribbons + bold median line
        sw = max(1.2, s * 0.06); pen.setWidthF(sw); p.setPen(pen)
        m = s * 0.14
        # axes
        p.drawLine(QPointF(m, m*0.8), QPointF(m, s - m))
        p.drawLine(QPointF(m, s - m), QPointF(s - m*0.8, s - m))
        # outer ribbon (lighter)
        outer = QPainterPath()
        outer.moveTo(m, s - m - s*0.07)
        outer.cubicTo(s*0.4, s - m - s*0.38, s*0.6, s - m - s*0.28, s - m*0.9, s - m - s*0.60)
        outer.lineTo(s - m*0.9, s - m - s*0.44)
        outer.cubicTo(s*0.6, s - m - s*0.12, s*0.4, s - m - s*0.20, m, s - m - s*0.01)
        outer.closeSubpath()
        outer_c = QColor(color); outer_c.setAlphaF(0.18)
        p.setBrush(QBrush(outer_c)); p.setPen(Qt.PenStyle.NoPen); p.drawPath(outer)
        # inner ribbon (more opaque)
        inner = QPainterPath()
        inner.moveTo(m, s - m - s*0.10)
        inner.cubicTo(s*0.4, s - m - s*0.30, s*0.6, s - m - s*0.22, s - m*0.9, s - m - s*0.54)
        inner.lineTo(s - m*0.9, s - m - s*0.50)
        inner.cubicTo(s*0.6, s - m - s*0.18, s*0.4, s - m - s*0.24, m, s - m - s*0.04)
        inner.closeSubpath()
        inner_c = QColor(color); inner_c.setAlphaF(0.35)
        p.setBrush(QBrush(inner_c)); p.setPen(Qt.PenStyle.NoPen); p.drawPath(inner)
        # median line
        pen_med = QPen(c); pen_med.setWidthF(sw * 1.5)
        pen_med.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_med); p.setBrush(Qt.BrushStyle.NoBrush)
        med = QPainterPath()
        med.moveTo(m, s - m - s*0.055)
        med.cubicTo(s*0.4, s - m - s*0.26, s*0.6, s - m - s*0.20, s - m*0.9, s - m - s*0.52)
        p.drawPath(med)

    elif name == 'fileexplorer':
        # Document with folded corner and text lines — file browser
        sw = max(1.5, s * 0.07); pen.setWidthF(sw); p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        m = s * 0.12; fold = s * 0.22
        path = QPainterPath()
        path.moveTo(m, m)
        path.lineTo(s - m - fold, m)
        path.lineTo(s - m, m + fold)
        path.lineTo(s - m, s - m)
        path.lineTo(m, s - m)
        path.closeSubpath()
        p.drawPath(path)
        fold_path = QPainterPath()
        fold_path.moveTo(s - m - fold, m)
        fold_path.lineTo(s - m - fold, m + fold)
        fold_path.lineTo(s - m, m + fold)
        p.drawPath(fold_path)
        pen2 = QPen(c); pen2.setWidthF(sw * 0.8); pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen2)
        for frac in [0.46, 0.60, 0.74]:
            y = s * frac
            p.drawLine(QPointF(s * 0.25, y), QPointF(s * 0.78, y))

    p.end()
    _NAV_ICON_CACHE[cache_key] = px
    return px


def _placeholder(msg):
    lbl = QLabel(msg); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setObjectName('mutedLarge'); return lbl
